"""字段映射、类型转换、派生字段、必填校验与来源内去重。

派生字段表达式(不使用 eval, 手写递归下降解析):
- 模板: 任意文本 + 字段引用, 如 ``${姓氏}${名字}`` 或 ``${last_name} ${first_name}``
- 函数: ``concat(...)`` / ``coalesce(...)`` / ``upper(...)`` / ``lower(...)`` / ``trim(...)``
  参数支持字符串字面量 "xxx"、字段引用 ${field} 与嵌套函数
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# 目标字段 -> 数据类型
TARGET_TYPES: dict[str, str] = {
    "biz_no": "string",
    "full_name": "string",
    "amount": "decimal",
    "order_date": "date",
    "channel": "string",
    "status": "string",
}

DEFAULT_NULL_TOKENS = ["-", "--", "null", "NULL", "", "None", "N/A", "n/a"]

_DATE_FORMATS = [
    "%Y/%m/%d",
    "%Y.%m.%d",
    "%Y%m%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
]


class TransformError(Exception):
    """单行数据转换失败, 收集后作为无效行返回, 不中断整批处理。"""


# --------------------------------------------------------------------------- #
# 派生字段表达式
# --------------------------------------------------------------------------- #

# 注意: 统一用 re.match(text, pos) 锚定位置, 模式里不要写 ^,
# 否则显式 ^ 只匹配字符串索引 0, pos > 0 时会失配
_FIELD_RE = re.compile(r"\$\{([^{}]+)\}")
_STRING_RE = re.compile(r'"([^"]*)"')
_IDENT_RE = re.compile(r"[A-Za-z_一-鿿][A-Za-z0-9_一-鿿]*")


class _Expr:
    def evaluate(self, row: dict[str, Any]) -> Any:  # pragma: no cover - 抽象方法
        raise NotImplementedError


class _Literal(_Expr):
    def __init__(self, text: str):
        self.text = text

    def evaluate(self, row: dict[str, Any]) -> Any:
        return self.text


class _FieldRef(_Expr):
    def __init__(self, name: str):
        self.name = name

    def evaluate(self, row: dict[str, Any]) -> Any:
        return row.get(self.name)


class _Call(_Expr):
    def __init__(self, name: str, args: list[_Expr]):
        self.name = name
        self.args = args

    def evaluate(self, row: dict[str, Any]) -> Any:
        values = [arg.evaluate(row) for arg in self.args]
        if self.name == "concat":
            return "".join(str(v) for v in values if v is not None)
        if self.name == "coalesce":
            for v in values:
                if v is not None:
                    return v
            return None
        if self.name in ("upper", "lower", "trim"):
            target = values[0] if values else None
            if target is None:
                return None
            text = str(target)
            if self.name == "upper":
                return text.upper()
            if self.name == "lower":
                return text.lower()
            return text.strip()
        raise TransformError(f"不支持的函数: {self.name}")


class _Template(_Expr):
    def __init__(self, parts: list[_Expr]):
        self.parts = parts

    def evaluate(self, row: dict[str, Any]) -> Any:
        chunks: list[str] = []
        for part in self.parts:
            value = part.evaluate(row)
            if value is not None:
                chunks.append(str(value))
        rendered = "".join(chunks)
        return rendered or None


def _parse_args(text: str, pos: int) -> tuple[list[_Expr], int]:
    args: list[_Expr] = []
    if text[pos] != "(":
        raise TransformError("函数调用缺少左括号")
    pos += 1
    while pos < len(text):
        while pos < len(text) and text[pos] == " ":
            pos += 1
        if text[pos] == ")":
            return args, pos + 1
        arg, pos = _parse_expr(text, pos)
        args.append(arg)
        while pos < len(text) and text[pos] == " ":
            pos += 1
        if pos < len(text) and text[pos] == ",":
            pos += 1
            continue
    raise TransformError("函数调用缺少右括号")


def _parse_expr(text: str, pos: int = 0) -> tuple[_Expr, int]:
    while pos < len(text) and text[pos] == " ":
        pos += 1
    match = _IDENT_RE.match(text, pos)
    if match and text.find("(", match.end(), match.end() + 1) != -1:
        name = match.group(0)
        args, new_pos = _parse_args(text, match.end())
        return _Call(name, args), new_pos

    match = _STRING_RE.match(text, pos)
    if match:
        return _Literal(match.group(1)), match.end()

    match = _FIELD_RE.match(text, pos)
    if match:
        return _FieldRef(match.group(1)), match.end()

    raise TransformError(f"无法解析表达式, 位置 {pos}: {text[pos:pos + 20]}")


def parse_expression(expression: str) -> _Expr:
    text = expression.strip()
    if not text:
        raise TransformError("派生字段表达式为空")
    # 整体是一个函数调用
    ident = _IDENT_RE.match(text, 0)
    if ident and text.endswith(")") and text.find("(", ident.end()) == ident.end():
        expr, pos = _parse_expr(text, 0)
        if pos != len(text):
            raise TransformError(f"表达式存在多余字符: {text[pos:]}")
        return expr
    # 否则按模板解析: 文本片段与 ${字段} 交替
    parts: list[_Expr] = []
    pos = 0
    while pos < len(text):
        match = _FIELD_RE.match(text, pos)
        if match:
            parts.append(_FieldRef(match.group(1)))
            pos = match.end()
            continue
        next_ref = text.find("${", pos)
        end = len(text) if next_ref == -1 else next_ref
        if end > pos:
            parts.append(_Literal(text[pos:end]))
            pos = end
        else:
            # 没有可消费的字面量又找不到合法字段引用(如单个 $), 直接报错避免死循环
            raise TransformError(f"模板解析失败, 位置 {pos}: {text[pos:pos + 20]}")
    if not parts:
        raise TransformError(f"非法表达式: {expression}")
    return _Template(parts)


# --------------------------------------------------------------------------- #
# 类型转换
# --------------------------------------------------------------------------- #

def convert_decimal(value: Any) -> float:
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    text = str(value).strip().replace(",", "")
    if not text:
        raise TransformError("金额为空")
    try:
        return round(float(text), 2)
    except ValueError as exc:
        raise TransformError(f"金额格式非法: {value!r}") from exc


def convert_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    text = str(value).strip()
    if not text:
        raise TransformError("日期为空")
    # ISO 8601 (含 2026-10-01 与 2026-10-01T09:30:00), 非法日期如 2026-02-30 会抛错
    iso_candidate = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso_candidate).date().isoformat()
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    raise TransformError(f"日期格式无法识别: {value!r}")


def convert_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def convert_value(value: Any, target_type: str) -> Any:
    if target_type == "string":
        return convert_string(value)
    if target_type == "decimal":
        return convert_decimal(value)
    if target_type == "date":
        return convert_date(value)
    raise TransformError(f"不支持的目标类型: {target_type}")


# --------------------------------------------------------------------------- #
# 行级清洗
# --------------------------------------------------------------------------- #

@dataclass
class SourceCleanResult:
    source_label: str
    source_file: str
    batch_id: int
    records: list[dict[str, Any]] = field(default_factory=list)
    invalid_rows: list[dict[str, Any]] = field(default_factory=list)
    dropped_duplicates: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


def normalize_nulls(row: dict[str, Any], null_tokens: list[str]) -> dict[str, Any]:
    tokens = set(null_tokens)
    normalized: dict[str, Any] = {}
    for key, value in row.items():
        if value is None:
            normalized[key] = None
        elif isinstance(value, str) and value.strip() in tokens:
            normalized[key] = None
        else:
            normalized[key] = value
    return normalized


def clean_source(
    source_label: str,
    source_file: str,
    batch_id: int,
    raw_rows: list[dict[str, Any]],
    rule: dict[str, Any],
) -> SourceCleanResult:
    null_tokens = rule.get("null_tokens") or DEFAULT_NULL_TOKENS
    field_mappings: dict[str, str] = rule.get("field_mappings", {})
    value_maps: dict[str, dict[str, str]] = rule.get("value_maps", {})
    derived: dict[str, str] = rule.get("derived_fields", {})
    required: list[str] = rule.get("required_fields", [])
    dedupe_key = rule.get("dedupe_key")
    strategy = rule.get("dedupe_strategy", "keep_first")
    priority_field = rule.get("priority_field")
    priority_desc = rule.get("priority_desc", True)

    compiled_derived = {target: parse_expression(expr) for target, expr in derived.items()}

    result = SourceCleanResult(
        source_label=source_label, source_file=source_file, batch_id=batch_id
    )
    valid: list[dict[str, Any]] = []

    for raw_row in raw_rows:
        row_no = raw_row["row_no"]
        source_data = normalize_nulls(raw_row["data"], null_tokens)
        errors: list[str] = []
        target_data: dict[str, Any] = {}

        # 1. 字段映射 + 值映射 + 类型转换
        for target_field, source_field in field_mappings.items():
            value = source_data.get(source_field)
            if value is not None and target_field in value_maps:
                mapping = value_maps[target_field]
                if str(value) in mapping:
                    value = mapping[str(value)]
                else:
                    errors.append(f"字段 {target_field} 的值映射缺少键: {value!r}")
            if value is not None:
                target_type = TARGET_TYPES.get(target_field, "string")
                try:
                    target_data[target_field] = convert_value(value, target_type)
                except TransformError as exc:
                    errors.append(str(exc))
            else:
                target_data[target_field] = None

        # 2. 派生字段
        for target_field, expr in compiled_derived.items():
            try:
                value = expr.evaluate(source_data)
                target_type = TARGET_TYPES.get(target_field, "string")
                target_data[target_field] = (
                    convert_value(value, target_type) if value is not None else None
                )
            except TransformError as exc:
                errors.append(f"派生字段 {target_field} 计算失败: {exc}")

        # 3. 必填校验
        for required_field in required:
            if target_data.get(required_field) in (None, ""):
                errors.append(f"必填字段 {required_field} 为空")

        trace = {
            "source_label": source_label,
            "source_file": source_file,
            "source_row": row_no,
            "batch_id": batch_id,
            "dedupe_key": target_data.get(dedupe_key) if dedupe_key else None,
        }
        if errors:
            result.invalid_rows.append({**trace, "errors": errors, "raw": raw_row["data"]})
            continue
        # _raw 仅用于来源内优先级比较, 落库前会剔除
        valid.append({**trace, "data": target_data, "_raw": source_data})

    # 4. 来源内去重(跨来源的同键记录保留, 交给对账)
    kept, dropped = _dedupe(valid, strategy, dedupe_key, priority_field, priority_desc)
    for record in kept:
        record.pop("_raw", None)
    result.records = kept
    result.dropped_duplicates = dropped
    result.stats = {
        "total_rows": len(raw_rows),
        "valid_rows": len(valid),
        "invalid_rows": len(result.invalid_rows),
        "kept_rows": len(kept),
        "dropped_duplicates": len(dropped),
    }
    return result


def _priority_value(record: dict[str, Any], priority_field: str | None) -> Any:
    if not priority_field:
        return None
    # 先看转换后的目标字段, 再看来源原始字段
    if priority_field in record["data"]:
        return record["data"][priority_field]
    return record.get("_raw", {}).get(priority_field)


def _dedupe(
    records: list[dict[str, Any]],
    strategy: str,
    dedupe_key: str | None,
    priority_field: str | None,
    priority_desc: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not dedupe_key:
        return records, []

    groups: dict[Any, list[dict[str, Any]]] = {}
    no_key: list[dict[str, Any]] = []
    for record in records:
        key = record["data"].get(dedupe_key)
        if key in (None, ""):
            no_key.append(record)
            continue
        groups.setdefault(str(key), []).append(record)

    kept: list[dict[str, Any]] = list(no_key)
    dropped: list[dict[str, Any]] = []
    for key, group in groups.items():
        if len(group) == 1:
            kept.append(group[0])
            continue
        if strategy == "priority" and priority_field:
            # None 视为最低优先级; 同优先级按原始行号, 保证结果稳定
            none_rank = float("inf") if priority_desc else float("-inf")

            def sort_key(r: dict[str, Any]) -> tuple[Any, int]:
                value = _priority_value(r, priority_field)
                rank = none_rank if value is None else value
                return (-rank if priority_desc else rank, r["source_row"])

            winner = min(group, key=sort_key)
        else:
            # keep_first: 原始行号最小者胜出
            winner = min(group, key=lambda r: r["source_row"])
        kept.append(winner)
        for loser in group:
            if loser is winner:
                continue
            dropped.append({
                "dedupe_key": key,
                "dropped_source": loser["source_label"],
                "dropped_row": loser["source_row"],
                "kept_row": winner["source_row"],
                "reason": f"{strategy}: 保留第 {winner['source_row']} 行",
            })
    kept.sort(key=lambda r: (r["source_label"], r["source_row"]))
    return kept, dropped


# --------------------------------------------------------------------------- #
# 字段映射建议
# --------------------------------------------------------------------------- #

_ALIASES: dict[str, list[str]] = {
    "biz_no": ["bizno", "biz_no", "id", "业务编号", "单号", "编号"],
    "full_name": ["fullname", "name", "姓名", "全名", "客户名称"],
    "amount": ["amount", "money", "price", "total", "金额", "订单金额", "总金额"],
    "order_date": ["orderdate", "date", "createtime", "下单日期", "日期", "订单日期"],
    "channel": ["channel", "source", "渠道", "来源", "销售渠道"],
    "status": ["status", "state", "状态", "单据状态"],
}


def suggest_mappings(columns: list[str]) -> dict[str, str]:
    suggestions: dict[str, str] = {}
    for target_field, aliases in _ALIASES.items():
        for column in columns:
            normalized = re.sub(r"[^a-z0-9一-鿿]", "", column.lower())
            if normalized in [re.sub(r"[^a-z0-9一-鿿]", "", a.lower()) for a in aliases]:
                suggestions[target_field] = column
                break
    return suggestions
