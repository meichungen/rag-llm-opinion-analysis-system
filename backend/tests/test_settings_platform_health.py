import asyncio
import os

from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_task.db"

from app.core.database import AsyncSessionLocal, Base, engine
from app.main import app
from app.models.sql_models import SystemConfig, User


async def reset_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as session:
        await session.execute(delete(SystemConfig))
        await session.execute(delete(User))
        session.add(
            User(
                id=1,
                username="admin",
                email="admin@example.com",
                password_hash="hashed_password_placeholder",
                role="admin",
            )
        )
        await session.commit()


def test_get_platform_cookie_health(monkeypatch):
    monkeypatch.setattr(
        "app.main.read_platform_cookie_status",
        lambda platforms: {
            platform: {
                "has_cookie": platform == "douyin",
                "health": "warning" if platform == "douyin" else "missing",
                "issues": ["缺少关键 Cookie: passport_csrf_token"] if platform == "douyin" else ["未找到 Cookie 文件"],
                "required_keys": ["passport_csrf_token"],
                "missing_keys": ["passport_csrf_token"],
            }
            for platform in platforms
        },
    )

    async def _run():
        await reset_tables()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/settings/platform-cookie/health?platform=douyin")
        assert response.status_code == 200
        payload = response.json()
        assert payload["platforms"] == ["douyin"]
        assert payload["cookie_health"]["douyin"]["health"] == "warning"

    asyncio.run(_run())


def test_get_platform_crawler_settings():
    async def _run():
        await reset_tables()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/settings/platform-crawler?platform=bilibili")
        assert response.status_code == 200
        payload = response.json()
        assert payload["platform"] == "bilibili"
        assert payload["crawler"]["enable_unsigned_search_fallback"] is True
        assert payload["crawler"]["max_search_pages"] >= 1

    asyncio.run(_run())
