"""清洗规则版本管理。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..transform import clean_source

router = APIRouter(prefix="/api/rules", tags=["rules"])


@router.post("", response_model=schemas.RuleVersionOut, status_code=201)
def create_rule(payload: schemas.RuleCreate, db: Session = Depends(get_db)) -> models.RuleVersion:
    latest = db.scalar(
        select(models.RuleVersion)
        .where(models.RuleVersion.name == payload.name)
        .order_by(models.RuleVersion.version.desc())
    )
    next_version = (latest.version + 1) if latest else 1
    rule = models.RuleVersion(
        name=payload.name,
        version=next_version,
        note=payload.note,
        config_json=payload.config.model_dump(),
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.get("", response_model=list[schemas.RuleVersionOut])
def list_rules(db: Session = Depends(get_db)) -> list[models.RuleVersion]:
    return list(db.scalars(
        select(models.RuleVersion).order_by(
            models.RuleVersion.name, models.RuleVersion.version.desc()
        )
    ))


@router.get("/{rule_id}", response_model=schemas.RuleVersionOut)
def get_rule(rule_id: int, db: Session = Depends(get_db)) -> models.RuleVersion:
    rule = db.get(models.RuleVersion, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="规则版本不存在")
    return rule


@router.post("/preview", response_model=schemas.RulePreviewOut)
def preview_rule(payload: schemas.RuleCreate, db: Session = Depends(get_db)) -> dict:
    """按草稿规则试清洗, 不写库, 供界面确认清洗结果。"""
    per_source: list[dict] = []
    total_kept = total_invalid = total_dropped = 0
    for source_rule in payload.config.sources:
        batch = db.get(models.ImportBatch, source_rule.batch_id)
        if batch is None:
            raise HTTPException(
                status_code=404,
                detail=f"来源 {source_rule.source_label} 的导入批次不存在",
            )
        clean = clean_source(
            source_label=source_rule.source_label,
            source_file=batch.file_name,
            batch_id=batch.id,
            raw_rows=batch.raw_rows_json,
            rule=source_rule.model_dump(),
        )
        per_source.append({
            "source_label": source_rule.source_label,
            "source_file": batch.file_name,
            "stats": clean.stats,
            "records": [
                {**r, "data": r["data"]} for r in clean.records
            ],
            "invalid_rows": clean.invalid_rows,
            "dropped_duplicates": clean.dropped_duplicates,
        })
        total_kept += clean.stats["kept_rows"]
        total_invalid += clean.stats["invalid_rows"]
        total_dropped += clean.stats["dropped_duplicates"]
    return {
        "per_source": per_source,
        "total_kept": total_kept,
        "total_invalid": total_invalid,
        "total_dropped": total_dropped,
    }
