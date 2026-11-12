"""后台任务: 清洗全量重算与对账。

幂等保证:
1. 导入阶段按文件内容 SHA-256 去重, 同文件重复上传复用原批次
2. 清洗 run 全量重算: 先删旧 run 的合并记录再写入, 结果只取决于
   (规则版本, 批次内容), 与运行次数无关
3. 对账 job 同理, 每次重算覆盖自己的条目
"""
from __future__ import annotations

from .models import _utcnow

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import models
from .reconcile import reconcile
from .transform import clean_source


def _set_progress(db: Session, obj, progress: int, message: str | None = None) -> None:
    obj.progress = progress
    if message is not None:
        obj.message = message
    db.commit()


def run_cleaning(db: Session, run_id: int) -> None:
    run = db.get(models.CleaningRun, run_id)
    if run is None:
        return
    run.status = "running"
    run.progress = 5
    run.message = "开始清洗"
    db.commit()

    try:
        rule = db.get(models.RuleVersion, run.rule_version_id)
        config = rule.config_json
        sources = config["sources"]

        # 全量重算: 清掉本 run 旧产物(正常情况下新 run 没有旧数据, 重跑同 run 时生效)
        db.execute(delete(models.MergedRecord).where(models.MergedRecord.run_id == run.id))
        db.commit()

        all_invalid: list[dict] = []
        all_dropped: list[dict] = []
        merged_stats: dict[str, int] = {
            "total_rows": 0,
            "valid_rows": 0,
            "invalid_rows": 0,
            "kept_rows": 0,
            "dropped_duplicates": 0,
        }
        per_source: dict[str, dict] = {}

        total_sources = max(len(sources), 1)
        for index, source_rule in enumerate(sources):
            label = source_rule["source_label"]
            batch = db.get(models.ImportBatch, source_rule["batch_id"])
            if batch is None:
                raise ValueError(f"来源 {label} 引用的导入批次 {source_rule['batch_id']} 不存在")

            _set_progress(db, run, 10 + int(70 * index / total_sources), f"清洗来源: {label}")
            clean = clean_source(
                source_label=label,
                source_file=batch.file_name,
                batch_id=batch.id,
                raw_rows=batch.raw_rows_json,
                rule=source_rule,
            )

            for record in clean.records:
                db.add(models.MergedRecord(
                    run_id=run.id,
                    source_label=record["source_label"],
                    source_file=record["source_file"],
                    source_row=record["source_row"],
                    batch_id=record["batch_id"],
                    dedupe_key=record.get("dedupe_key"),
                    data_json=record["data"],
                ))
            all_invalid.extend(clean.invalid_rows)
            all_dropped.extend(clean.dropped_duplicates)
            for key, value in clean.stats.items():
                merged_stats[key] = merged_stats.get(key, 0) + value
            per_source[label] = clean.stats

        db.commit()
        merged_stats["per_source"] = per_source  # type: ignore[assignment]
        merged_stats["invalid_rows_detail"] = all_invalid  # type: ignore[assignment]
        merged_stats["dropped_duplicates_detail"] = all_dropped  # type: ignore[assignment]

        run.stats_json = merged_stats
        run.status = "completed"
        run.progress = 100
        run.message = "清洗完成"
        run.finished_at = _utcnow()
        db.commit()
    except Exception as exc:  # noqa: BLE001 - 后台任务需要兜底记录失败原因
        db.rollback()
        run = db.get(models.CleaningRun, run_id)
        run.status = "failed"
        run.message = f"{type(exc).__name__}: {exc}"
        run.finished_at = _utcnow()
        db.commit()


def run_reconciliation(db: Session, job_id: int) -> None:
    job = db.get(models.ReconJob, job_id)
    if job is None:
        return
    job.status = "running"
    job.progress = 10
    job.message = "加载合并记录"
    db.commit()

    try:
        records = db.scalars(
            select(models.MergedRecord).where(models.MergedRecord.run_id == job.run_id)
        ).all()
        left_records = [
            {"data": r.data_json, "source_file": r.source_file, "source_row": r.source_row,
             "source_label": r.source_label, "batch_id": r.batch_id}
            for r in records if r.source_label == job.left_label
        ]
        right_records = [
            {"data": r.data_json, "source_file": r.source_file, "source_row": r.source_row,
             "source_label": r.source_label, "batch_id": r.batch_id}
            for r in records if r.source_label == job.right_label
        ]

        job.progress = 40
        job.message = "逐笔对账"
        db.commit()

        entries, stats = reconcile(
            left_records,
            right_records,
            job.key_field,
            job.compare_fields_json,
            job.amount_tolerance,
        )

        db.execute(delete(models.ReconEntry).where(models.ReconEntry.job_id == job.id))
        for item in entries:
            left = item["left"]
            right = item["right"]
            db.add(models.ReconEntry(
                job_id=job.id,
                match_type=item["match_type"],
                key_value=item["key_value"],
                left_row=left["source_row"] if left else None,
                right_row=right["source_row"] if right else None,
                left_file=left["source_file"] if left else None,
                right_file=right["source_file"] if right else None,
                left_json=left["data"] if left else None,
                right_json=right["data"] if right else None,
                diffs_json=item["diffs"],
            ))
        db.commit()

        job.stats_json = stats
        job.status = "completed"
        job.progress = 100
        job.message = "对账完成"
        job.finished_at = _utcnow()
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        job = db.get(models.ReconJob, job_id)
        job.status = "failed"
        job.message = f"{type(exc).__name__}: {exc}"
        job.finished_at = _utcnow()
        db.commit()
