"""CSV 导出与两次清洗 run 的字段级差异对比。"""
from __future__ import annotations

import csv
import io
from .models import _utcnow

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import EXPORT_DIR, TARGET_SCHEMA
from . import models

_TRACE_FIELDS = ["source_label", "source_file", "source_row", "dedupe_key"]


def export_merged_csv(db: Session, run_id: int) -> tuple[str, int]:
    records = db.scalars(
        select(models.MergedRecord)
        .where(models.MergedRecord.run_id == run_id)
        .order_by(models.MergedRecord.source_label, models.MergedRecord.source_row)
    ).all()

    header = _TRACE_FIELDS + list(TARGET_SCHEMA.keys())
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    for record in records:
        row = [
            record.source_label,
            record.source_file,
            record.source_row,
            record.dedupe_key or "",
        ]
        row.extend(record.data_json.get(field, "") for field in TARGET_SCHEMA)
        writer.writerow(row)

    stamp = _utcnow().strftime("%Y%m%d_%H%M%S")
    file_name = f"cleaned_run{run_id}_{stamp}.csv"
    (EXPORT_DIR / file_name).write_text(buffer.getvalue(), encoding="utf-8-sig")
    return file_name, len(records)


def export_recon_csv(db: Session, job_id: int) -> tuple[str, int]:
    entries = db.scalars(
        select(models.ReconEntry)
        .where(models.ReconEntry.job_id == job_id)
        .order_by(models.ReconEntry.match_type, models.ReconEntry.key_value)
    ).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "差异类型", "业务键", "左来源文件", "左行号", "右来源文件", "右行号",
        "差异字段", "左值", "右值",
    ])
    type_labels = {
        "field_mismatch": "字段不一致",
        "only_left": "仅左侧存在",
        "only_right": "仅右侧存在",
    }
    for entry in entries:
        if entry.match_type == "field_mismatch":
            for diff in entry.diffs_json:
                writer.writerow([
                    type_labels[entry.match_type], entry.key_value,
                    entry.left_file, entry.left_row,
                    entry.right_file, entry.right_row,
                    diff.get("field_label", diff.get("field")),
                    diff.get("left"), diff.get("right"),
                ])
        else:
            writer.writerow([
                type_labels[entry.match_type], entry.key_value,
                entry.left_file or "", entry.left_row or "",
                entry.right_file or "", entry.right_row or "",
                "", "", "",
            ])

    stamp = _utcnow().strftime("%Y%m%d_%H%M%S")
    file_name = f"recon_job{job_id}_{stamp}.csv"
    (EXPORT_DIR / file_name).write_text(buffer.getvalue(), encoding="utf-8-sig")
    return file_name, len(entries)


def diff_runs(
    db: Session, base_run_id: int, target_run_id: int
) -> dict:
    """以 (source_label, dedupe_key 或来源行号) 为记录身份对比两次 run。"""
    def index_records(run_id: int) -> dict[tuple, models.MergedRecord]:
        records = db.scalars(
            select(models.MergedRecord).where(models.MergedRecord.run_id == run_id)
        ).all()
        indexed: dict[tuple, models.MergedRecord] = {}
        for record in records:
            identity = (
                record.source_label,
                record.dedupe_key or f"row:{record.source_row}",
            )
            indexed[identity] = record
        return indexed

    base_map = index_records(base_run_id)
    target_map = index_records(target_run_id)

    added: list[dict] = []
    removed: list[dict] = []
    changed: list[dict] = []

    for identity, record in target_map.items():
        if identity not in base_map:
            added.append({
                "source_label": record.source_label,
                "dedupe_key": record.dedupe_key,
                "source_row": record.source_row,
                "data": record.data_json,
            })

    for identity, record in base_map.items():
        if identity not in target_map:
            removed.append({
                "source_label": record.source_label,
                "dedupe_key": record.dedupe_key,
                "source_row": record.source_row,
                "data": record.data_json,
            })

    for identity in sorted(set(base_map) & set(target_map)):
        old = base_map[identity].data_json
        new = target_map[identity].data_json
        field_diffs = []
        for field in TARGET_SCHEMA:
            if old.get(field) != new.get(field):
                field_diffs.append({
                    "field": field,
                    "field_label": TARGET_SCHEMA[field],
                    "before": old.get(field),
                    "after": new.get(field),
                })
        if field_diffs:
            changed.append({
                "source_label": identity[0],
                "dedupe_key": identity[1],
                "source_row_before": base_map[identity].source_row,
                "source_row_after": target_map[identity].source_row,
                "field_diffs": field_diffs,
            })

    return {
        "base_run_id": base_run_id,
        "target_run_id": target_run_id,
        "summary": {
            "base_count": len(base_map),
            "target_count": len(target_map),
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
        },
        "added": added,
        "removed": removed,
        "changed": changed,
    }
