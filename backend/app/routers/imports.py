"""文件导入与预览。"""
from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..parsers import FileParseError, parse_file, sniff_format
from ..transform import suggest_mappings

router = APIRouter(prefix="/api/imports", tags=["imports"])

PREVIEW_LIMIT = 8


@router.post("/upload", response_model=schemas.ImportPreviewOut)
async def upload_file(
    source_label: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> schemas.ImportPreviewOut:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空")
    try:
        file_format = sniff_format(file.filename or "")
        columns, rows = parse_file(content, file_format)
    except FileParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    content_hash = hashlib.sha256(content).hexdigest()

    # 幂等: 同内容文件直接复用原批次
    existing = db.scalar(
        select(models.ImportBatch).where(models.ImportBatch.content_hash == content_hash)
    )
    if existing is not None:
        preview = existing.raw_rows_json[:PREVIEW_LIMIT]
        return schemas.ImportPreviewOut(
            batch=schemas.ImportBatchOut.model_validate(existing),
            reused=True,
            preview_rows=preview,
            total_rows=existing.row_count,
        )

    batch = models.ImportBatch(
        source_label=source_label.strip(),
        file_name=file.filename or "unknown",
        file_format=file_format,
        content_hash=content_hash,
        row_count=len(rows),
        columns_json=columns,
        raw_rows_json=rows,
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return schemas.ImportPreviewOut(
        batch=schemas.ImportBatchOut.model_validate(batch),
        reused=False,
        preview_rows=rows[:PREVIEW_LIMIT],
        total_rows=len(rows),
    )


@router.get("", response_model=list[schemas.ImportBatchOut])
def list_batches(db: Session = Depends(get_db)) -> list[models.ImportBatch]:
    return list(db.scalars(
        select(models.ImportBatch).order_by(models.ImportBatch.created_at.desc())
    ))


@router.get("/{batch_id}", response_model=schemas.ImportPreviewOut)
def get_batch(batch_id: int, db: Session = Depends(get_db)) -> schemas.ImportPreviewOut:
    batch = db.get(models.ImportBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="导入批次不存在")
    return schemas.ImportPreviewOut(
        batch=schemas.ImportBatchOut.model_validate(batch),
        reused=False,
        preview_rows=batch.raw_rows_json[:PREVIEW_LIMIT],
        total_rows=batch.row_count,
    )


@router.get("/{batch_id}/rows")
def get_batch_rows(
    batch_id: int, limit: int = 100, offset: int = 0, db: Session = Depends(get_db)
) -> dict:
    batch = db.get(models.ImportBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="导入批次不存在")
    rows = batch.raw_rows_json[offset: offset + limit]
    return {"total": batch.row_count, "rows": rows}


@router.get("/{batch_id}/suggest")
def mapping_suggestion(batch_id: int, db: Session = Depends(get_db)) -> dict:
    batch = db.get(models.ImportBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="导入批次不存在")
    return {
        "batch_id": batch.id,
        "source_label": batch.source_label,
        "columns": batch.columns_json,
        "suggested_mappings": suggest_mappings(batch.columns_json),
    }
