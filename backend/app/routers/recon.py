"""对账任务与差异条目。"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import SessionLocal, get_db
from ..jobs import run_reconciliation

router = APIRouter(prefix="/api/recon", tags=["recon"])


def _recon_task(job_id: int) -> None:
    with SessionLocal() as db:
        run_reconciliation(db, job_id)


@router.post("", response_model=schemas.ReconJobOut, status_code=202)
def start_recon(
    payload: schemas.ReconRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> models.ReconJob:
    run = db.get(models.CleaningRun, payload.run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="清洗任务不存在")
    if run.status != "completed":
        raise HTTPException(status_code=400, detail="清洗任务尚未完成, 无法对账")
    if payload.left_label == payload.right_label:
        raise HTTPException(status_code=400, detail="对账的两个来源不能相同")

    labels = {r.source_label for r in run.records}
    for label in (payload.left_label, payload.right_label):
        if label not in labels:
            raise HTTPException(status_code=400, detail=f"清洗结果中不存在来源: {label}")

    job = models.ReconJob(
        run_id=run.id,
        left_label=payload.left_label,
        right_label=payload.right_label,
        key_field=payload.key_field,
        compare_fields_json=payload.compare_fields,
        amount_tolerance=payload.amount_tolerance,
        status="pending",
        progress=0,
        message="任务已排队",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    background.add_task(_recon_task, job.id)
    return job


@router.get("", response_model=list[schemas.ReconJobOut])
def list_jobs(db: Session = Depends(get_db)) -> list[models.ReconJob]:
    return list(db.scalars(
        select(models.ReconJob).order_by(models.ReconJob.created_at.desc())
    ))


@router.get("/{job_id}", response_model=schemas.ReconJobOut)
def get_job(job_id: int, db: Session = Depends(get_db)) -> models.ReconJob:
    job = db.get(models.ReconJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="对账任务不存在")
    return job


@router.get("/{job_id}/entries", response_model=list[schemas.ReconEntryOut])
def get_entries(
    job_id: int,
    match_type: str | None = None,
    db: Session = Depends(get_db),
) -> list[models.ReconEntry]:
    if db.get(models.ReconJob, job_id) is None:
        raise HTTPException(status_code=404, detail="对账任务不存在")
    stmt = select(models.ReconEntry).where(models.ReconEntry.job_id == job_id)
    if match_type:
        stmt = stmt.where(models.ReconEntry.match_type == match_type)
    stmt = stmt.order_by(models.ReconEntry.match_type, models.ReconEntry.key_value)
    return list(db.scalars(stmt))
