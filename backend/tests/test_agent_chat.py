import asyncio
import os

from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_task.db"

from app.agent.agent import OpinionAgent
from app.agent.tool_manager import ToolManager
from app.core.database import AsyncSessionLocal, Base, engine
from app.main import app
from app.models.sql_models import AnalysisResult, Comment, Post, SystemConfig, Task, User


async def reset_agent_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as session:
        await session.execute(delete(AnalysisResult))
        await session.execute(delete(Comment))
        await session.execute(delete(Post))
        await session.execute(delete(Task))
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


def test_agent_chat_direct_answer(monkeypatch):
    responses = iter(
        [
            '```json\n{"thought":"直接回答即可","action":"direct_answer","parameters":{}}\n```',
            "这是 Agent 的直接回答。",
        ]
    )

    async def fake_chat(self, prompt: str, temperature: float) -> str:
        return next(responses)

    async def fail_tool(self, action, params, session_id):
        raise AssertionError("direct_answer 分支不应调用工具")

    monkeypatch.setattr(OpinionAgent, "_chat", fake_chat)
    monkeypatch.setattr(ToolManager, "call_tool", fail_tool)

    async def _run():
        await reset_agent_tables()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/agent/chat",
                json={"query": "帮我总结一下今天的舆情", "session_id": "s-direct"},
            )
        assert response.status_code == 200
        payload = response.json()
        assert payload["answer"] == "这是 Agent 的直接回答。"
        assert payload["used_tool"] == "direct_answer"
        assert payload["tool_observation"]["message"] == "本轮直接回答，无需调用工具。"

    asyncio.run(_run())


def test_agent_chat_tool_fallback(monkeypatch):
    responses = iter(
        [
            '{"thought":"先查数据","action":"fetch_data","parameters":{"keyword":"小米"}}',
            "",
        ]
    )
    recorded = {}

    async def fake_chat(self, prompt: str, temperature: float) -> str:
        return next(responses)

    async def fail_tool(self, action, params, session_id):
        recorded["action"] = action
        recorded["params"] = params
        return {"error": "工具执行失败: mock tool error", "fallback": "direct_answer"}

    monkeypatch.setattr(OpinionAgent, "_chat", fake_chat)
    monkeypatch.setattr(ToolManager, "call_tool", fail_tool)

    async def _run():
        await reset_agent_tables()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/agent/chat",
                json={"query": "帮我看看微博上小米的舆情", "session_id": "s-fallback"},
            )
        assert response.status_code == 200
        payload = response.json()
        assert payload["used_tool"] == "direct_answer"
        assert "工具调用失败" in payload["answer"]
        assert payload["tool_observation"]["error"] == "工具执行失败: mock tool error"
        assert recorded == {
            "action": "fetch_data",
            "params": {"keyword": "小米", "platform": "weibo"},
        }

    asyncio.run(_run())
