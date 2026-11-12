"""转换引擎: 类型转换、派生表达式、必填校验、去重。"""
from __future__ import annotations

import pytest

from app.transform import (
    TransformError,
    clean_source,
    convert_date,
    convert_decimal,
    parse_expression,
)


def test_decimal_accepts_str_int_and_mixed_decimals() -> None:
    assert convert_decimal("1200.00") == 1200.0
    assert convert_decimal(850.5) == 850.5
    assert convert_decimal("1,200.5") == 1200.5
    with pytest.raises(TransformError):
        convert_decimal("")
    with pytest.raises(TransformError):
        convert_decimal("abc")


def test_date_parses_chinese_slash_and_iso() -> None:
    assert convert_date("2026/10/01") == "2026-10-01"
    assert convert_date("2026-10-01T09:30:00") == "2026-10-01"
    assert convert_date("20261001") == "2026-10-01"
    with pytest.raises(TransformError):
        convert_date("2026-02-30T10:00:00")
    with pytest.raises(TransformError):
        convert_date("not-a-date")


def test_derived_template_and_functions() -> None:
    row = {"姓氏": "张", "名字": "伟", "en": " abc "}
    assert parse_expression("${姓氏}${名字}").evaluate(row) == "张伟"
    assert parse_expression('concat(${姓氏}, "-", ${名字})').evaluate(row) == "张-伟"
    assert parse_expression("upper(${en})").evaluate(row) == " ABC "
    assert parse_expression("trim(${en})").evaluate(row) == "abc"
    assert parse_expression("coalesce(${missing}, ${en})").evaluate(row) == " abc "


def test_null_tokens_normalized() -> None:
    rule = {
        "field_mappings": {"biz_no": "编号", "channel": "渠道"},
        "null_tokens": ["-", "null", ""],
        "required_fields": ["biz_no"],
        "dedupe_key": None,
    }
    rows = [
        {"row_no": 2, "data": {"编号": "A1", "渠道": "-"}},
        {"row_no": 3, "data": {"编号": "A2", "渠道": "null"}},
    ]
    result = clean_source("s", "f.csv", 1, rows, rule)
    assert result.stats["invalid_rows"] == 0
    assert result.records[0]["data"]["channel"] is None
    assert result.records[1]["data"]["channel"] is None


def test_required_validation_collects_invalid_rows() -> None:
    rule = {
        "field_mappings": {"biz_no": "编号", "amount": "金额"},
        "required_fields": ["biz_no", "amount"],
        "dedupe_key": None,
    }
    rows = [
        {"row_no": 2, "data": {"编号": "A1", "金额": "100"}},
        {"row_no": 3, "data": {"编号": "", "金额": "200"}},
        {"row_no": 4, "data": {"编号": "A3", "金额": ""}},
    ]
    result = clean_source("s", "f.csv", 1, rows, rule)
    assert len(result.records) == 1
    assert len(result.invalid_rows) == 2
    assert result.invalid_rows[0]["source_row"] == 3
    assert any("必填字段 biz_no" in e for e in result.invalid_rows[0]["errors"])


def test_dedupe_keep_first_keeps_smallest_row_no() -> None:
    rule = {
        "field_mappings": {"biz_no": "编号"},
        "required_fields": ["biz_no"],
        "dedupe_key": "biz_no",
        "dedupe_strategy": "keep_first",
    }
    rows = [
        {"row_no": 2, "data": {"编号": "A1"}},
        {"row_no": 5, "data": {"编号": "A1"}},
        {"row_no": 7, "data": {"编号": "A2"}},
    ]
    result = clean_source("s", "f.csv", 1, rows, rule)
    assert len(result.records) == 2
    keys = {r["data"]["biz_no"]: r["source_row"] for r in result.records}
    assert keys == {"A1": 2, "A2": 7}
    assert result.dropped_duplicates[0]["dropped_row"] == 5


def test_dedupe_priority_uses_source_field() -> None:
    rule = {
        "field_mappings": {"biz_no": "编号"},
        "required_fields": ["biz_no"],
        "dedupe_key": "biz_no",
        "dedupe_strategy": "priority",
        "priority_field": "tier",
        "priority_desc": True,
    }
    rows = [
        {"row_no": 1, "data": {"编号": "A1", "tier": 1}},
        {"row_no": 2, "data": {"编号": "A1", "tier": 2}},
        {"row_no": 3, "data": {"编号": "A1", "tier": 2}},
    ]
    result = clean_source("s", "f.csv", 1, rows, rule)
    assert len(result.records) == 1
    # tier 最高者胜出, 同 tier 行号小者稳定胜出
    assert result.records[0]["source_row"] == 2
    assert len(result.dropped_duplicates) == 2


def test_trace_fields_preserved() -> None:
    rule = {"field_mappings": {"biz_no": "编号"}, "required_fields": ["biz_no"]}
    rows = [{"row_no": 42, "data": {"编号": "A1"}}]
    result = clean_source("crm", "source_a.csv", 7, rows, rule)
    record = result.records[0]
    assert record["source_label"] == "crm"
    assert record["source_file"] == "source_a.csv"
    assert record["source_row"] == 42
    assert record["batch_id"] == 7
