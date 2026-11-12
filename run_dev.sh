#!/usr/bin/env bash
# 一键启动本地开发环境: 后端 8000 + 前端 5173
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

# ---- 后端 ----
cd "$BACKEND_DIR"
if [ ! -d ".venv" ]; then
  echo ">> 创建 Python 虚拟环境并安装依赖..."
  python3 -m venv .venv
  ./.venv/bin/pip install --disable-pip-version-check -r requirements.txt
fi

# ---- 前端 ----
cd "$FRONTEND_DIR"
if [ ! -d "node_modules" ]; then
  echo ">> 安装前端依赖..."
  npm install
fi

echo ">> 启动后端 http://127.0.0.1:8000 (API 文档 /docs)"
echo ">> 启动前端 http://127.0.0.1:5173"
cd "$BACKEND_DIR"
./.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!
cd "$FRONTEND_DIR"
npm run dev &
FRONTEND_PID=$!

trap 'echo; echo ">> 停止服务..."; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null || true' EXIT
wait
