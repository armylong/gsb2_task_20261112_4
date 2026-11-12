"""Pydantic 请求/响应模型。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------- 导入 ----------

class RawRow(BaseModel):
    row_no: int
    data: dict[str, Any]


class ImportBatchOut(BaseModel):
    id: int
    source_label: str
    file_name: str
    file_format: str
    content_hash: str
    row_count: int
    columns: list[str] = Field(validation_alias="columns_json")
    created_at: datetime

    model_config = {"from_attributes": True}


class ImportPreviewOut(BaseModel):
    batch: ImportBatchOut | None = None
    reused: bool = False
    preview_rows: list[RawRow]
    total_rows: int


# ---------- 规则 ----------

class SourceRule(BaseModel):
    source_label: str
    batch_id: int
    field_mappings: dict[str, str] = Field(default_factory=dict)
    null_tokens: list[str] = Field(default_factory=lambda: ["-", "--", "null", "NULL", "", "None"])
    value_maps: dict[str, dict[str, str]] = Field(default_factory=dict)
    derived_fields: dict[str, str] = Field(default_factory=dict)
    dedupe_key: str | None = None
    dedupe_strategy: Literal["keep_first", "priority"] = "keep_first"
    priority_field: str | None = None
    priority_desc: bool = True
    required_fields: list[str] = Field(default_factory=list)


class RuleConfig(BaseModel):
    sources: list[SourceRule]


class RuleVersionOut(BaseModel):
    id: int
    name: str
    version: int
    note: str | None = None
    config: dict = Field(validation_alias="config_json")
    created_at: datetime

    model_config = {"from_attributes": True}


class RuleCreate(BaseModel):
    name: str
    note: str | None = None
    config: RuleConfig


class RulePreviewOut(BaseModel):
    per_source: list[dict[str, Any]]
    total_kept: int
    total_invalid: int
    total_dropped: int


# ---------- 清洗 ----------

class CleanRequest(BaseModel):
    rule_version_id: int


class RunOut(BaseModel):
    id: int
    rule_version_id: int
    rule_version: int
    status: str
    progress: int
    message: str | None = None
    stats: dict = Field(validation_alias="stats_json")
    created_at: datetime
    finished_at: datetime | None = None

    model_config = {"from_attributes": True, "populate_by_name": True}


class MergedRecordOut(BaseModel):
    id: int
    source_label: str
    source_file: str
    source_row: int
    batch_id: int
    dedupe_key: str | None = None
    data: dict = Field(validation_alias="data_json")

    model_config = {"from_attributes": True}


class InvalidRowOut(BaseModel):
    source_label: str
    source_file: str
    source_row: int
    dedupe_key: str | None = None
    errors: list[str]
    raw: dict[str, Any]


class RunDetailOut(RunOut):
    records: list[MergedRecordOut] = Field(default_factory=list)
    invalid_rows: list[InvalidRowOut] = Field(default_factory=list)
    dropped_duplicates: list[dict[str, Any]] = Field(default_factory=list)


# ---------- 对账 ----------

class ReconRequest(BaseModel):
    run_id: int
    left_label: str
    right_label: str
    key_field: str = "biz_no"
    compare_fields: list[str] = Field(default_factory=list)
    amount_tolerance: float = 0.0


class ReconJobOut(BaseModel):
    id: int
    run_id: int
    left_label: str
    right_label: str
    key_field: str
    compare_fields: list = Field(validation_alias="compare_fields_json")
    amount_tolerance: float
    status: str
    progress: int
    stats: dict = Field(validation_alias="stats_json")
    message: str | None = None
    created_at: datetime
    finished_at: datetime | None = None

    model_config = {"from_attributes": True}


class ReconEntryOut(BaseModel):
    id: int
    match_type: str
    key_value: str | None
    left_row: int | None
    right_row: int | None
    left_file: str | None
    right_file: str | None
    left: dict | None = Field(validation_alias="left_json")
    right: dict | None = Field(validation_alias="right_json")
    diffs: list = Field(validation_alias="diffs_json")

    model_config = {"from_attributes": True}


# ---------- 版本 diff / 导出 ----------

class RunDiffOut(BaseModel):
    base_run_id: int
    target_run_id: int
    summary: dict[str, int]
    added: list[dict[str, Any]]
    removed: list[dict[str, Any]]
    changed: list[dict[str, Any]]


class ExportOut(BaseModel):
    download_url: str
    file_name: str
    row_count: int
