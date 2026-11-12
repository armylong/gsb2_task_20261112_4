#!/usr/bin/env bash
# 生产式本地运行: 构建前端, 由 FastAPI 直接托管, 单端口 8000
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"

cd "$ROOT_DIR/frontend"
[ -d node_modules ] || npm install
npm run build

cd "$ROOT_DIR/backend"
[ -d .venv ] || (python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt)
echo ">> 单端口模式: http://127.0.0.1:8000"
exec ./.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
