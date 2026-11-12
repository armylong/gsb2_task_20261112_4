"""FastAPI 入口。

开发模式: uvicorn app.main:app --reload (前端走 Vite 5173 代理)
本地一体化: 先 build 前端, 后端直接托管 ../frontend/dist 静态文件
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import TARGET_SCHEMA
from .database import init_db
from .routers import exports, imports, recon, rules, runs


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="本地数据清洗对账工具", version="1.0.0", lifespan=lifespan)

# 本地开发: Vite dev server 5173 端口
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(imports.router)
app.include_router(rules.router)
app.include_router(runs.router)
app.include_router(recon.router)
app.include_router(exports.router)


@app.get("/api/meta")
def meta() -> dict:
    from .transform import DEFAULT_NULL_TOKENS, TARGET_TYPES

    return {
        "target_schema": TARGET_SCHEMA,
        "target_types": TARGET_TYPES,
        "default_null_tokens": DEFAULT_NULL_TOKENS,
    }


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


# ---- 生产模式托管前端构建产物 ----
_DIST_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _DIST_DIR.exists():
    app.mount(
        "/assets",
        StaticFiles(directory=_DIST_DIR / "assets"),
        name="assets",
    )

    @app.get("/{full_path:path}")
    def spa(full_path: str) -> FileResponse:  # pragma: no cover
        if full_path.startswith("api/"):
            return FileResponse(_DIST_DIR / "index.html", status_code=404)
        target = _DIST_DIR / full_path
        if full_path and target.is_file():
            return FileResponse(target)
        return FileResponse(_DIST_DIR / "index.html")
