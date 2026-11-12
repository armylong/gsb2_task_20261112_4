"""全局配置。所有运行期产物都放在工作目录下, 便于本地清理。"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
WORK_DIR = Path(os.environ.get("RECON_WORK_DIR", BASE_DIR / "workdata"))
DB_PATH = WORK_DIR / "app.db"
EXPORT_DIR = WORK_DIR / "exports"

WORK_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = f"sqlite:///{DB_PATH}"

# 统一后的目标字段: key -> 显示名
TARGET_SCHEMA: dict[str, str] = {
    "biz_no": "业务编号",
    "full_name": "客户全名",
    "amount": "订单金额",
    "order_date": "下单日期",
    "channel": "渠道",
    "status": "单据状态",
}
