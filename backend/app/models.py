"""ORM 模型。

设计要点:
- import_batches 保留原始文件与内容哈希, 同文件重复导入直接复用, 不产生新数据
- rule_versions 每次保存规则生成一条不可变快照, 清洗 run 绑定具体版本
- cleaning_runs 每次清洗全量重算, 合并记录挂在 run 下; 重跑不会让结果累加
- merged_records 保留来源文件与原始行号, 支持追溯
- recon_jobs / recon_entries 记录对账结果与逐笔差异
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)  # SQLite 以 naive UTC 存储


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_label: Mapped[str] = mapped_column(String(64), index=True)
    file_name: Mapped[str] = mapped_column(String(255))
    file_format: Mapped[str] = mapped_column(String(16))  # csv / json
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    columns_json: Mapped[list] = mapped_column(JSON, default=list)
    # 解析后的原始行, 每行 {"row_no": int, "data": {...}}
    raw_rows_json: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class RuleVersion(Base):
    __tablename__ = "rule_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    version: Mapped[int] = mapped_column(Integer, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    config_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class CleaningRun(Base):
    __tablename__ = "cleaning_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_version_id: Mapped[int] = mapped_column(ForeignKey("rule_versions.id"), index=True)
    rule_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    # pending / running / completed / failed
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    stats_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    records: Mapped[list["MergedRecord"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class MergedRecord(Base):
    __tablename__ = "merged_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("cleaning_runs.id"), index=True)
    source_label: Mapped[str] = mapped_column(String(64), index=True)
    source_file: Mapped[str] = mapped_column(String(255))
    source_row: Mapped[int] = mapped_column(Integer)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id"))
    dedupe_key: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    data_json: Mapped[dict] = mapped_column(JSON)

    run: Mapped[CleaningRun] = relationship(back_populates="records")


class ReconJob(Base):
    __tablename__ = "recon_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("cleaning_runs.id"), index=True)
    left_label: Mapped[str] = mapped_column(String(64))
    right_label: Mapped[str] = mapped_column(String(64))
    key_field: Mapped[str] = mapped_column(String(64))
    compare_fields_json: Mapped[list] = mapped_column(JSON, default=list)
    amount_tolerance: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    stats_json: Mapped[dict] = mapped_column(JSON, default=dict)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    entries: Mapped[list["ReconEntry"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class ReconEntry(Base):
    __tablename__ = "recon_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("recon_jobs.id"), index=True)
    match_type: Mapped[str] = mapped_column(String(16), index=True)
    # matched / field_mismatch / only_left / only_right
    key_value: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    left_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    right_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    left_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    right_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    left_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    right_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    diffs_json: Mapped[list] = mapped_column(JSON, default=list)

    job: Mapped[ReconJob] = relationship(back_populates="entries")
