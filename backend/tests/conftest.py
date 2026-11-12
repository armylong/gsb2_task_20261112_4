"""pytest 公共夹具: 每个测试使用独立临时数据库。"""
from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator

import pytest

_tmp = tempfile.mkdtemp(prefix="recon_test_")
os.environ["RECON_WORK_DIR"] = _tmp


@pytest.fixture()
def db() -> Iterator:
    from app.database import Base, SessionLocal, engine
    from app import models  # noqa: F401

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client() -> Iterator:
    """确保 TestClient 的 startup 已执行(建表), 并在每个测试前重置数据。"""
    from fastapi.testclient import TestClient

    from app.database import Base, engine
    from app import models  # noqa: F401
    from app.main import app

    with TestClient(app) as test_client:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        yield test_client
