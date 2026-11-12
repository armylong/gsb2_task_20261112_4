"""清洗结果与对账差异导出。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import models, schemas
from ..config import EXPORT_DIR
from ..database import get_db
from ..services import export_merged_csv, export_recon_csv

router = APIRouter(prefix="/api/exports", tags=["exports"])


@router.post("/run/{run_id}", response_model=schemas.ExportOut)
def export_run(run_id: int, db: Session = Depends(get_db)) -> schemas.ExportOut:
    run = db.get(models.CleaningRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="清洗任务不存在")
    if run.status != "completed":
        raise HTTPException(status_code=400, detail="清洗任务未完成, 无法导出")
    file_name, row_count = export_merged_csv(db, run_id)
    return schemas.ExportOut(
        download_url=f"/api/exports/download/{file_name}",
        file_name=file_name,
        row_count=row_count,
    )


@router.post("/recon/{job_id}", response_model=schemas.ExportOut)
def export_recon(job_id: int, db: Session = Depends(get_db)) -> schemas.ExportOut:
    job = db.get(models.ReconJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="对账任务不存在")
    if job.status != "completed":
        raise HTTPException(status_code=400, detail="对账任务未完成, 无法导出")
    file_name, row_count = export_recon_csv(db, job_id)
    return schemas.ExportOut(
        download_url=f"/api/exports/download/{file_name}",
        file_name=file_name,
        row_count=row_count,
    )


@router.get("/download/{file_name}")
def download(file_name: str) -> FileResponse:
    # 只允许文件名, 阻断路径穿越
    if "/" in file_name or ".." in file_name:
        raise HTTPException(status_code=400, detail="非法文件名")
    path = EXPORT_DIR / file_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="导出文件不存在或已被清理")
    return FileResponse(path, filename=file_name, media_type="text/csv")
