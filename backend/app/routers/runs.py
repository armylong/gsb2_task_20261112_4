"""清洗任务: 创建 run、轮询进度、查看结果与版本间差异。"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import SessionLocal, get_db
from ..jobs import run_cleaning
from ..services import diff_runs

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _cleaning_task(run_id: int) -> None:
    # 后台任务使用独立 Session, 与请求 Session 隔离
    with SessionLocal() as db:
        run_cleaning(db, run_id)


@router.post("", response_model=schemas.RunOut, status_code=202)
def start_run(
    payload: schemas.CleanRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> models.CleaningRun:
    rule = db.get(models.RuleVersion, payload.rule_version_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="规则版本不存在")
    run = models.CleaningRun(
        rule_version_id=rule.id,
        rule_version=rule.version,
        status="pending",
        progress=0,
        message="任务已排队",
        stats_json={},
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    background.add_task(_cleaning_task, run.id)
    return run


@router.get("", response_model=list[schemas.RunOut])
def list_runs(db: Session = Depends(get_db)) -> list[models.CleaningRun]:
    return list(db.scalars(
        select(models.CleaningRun).order_by(models.CleaningRun.created_at.desc())
    ))


@router.get("/{run_id}", response_model=schemas.RunDetailOut)
def get_run(run_id: int, db: Session = Depends(get_db)) -> schemas.RunDetailOut:
    run = db.get(models.CleaningRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="清洗任务不存在")

    records = db.scalars(
        select(models.MergedRecord)
        .where(models.MergedRecord.run_id == run_id)
        .order_by(models.MergedRecord.source_label, models.MergedRecord.source_row)
    ).all()

    stats = run.stats_json or {}
    detail = schemas.RunDetailOut(
        id=run.id,
        rule_version_id=run.rule_version_id,
        rule_version=run.rule_version,
        status=run.status,
        progress=run.progress,
        message=run.message,
        stats=stats,
        created_at=run.created_at,
        finished_at=run.finished_at,
        records=[schemas.MergedRecordOut.model_validate(r) for r in records],
        invalid_rows=stats.get("invalid_rows_detail", []),
        dropped_duplicates=stats.get("dropped_duplicates_detail", []),
    )
    return detail


@router.get("/diff/{base_run_id}/{target_run_id}", response_model=schemas.RunDiffOut)
def compare_runs(base_run_id: int, target_run_id: int, db: Session = Depends(get_db)) -> dict:
    if db.get(models.CleaningRun, base_run_id) is None:
        raise HTTPException(status_code=404, detail=f"基准 run {base_run_id} 不存在")
    if db.get(models.CleaningRun, target_run_id) is None:
        raise HTTPException(status_code=404, detail=f"对比 run {target_run_id} 不存在")
    return diff_runs(db, base_run_id, target_run_id)
