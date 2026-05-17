import asyncio
import os

from sqlalchemy import delete

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_task.db"

from app.agent.indexer import KnowledgeIndexer
from app.agent.vector_backends import VectorBackendClient
from app.core.database import AsyncSessionLocal, Base, engine
from app.models.sql_models import AnalysisResult, Comment, Post, SystemConfig, Task, User
from app.services import services as services_module


async def reset_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as session:
        await session.execute(delete(AnalysisResult))
        await session.execute(delete(Comment))
        await session.execute(delete(Post))
        await session.execute(delete(Task))
        await session.execute(delete(SystemConfig))
        await session.execute(delete(User))
        session.add(User(id=1, username="admin", email="admin@example.com", password_hash="x", role="admin"))
        await session.commit()


def test_indexer_build_documents():
    async def _run():
        await reset_tables()
        async with AsyncSessionLocal() as session:
            task = Task(user_id=1, platform="weibo", keyword="小米", status="completed")
            session.add(task)
            await session.flush()
            session.add(AnalysisResult(task_id=task.id, summary="这是任务摘要"))
            post = Post(task_id=task.id, platform_post_id="p1", platform="weibo", content="帖子内容")
            session.add(post)
            await session.flush()
            session.add(Comment(post_id=post.id, platform_comment_id="c1", content="评论内容"))
            await session.commit()
            docs = await KnowledgeIndexer({"retrieval_backend": "redis_vector"}).build_documents(session, task.id)
        assert [doc["type"] for doc in docs] == ["summary", "post", "comment"]
        assert docs[0]["keyword"] == "小米"

    asyncio.run(_run())


def test_sync_task_knowledge_uses_merged_agent_config(monkeypatch):
    recorded = {}

    async def fake_sync(self, db, task_id):
        recorded["backend"] = self.backend
        recorded["task_id"] = task_id
        return {"backend": self.backend, "synced_count": 2, "skipped": False}

    monkeypatch.setattr(KnowledgeIndexer, "sync_task", fake_sync)

    async def _run():
        await reset_tables()
        async with AsyncSessionLocal() as session:
            session.add(SystemConfig(key="agent", value={"retrieval_backend": "milvus"}))
            await session.commit()
            result = await services_module._sync_task_knowledge(session, 99)
        assert result["backend"] == "milvus"
        assert recorded == {"backend": "milvus", "task_id": 99}

    asyncio.run(_run())


def test_sync_task_skips_local_embedding():
    async def _run():
        await reset_tables()
        async with AsyncSessionLocal() as session:
            task = Task(user_id=1, platform="weibo", keyword="本地模式", status="completed")
            session.add(task)
            await session.flush()
            session.add(AnalysisResult(task_id=task.id, summary="仅构建文档，不落向量库"))
            await session.commit()
            result = await KnowledgeIndexer({"retrieval_backend": "local_embedding"}).sync_task(
                session, task.id
            )
        assert result == {"backend": "local_embedding", "synced_count": 0, "skipped": True}

    asyncio.run(_run())


def test_sync_task_calls_redis_upsert(monkeypatch):
    recorded = {}

    async def fake_upsert(self, model, docs):
        recorded["count"] = len(docs)
        recorded["first_type"] = docs[0]["type"]

    class FakeModel:
        pass

    monkeypatch.setattr(VectorBackendClient, "redis_upsert", fake_upsert)
    monkeypatch.setattr(KnowledgeIndexer, "_get_model", lambda self: FakeModel())

    async def _run():
        await reset_tables()
        async with AsyncSessionLocal() as session:
            task = Task(user_id=1, platform="weibo", keyword="Redis写入", status="completed")
            session.add(task)
            await session.flush()
            session.add(AnalysisResult(task_id=task.id, summary="摘要"))
            await session.commit()
            result = await KnowledgeIndexer({"retrieval_backend": "redis_vector"}).sync_task(
                session, task.id
            )
        assert result == {"backend": "redis_vector", "synced_count": 1, "skipped": False}
        assert recorded == {"count": 1, "first_type": "summary"}

    asyncio.run(_run())
