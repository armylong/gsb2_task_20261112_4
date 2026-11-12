"""CSV / JSON 文件解析。

行号约定:
- CSV: 含表头, 第一条数据行 row_no=2, 与用 Excel/文本编辑器看到的物理行号一致
- JSON: records 数组中的序号, 第一条记录 row_no=1
"""
from __future__ import annotations

import csv
import io
import json
from typing import Any


class FileParseError(Exception):
    pass


def _decode(content: bytes) -> str:
    # utf-8-sig 可兼容带 BOM 的 CSV
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise FileParseError(f"文件不是 UTF-8 编码: {exc}") from exc


def parse_csv(content: bytes) -> tuple[list[str], list[dict[str, Any]]]:
    text = _decode(content)
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise FileParseError("CSV 文件缺少表头")
    columns = [c.strip() for c in reader.fieldnames]
    rows: list[dict[str, Any]] = []
    for physical_line, raw in enumerate(reader, start=2):
        # DictReader 对短行会补 None, 统一转成空串
        clean = {(k.strip() if k else k): ("" if v is None else v) for k, v in raw.items()}
        rows.append({"row_no": physical_line, "data": clean})
    return columns, rows


def parse_json(content: bytes) -> tuple[list[str], list[dict[str, Any]]]:
    text = _decode(content)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FileParseError(f"JSON 解析失败: {exc}") from exc

    if isinstance(payload, dict) and isinstance(payload.get("records"), list):
        records = payload["records"]
    elif isinstance(payload, list):
        records = payload
    else:
        raise FileParseError("JSON 顶层需为数组, 或包含 records 数组的对象")

    columns: list[str] = []
    rows: list[dict[str, Any]] = []
    for idx, item in enumerate(records, start=1):
        if not isinstance(item, dict):
            raise FileParseError(f"第 {idx} 条记录不是对象")
        for key in item:
            if key not in columns:
                columns.append(key)
        rows.append({"row_no": idx, "data": item})
    return columns, rows


def parse_file(content: bytes, file_format: str) -> tuple[list[str], list[dict[str, Any]]]:
    if file_format == "csv":
        return parse_csv(content)
    if file_format == "json":
        return parse_json(content)
    raise FileParseError(f"不支持的文件格式: {file_format}")


def sniff_format(file_name: str) -> str:
    suffix = file_name.lower().rsplit(".", 1)[-1]
    if suffix == "csv":
        return "csv"
    if suffix == "json":
        return "json"
    raise FileParseError(f"无法从文件名识别格式(仅支持 .csv/.json): {file_name}")
