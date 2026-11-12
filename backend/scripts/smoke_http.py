"""真实 HTTP 端到端冒烟: 通过运行中的 uvicorn 走完整业务链路。

用法:
    uvicorn app.main:app --port 8011 &
    python scripts/smoke_http.py [base_url]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8011"
DEMO = str(Path(__file__).resolve().parents[2] / "demo_data")


def wait_ready() -> None:
    for _ in range(50):
        try:
            if httpx.get(f"{BASE}/api/health", timeout=1).json()["status"] == "ok":
                return
        except httpx.TransportError:
            time.sleep(0.2)
    raise SystemExit("server not ready")


def poll(url: str) -> dict:
    for _ in range(50):
        data = httpx.get(url, timeout=5).json()
        if data["status"] in ("completed", "failed"):
            assert data["status"] == "completed", data
            return data
        time.sleep(0.2)
    raise SystemExit(f"timeout polling {url}")


def main() -> None:
    wait_ready()
    print("1. health OK")

    def upload(label: str, path: str) -> dict:
        with open(path, "rb") as fh:
            return httpx.post(
                f"{BASE}/api/imports/upload",
                data={"source_label": label},
                files={"file": (path.split("/")[-1], fh, "application/octet-stream")},
                timeout=10,
            ).json()

    a1 = upload("CRM", f"{DEMO}/source_a_crm.csv")
    a2 = upload("CRM", f"{DEMO}/source_a_crm.csv")
    b1 = upload("ERP", f"{DEMO}/source_b_erp.json")
    assert a1["reused"] is False and a2["reused"] is True, (a1, a2)
    assert b1["total_rows"] == 13
    batches = httpx.get(f"{BASE}/api/imports", timeout=5).json()
    assert len(batches) == 2
    print("2. 导入幂等 OK, 批次 =", [b["file_name"] for b in batches])

    rule_payload = {
        "name": "冒烟规则",
        "note": "smoke",
        "config": {"sources": [
            {
                "source_label": "CRM", "batch_id": a1["batch"]["id"],
                "field_mappings": {
                    "biz_no": "业务编号", "amount": "订单金额",
                    "order_date": "下单日期", "channel": "渠道", "status": "单据状态",
                },
                "derived_fields": {"full_name": "${姓氏}${名字}"},
                "value_maps": {"status": {"已完成": "completed", "已退款": "refunded",
                                           "已取消": "cancelled"}},
                "dedupe_key": "biz_no", "dedupe_strategy": "keep_first",
                "required_fields": ["biz_no", "amount", "order_date"],
            },
            {
                "source_label": "ERP", "batch_id": b1["batch"]["id"],
                "field_mappings": {
                    "biz_no": "bizNo", "amount": "amount", "order_date": "orderDate",
                    "channel": "salesChannel", "status": "recordStatus",
                },
                "derived_fields": {"full_name": "${firstName} ${lastName}"},
                "value_maps": {
                    "status": {"COMPLETED": "completed", "REFUNDED": "refunded",
                               "CANCELLED": "cancelled"},
                    "channel": {"online": "线上", "store": "门店", "dealer": "渠道商"},
                },
                "dedupe_key": "biz_no", "dedupe_strategy": "priority",
                "priority_field": "dataTier", "priority_desc": True,
                "required_fields": ["biz_no", "amount", "order_date"],
            },
        ]},
    }

    preview = httpx.post(f"{BASE}/api/rules/preview", json=rule_payload, timeout=10).json()
    assert preview["total_kept"] == 22 and preview["total_invalid"] == 2
    print("3. 试清洗预览 OK: kept =", preview["total_kept"])

    rule = httpx.post(f"{BASE}/api/rules", json=rule_payload, timeout=10).json()
    run = httpx.post(f"{BASE}/api/runs", json={"rule_version_id": rule["id"]},
                     timeout=10).json()
    detail = poll(f"{BASE}/api/runs/{run['id']}")
    assert detail["stats"]["kept_rows"] == 22
    assert len(detail["records"]) == 22
    print("4. 清洗 OK, 状态:", detail["stats"])

    # 重跑验证幂等
    run2 = httpx.post(f"{BASE}/api/runs", json={"rule_version_id": rule["id"]},
                      timeout=10).json()
    detail2 = poll(f"{BASE}/api/runs/{run2['id']}")
    assert len(detail2["records"]) == 22
    diff = httpx.get(f"{BASE}/api/runs/diff/{run['id']}/{run2['id']}",
                     timeout=10).json()
    assert diff["summary"]["changed"] == 0
    print("5. 重跑幂等 + 零差异 OK")

    recon = httpx.post(f"{BASE}/api/recon", json={
        "run_id": run["id"], "left_label": "CRM", "right_label": "ERP",
        "key_field": "biz_no",
        "compare_fields": ["amount", "order_date", "channel", "status"],
        "amount_tolerance": 0,
    }, timeout=10).json()
    job = poll(f"{BASE}/api/recon/{recon['id']}")
    assert job["stats"] == {
        "left_count": 11, "right_count": 11, "matched": 8,
        "field_mismatch": 2, "only_left": 1, "only_right": 1,
        "left_duplicate_keys": 0, "right_duplicate_keys": 0, "total_diff_entries": 4,
    }, job["stats"]
    print("6. 对账 OK:", job["stats"])

    export1 = httpx.post(f"{BASE}/api/exports/run/{run['id']}", timeout=10).json()
    export2 = httpx.post(f"{BASE}/api/exports/recon/{recon['id']}", timeout=10).json()
    csv1 = httpx.get(f"{BASE}{export1['download_url']}", timeout=10).text
    csv2 = httpx.get(f"{BASE}{export2['download_url']}", timeout=10).text
    assert "source_a_crm.csv,2" in csv1.replace('"', "").replace("\r", "")
    assert "BIZ-1005" in csv2
    print("7. 导出 OK:", export1["file_name"], "/", export2["file_name"])

    # 前端构建产物由后端托管
    page = httpx.get(f"{BASE}/", timeout=10)
    assert page.status_code == 200 and '<div id="app">' in page.text
    deep = httpx.get(f"{BASE}/some/spa/route", timeout=10)
    assert deep.status_code == 200 and '<div id="app">' in deep.text
    print("8. SPA 托管 + history fallback OK")
    print("\nALL SMOKE CHECKS PASSED")


if __name__ == "__main__":
    main()
