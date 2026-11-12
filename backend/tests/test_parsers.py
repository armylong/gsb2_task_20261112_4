"""解析器: CSV 物理行号、JSON 序号、空值与错误格式。"""
from __future__ import annotations

import pytest

from app.parsers import FileParseError, parse_csv, parse_json


def test_csv_row_no_matches_physical_line() -> None:
    content = "编号,金额\nA1,100\nA2,200\n".encode("utf-8")
    columns, rows = parse_csv(content)
    assert columns == ["编号", "金额"]
    assert [r["row_no"] for r in rows] == [2, 3]
    assert rows[0]["data"] == {"编号": "A1", "金额": "100"}


def test_json_supports_records_wrapper_and_null() -> None:
    payload = (
        '{"records": ['
        '{"bizNo": "A1", "channel": null},'
        '{"bizNo": "A2", "channel": "store"}'
        "]}"
    ).encode("utf-8")
    columns, rows = parse_json(payload)
    assert columns == ["bizNo", "channel"]
    assert [r["row_no"] for r in rows] == [1, 2]
    assert rows[0]["data"]["channel"] is None


def test_json_accepts_bare_array() -> None:
    columns, rows = parse_json(b'[{"a": 1}]')
    assert columns == ["a"] and rows[0]["row_no"] == 1


def test_bad_json_raises() -> None:
    with pytest.raises(FileParseError):
        parse_json(b"{not json}")
