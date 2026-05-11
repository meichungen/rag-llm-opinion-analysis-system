import os
import asyncio
import json
import pytest
from httpx import AsyncClient, ASGITransport

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_task.db"

from app.core.database import AsyncSessionLocal, engine, Base
import app.main as main_module
from app.main import app
from sqlalchemy.future import select
from app.models.sql_models import Task


@pytest.fixture(scope="session", autouse=True)
def cleanup_db_file():
    try:
        if os.path.exists("test_task.db"):
            os.remove("test_task.db")
    except Exception:
        pass


@pytest.fixture(autouse=True)
def patch_background_tasks(monkeypatch):
    def _noop(task_id: int):
        return None
    monkeypatch.setattr(main_module, "run_task_logic", _noop)


def test_create_task_normal_input():
    async def _run():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {"platform": "weibo", "keyword": "AI", "post_count": 200, "comment_count": 500}
            res = await client.post("/api/tasks", json=payload)
            assert res.status_code == 201
            list_res = await client.get("/api/tasks", params={"limit": 1})
            assert list_res.status_code == 200
            data = list_res.json()
            assert data["tasks"]
            task = data["tasks"][0]
            assert task["post_count"] == 200
            assert task["comment_count"] == 500
    asyncio.run(_run())


def test_create_task_boundary_values():
    async def _run():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload_max = {"platform": "weibo", "keyword": "max", "post_count": 1000, "comment_count": 10000}
            res_max = await client.post("/api/tasks", json=payload_max)
            assert res_max.status_code == 201

            list_res = await client.get("/api/tasks", params={"limit": 100})
            assert list_res.status_code == 200
            tasks = list_res.json()["tasks"]
            found_max = any(t["keyword"] == "max" and t["post_count"] == 1000 and t["comment_count"] == 10000 for t in tasks)
            assert found_max
    asyncio.run(_run())


def test_create_task_invalid_inputs():
    async def _run():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload_neg = {"platform": "weibo", "keyword": "neg", "post_count": -1, "comment_count": 10}
            res_neg = await client.post("/api/tasks", json=payload_neg)
            assert res_neg.status_code == 422

            payload_zero = {"platform": "weibo", "keyword": "zero", "post_count": 0, "comment_count": 0}
            res_zero = await client.post("/api/tasks", json=payload_zero)
            assert res_zero.status_code == 422

            payload_nonnum = {"platform": "weibo", "keyword": "str", "post_count": "abc", "comment_count": 10}
            res_nonnum = await client.post("/api/tasks", json=payload_nonnum)
            assert res_nonnum.status_code == 422

            payload_overmax = {"platform": "weibo", "keyword": "over", "post_count": 1001, "comment_count": 10001}
            res_overmax = await client.post("/api/tasks", json=payload_overmax)
            assert res_overmax.status_code == 422

            payload_invalid_platform = {"platform": "zhihu", "keyword": "invalid", "post_count": 100, "comment_count": 100}
            res_invalid_platform = await client.post("/api/tasks", json=payload_invalid_platform)
            assert res_invalid_platform.status_code == 422
    asyncio.run(_run())
