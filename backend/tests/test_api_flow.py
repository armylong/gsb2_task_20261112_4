"""端到端 API 流程: 导入(幂等) → 规则版本 → 清洗(幂等/追溯) → 版本 diff → 对账 → 导出。"""
from __future__ import annotations

from pathlib import Path

from app.main import app

DEMO_DIR = Path(__file__).resolve().parent.parent.parent / "demo_data"


def _upload(client, label: str, file_name: str) -> dict:
    with (DEMO_DIR / file_name).open("rb") as fh:
        response = client.post(
            "/api/imports/upload",
            data={"source_label": label},
            files={"file": (file_name, fh, "text/csv")},
        )
    assert response.status_code == 200, response.text
    return response.json()


def _rule_v1(batch_a: int, batch_b: int) -> dict:
    return {
        "name": "演示规则",
        "note": "初始版本",
        "config": {
            "sources": [
                {
                    "source_label": "CRM",
                    "batch_id": batch_a,
                    "field_mappings": {
                        "biz_no": "业务编号",
                        "amount": "订单金额",
                        "order_date": "下单日期",
                        "channel": "渠道",
                        "status": "单据状态",
                    },
                    "derived_fields": {"full_name": "${姓氏}${名字}"},
                    "value_maps": {
                        "status": {
                            "已完成": "completed",
                            "已退款": "refunded",
                            "已取消": "cancelled",
                        }
                    },
                    "dedupe_key": "biz_no",
                    "dedupe_strategy": "keep_first",
                    "required_fields": ["biz_no", "amount", "order_date"],
                },
                {
                    "source_label": "ERP",
                    "batch_id": batch_b,
                    "field_mappings": {
                        "biz_no": "bizNo",
                        "amount": "amount",
                        "order_date": "orderDate",
                        "channel": "salesChannel",
                        "status": "recordStatus",
                    },
                    "derived_fields": {"full_name": "${firstName} ${lastName}"},
                    "value_maps": {
                        "status": {
                            "COMPLETED": "completed",
                            "REFUNDED": "refunded",
                            "CANCELLED": "cancelled",
                        },
                        "channel": {
                            "online": "线上",
                            "store": "门店",
                            "dealer": "渠道商",
                        },
                    },
                    "dedupe_key": "biz_no",
                    "dedupe_strategy": "priority",
                    "priority_field": "dataTier",
                    "priority_desc": True,
                    "required_fields": ["biz_no", "amount", "order_date"],
                },
            ]
        },
    }


def _wait_run(client, run_id: int) -> dict:
    detail = client.get(f"/api/runs/{run_id}").json()
    assert detail["status"] != "failed", detail
    return detail


def test_full_flow(client) -> None:
    # 1. 导入 + 幂等复用
    first_a = _upload(client, "CRM", "source_a_crm.csv")
    again_a = _upload(client, "CRM", "source_a_crm.csv")
    first_b = _upload(client, "ERP", "source_b_erp.json")
    again_b = _upload(client, "ERP", "source_b_erp.json")

    assert first_a["reused"] is False and first_a["total_rows"] == 13
    assert again_a["reused"] is True
    assert again_a["batch"]["id"] == first_a["batch"]["id"]
    assert first_b["total_rows"] == 13 and again_b["reused"] is True
    batches = client.get("/api/imports").json()
    assert len(batches) == 2

    # 2. 创建规则 v1 并清洗
    rule = client.post("/api/rules", json=_rule_v1(first_a["batch"]["id"],
                                                   first_b["batch"]["id"])).json()
    assert rule["version"] == 1
    run1 = client.post("/api/runs", json={"rule_version_id": rule["id"]}).json()
    detail1 = _wait_run(client, run1["id"])
    assert detail1["status"] == "completed"

    stats1 = detail1["stats"]
    assert stats1["kept_rows"] == 22  # 每边 11 条
    assert stats1["invalid_rows"] == 2
    assert stats1["dropped_duplicates"] == 2
    assert len(detail1["records"]) == 22

    # 3. 追溯字段与转换结果
    crm_1001 = next(
        r for r in detail1["records"]
        if r["source_label"] == "CRM" and r["data"]["biz_no"] == "BIZ-1001"
    )
    assert (crm_1001["source_file"], crm_1001["source_row"]) == ("source_a_crm.csv", 2)
    assert crm_1001["data"]["full_name"] == "张伟"
    assert crm_1001["data"]["amount"] == 1200.0
    assert crm_1001["data"]["order_date"] == "2026-10-01"
    assert crm_1001["data"]["status"] == "completed"

    erp_1001 = next(
        r for r in detail1["records"]
        if r["source_label"] == "ERP" and r["data"]["biz_no"] == "BIZ-1001"
    )
    assert erp_1001["data"]["full_name"] == "Wei Zhang"
    assert erp_1001["data"]["channel"] == "线上"

    # ERP 优先级去重: BIZ-1003 保留 dataTier=2 的第 4 行(渠道商)
    erp_1003 = next(
        r for r in detail1["records"]
        if r["source_label"] == "ERP" and r["data"]["biz_no"] == "BIZ-1003"
    )
    assert erp_1003["source_row"] == 4
    assert erp_1003["data"]["channel"] == "渠道商"

    # 无效行可追溯
    invalid_keys = {(row["source_label"], row["source_row"])
                    for row in detail1["invalid_rows"]}
    assert ("CRM", 14) in invalid_keys   # 金额缺失
    assert ("ERP", 13) in invalid_keys   # 2026-02-30 非法日期

    # 4. 重跑幂等: 同样输入再跑一次, 条数完全一致, 不会累加
    run2 = client.post("/api/runs", json={"rule_version_id": rule["id"]}).json()
    detail2 = _wait_run(client, run2["id"])
    assert len(detail2["records"]) == len(detail1["records"]) == 22

    # 5. 同规则两次 run 的 diff 应为零差异
    diff = client.get(f"/api/runs/diff/{run1['id']}/{run2['id']}").json()
    assert diff["summary"] == {
        "base_count": 22, "target_count": 22,
        "added": 0, "removed": 0, "changed": 0,
    }

    # 6. 改规则生成 v2, diff 应能识别字段变化
    v2_payload = _rule_v1(first_a["batch"]["id"], first_b["batch"]["id"])
    v2_payload["note"] = "调整状态映射"
    v2_payload["config"]["sources"][0]["value_maps"]["status"]["已完成"] = "done"
    rule2 = client.post("/api/rules", json=v2_payload).json()
    assert rule2["version"] == 2
    run3 = client.post("/api/runs", json={"rule_version_id": rule2["id"]}).json()
    detail3 = _wait_run(client, run3["id"])
    diff2 = client.get(f"/api/runs/diff/{run1['id']}/{run3['id']}").json()
    assert diff2["summary"]["changed"] == 9  # 9 条 CRM 已完成记录
    sample = diff2["changed"][0]
    assert sample["field_diffs"][0]["field"] == "status"
    assert sample["field_diffs"][0]["before"] == "completed"
    assert sample["field_diffs"][0]["after"] == "done"

    # 7. 对账(基于 v1 的 run1): 2 个字段差异 + 2 条单边, 8 条完全匹配
    recon = client.post("/api/recon", json={
        "run_id": run1["id"],
        "left_label": "CRM",
        "right_label": "ERP",
        "key_field": "biz_no",
        "compare_fields": ["amount", "order_date", "channel", "status"],
        "amount_tolerance": 0.0,
    }).json()
    job_id = recon["id"]
    job = client.get(f"/api/recon/{job_id}").json()
    assert job["status"] == "completed"
    assert job["stats"]["matched"] == 8
    assert job["stats"]["field_mismatch"] == 2
    assert job["stats"]["only_left"] == 1
    assert job["stats"]["only_right"] == 1

    entries = client.get(f"/api/recon/{job_id}/entries").json()
    mismatch_keys = {e["key_value"] for e in entries if e["match_type"] == "field_mismatch"}
    assert mismatch_keys == {"BIZ-1005", "BIZ-1006"}
    one_sided = {e["key_value"] for e in entries
                 if e["match_type"] in ("only_left", "only_right")}
    assert one_sided == {"BIZ-1011", "BIZ-1012"}
    amount_diff = next(
        e for e in entries
        if e["key_value"] == "BIZ-1005"
    )
    assert amount_diff["diffs"][0]["left"] == 15600.0
    assert amount_diff["diffs"][0]["right"] == 1560.0
    # 差异条目保留来源追溯
    assert amount_diff["left_file"] == "source_a_crm.csv"
    assert amount_diff["right_row"] == 6

    # 8. 导出(清洗结果用 v2 的 run3, 验证规则变更后的产物也能导出)
    export_run = client.post(f"/api/exports/run/{run3['id']}").json()
    assert export_run["row_count"] == 22
    download = client.get(export_run["download_url"])
    assert download.status_code == 200
    assert "source_row" in download.text

    export_recon = client.post(f"/api/exports/recon/{job_id}").json()
    recon_csv = client.get(export_recon["download_url"]).text
    assert "BIZ-1005" in recon_csv and "字段不一致" in recon_csv
