import asyncio
import os
from datetime import datetime, timedelta

from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_task.db"

from app.core.database import AsyncSessionLocal, Base, engine
from app.main import app
from app.models.sql_models import Comment, DashboardMetricCache, Post, Task, User
from app.services.dashboard_service import (
    CACHE_TTL_SECONDS,
    TOTAL_COLLECTED_CACHE_KEY,
    DashboardService,
)


async def reset_dashboard_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        await session.execute(delete(Comment))
        await session.execute(delete(Post))
        await session.execute(delete(Task))
        await session.execute(delete(DashboardMetricCache))
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


def test_dashboard_metrics_cache_hit(monkeypatch):
    async def _run():
        await reset_dashboard_tables()
        async with AsyncSessionLocal() as session:
            session.add(
                DashboardMetricCache(
                    cache_key=TOTAL_COLLECTED_CACHE_KEY,
                    metric_value=321,
                    refreshed_at=datetime.now(),
                )
            )
            await session.commit()

            async def fail_recompute(_db):
                raise AssertionError("cache hit should not recompute")

            monkeypatch.setattr(DashboardService, "_recompute_total_collected", fail_recompute)

            total = await DashboardService.get_total_collected(session)
            assert total == 321

    asyncio.run(_run())


def test_dashboard_metrics_cache_miss_refreshes_cache():
    async def _run():
        await reset_dashboard_tables()
        async with AsyncSessionLocal() as session:
            task = Task(
                user_id=1,
                platform="weibo",
                keyword="dashboard",
                status="completed",
            )
            session.add(task)
            await session.flush()

            post = Post(
                task_id=task.id,
                platform_post_id="post-1",
                platform="weibo",
                content="post content",
            )
            session.add(post)
            await session.flush()

            session.add_all(
                [
                    Comment(post_id=post.id, platform_comment_id="comment-1", content="a"),
                    Comment(post_id=post.id, platform_comment_id="comment-2", content="b"),
                ]
            )
            await session.commit()

            total = await DashboardService.get_total_collected(session)
            assert total == 3

            cache_total = await DashboardService.get_total_collected(session)
            assert cache_total == 3

    asyncio.run(_run())


def test_dashboard_metrics_cache_stale_recomputes():
    async def _run():
        await reset_dashboard_tables()
        async with AsyncSessionLocal() as session:
            stale_at = datetime.now() - timedelta(seconds=CACHE_TTL_SECONDS + 5)
            session.add(
                DashboardMetricCache(
                    cache_key=TOTAL_COLLECTED_CACHE_KEY,
                    metric_value=1,
                    refreshed_at=stale_at,
                )
            )

            task = Task(
                user_id=1,
                platform="weibo",
                keyword="stale",
                status="running",
                created_at=datetime.now(),
            )
            session.add(task)
            await session.flush()

            post = Post(
                task_id=task.id,
                platform_post_id="post-2",
                platform="weibo",
                content="fresh post",
            )
            session.add(post)
            await session.flush()
            session.add(Comment(post_id=post.id, platform_comment_id="comment-3", content="fresh"))
            await session.commit()

            metrics = await DashboardService.get_metrics(session)
            assert metrics == {
                "totalCollected": 2,
                "activeTasks": 1,
                "todayNewTasks": 1,
            }

    asyncio.run(_run())


def test_dashboard_metrics_db_exception(monkeypatch):
    async def _run():
        await reset_dashboard_tables()
        async with AsyncSessionLocal() as session:
            async def boom(_db):
                raise RuntimeError("database unavailable")

            monkeypatch.setattr(DashboardService, "_recompute_total_collected", boom)

            try:
                await DashboardService.get_total_collected(session)
                assert False, "expected get_total_collected to raise"
            except RuntimeError as exc:
                assert str(exc) == "database unavailable"

    asyncio.run(_run())


def test_dashboard_metrics_refresh_cache_creates_and_updates_records():
    async def _run():
        await reset_dashboard_tables()
        async with AsyncSessionLocal() as session:
            task = Task(user_id=1, platform="weibo", keyword="refresh", status="completed")
            session.add(task)
            await session.flush()

            post = Post(
                task_id=task.id,
                platform_post_id="post-refresh",
                platform="weibo",
                content="refresh post",
            )
            session.add(post)
            await session.flush()
            session.add(Comment(post_id=post.id, platform_comment_id="comment-refresh", content="refresh"))
            await session.commit()

            created_total = await DashboardService.refresh_total_collected_cache(session)
            assert created_total == 2

            first_cache_total = await DashboardService.get_total_collected(session)
            assert first_cache_total == 2

            session.add(Comment(post_id=post.id, platform_comment_id="comment-refresh-2", content="refresh-2"))
            await session.commit()

            updated_total = await DashboardService.refresh_total_collected_cache(session)
            assert updated_total == 3

    asyncio.run(_run())


def test_dashboard_metrics_cache_stale_when_timestamp_missing():
    assert DashboardService._is_cache_stale(None) is True


def test_dashboard_metrics_endpoint_returns_json():
    async def _run():
        await reset_dashboard_tables()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/dashboard/metrics")
            assert response.status_code == 200
            assert response.json() == {
                "totalCollected": 0,
                "activeTasks": 0,
                "todayNewTasks": 0,
            }

    asyncio.run(_run())
