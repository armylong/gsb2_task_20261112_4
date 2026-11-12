"""对账: 匹配、字段差异、单边记录、金额容差。"""
from __future__ import annotations

from app.reconcile import reconcile


def _rec(key: str, amount: float | None = None, date: str | None = None) -> dict:
    return {
        "source_label": "x",
        "source_file": "f",
        "source_row": 1,
        "batch_id": 1,
        "data": {"biz_no": key, "amount": amount, "order_date": date},
    }


def test_matched_mismatch_and_one_sided() -> None:
    left = [_rec("K1", 100.0, "2026-10-01"), _rec("K2", 200.0), _rec("K3")]
    right = [_rec("K1", 100.0, "2026-10-01"), _rec("K2", 210.0), _rec("K4")]
    entries, stats = reconcile(left, right, "biz_no", ["amount", "order_date"], 0.0)

    assert stats["matched"] == 1
    assert stats["field_mismatch"] == 1
    assert stats["only_left"] == 1
    assert stats["only_right"] == 1
    types = {e["match_type"] for e in entries}
    assert types == {"field_mismatch", "only_left", "only_right"}

    mismatch = next(e for e in entries if e["match_type"] == "field_mismatch")
    assert mismatch["key_value"] == "K2"
    assert mismatch["diffs"][0]["field"] == "amount"


def test_amount_tolerance() -> None:
    left = [_rec("K1", 100.0)]
    right = [_rec("K1", 100.3)]
    _, stats = reconcile(left, right, "biz_no", ["amount"], 0.5)
    assert stats["matched"] == 1

    entries, _ = reconcile(left, right, "biz_no", ["amount"], 0.01)
    assert entries[0]["match_type"] == "field_mismatch"


def test_none_date_difference_detected() -> None:
    left = [_rec("K1", date="2026-10-01")]
    right = [_rec("K1", date="2026-10-16")]
    entries, stats = reconcile(left, right, "biz_no", ["order_date"], 0.0)
    assert stats["field_mismatch"] == 1
    assert entries[0]["diffs"][0]["field"] == "order_date"
