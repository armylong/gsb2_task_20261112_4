"""两来源对账: 按业务键外连接, 输出匹配、字段差异与单边记录。"""
from __future__ import annotations

from typing import Any

from .config import TARGET_SCHEMA


def _values_equal(left: Any, right: Any, field: str, tolerance: float) -> tuple[bool, Any, Any]:
    if field == "amount" and tolerance > 0:
        try:
            lv, rv = float(left), float(right)
            return abs(lv - rv) <= tolerance, lv, rv
        except (TypeError, ValueError):
            pass
    return left == right, left, right


def reconcile(
    left_records: list[dict[str, Any]],
    right_records: list[dict[str, Any]],
    key_field: str,
    compare_fields: list[str],
    amount_tolerance: float,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """返回 (差异/单边条目, 统计)。完全匹配的记录只计入统计, 不生成条目。"""
    left_map: dict[str, dict[str, Any]] = {}
    right_map: dict[str, dict[str, Any]] = {}
    left_dupes: list[dict[str, Any]] = []
    right_dupes: list[dict[str, Any]] = []

    for record in left_records:
        key = str(record["data"].get(key_field) or "")
        if key in left_map:
            left_dupes.append(record)
        else:
            left_map[key] = record
    for record in right_records:
        key = str(record["data"].get(key_field) or "")
        if key in right_map:
            right_dupes.append(record)
        else:
            right_map[key] = record

    all_keys = sorted(set(left_map) | set(right_map))
    entries: list[dict[str, Any]] = []
    stats = {
        "left_count": len(left_records),
        "right_count": len(right_records),
        "matched": 0,
        "field_mismatch": 0,
        "only_left": 0,
        "only_right": 0,
        "left_duplicate_keys": len(left_dupes),
        "right_duplicate_keys": len(right_dupes),
        "total_diff_entries": 0,
    }

    for key in all_keys:
        left = left_map.get(key)
        right = right_map.get(key)

        if left and not right:
            stats["only_left"] += 1
            entries.append(_entry("only_left", key, left, None, []))
            continue
        if right and not left:
            stats["only_right"] += 1
            entries.append(_entry("only_right", key, None, right, []))
            continue

        assert left and right
        diffs: list[dict[str, Any]] = []
        for field in compare_fields:
            lv = left["data"].get(field)
            rv = right["data"].get(field)
            equal, norm_lv, norm_rv = _values_equal(lv, rv, field, amount_tolerance)
            if not equal:
                diffs.append({
                    "field": field,
                    "field_label": TARGET_SCHEMA.get(field, field),
                    "left": norm_lv,
                    "right": norm_rv,
                })
        if diffs:
            stats["field_mismatch"] += 1
            entries.append(_entry("field_mismatch", key, left, right, diffs))
        else:
            stats["matched"] += 1

    stats["total_diff_entries"] = len(entries)
    return entries, stats


def _entry(
    match_type: str,
    key: str,
    left: dict[str, Any] | None,
    right: dict[str, Any] | None,
    diffs: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "match_type": match_type,
        "key_value": key,
        "left": left,
        "right": right,
        "diffs": diffs,
    }
