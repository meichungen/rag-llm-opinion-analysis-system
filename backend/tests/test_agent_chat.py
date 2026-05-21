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

    async def fake_chat(self, prompt: str, temperature: float, **kwargs) -> str:
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

    async def fake_chat(self, prompt: str, temperature: float, **kwargs) -> str:
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


def test_agent_chat_direct_crawl_without_llm(monkeypatch):
    recorded = {}

    async def fail_chat(self, prompt: str, temperature: float, **kwargs) -> str:
        raise AssertionError("明确实时采集请求不应调用 LLM")

    async def fake_tool(self, action, params, session_id):
        self.used_tool = action
        recorded["action"] = action
        recorded["params"] = params
        return {
            "success": True,
            "status": "partial_success",
            "platform": params["platform"],
            "keyword": params["keyword"],
            "total_posts": 1,
            "total_comments": 0,
            "warnings": [{"scope": "comments", "message": "评论抓取数量不足，目标 100，实际 0。"}],
            "diagnostics": {"risk_fingerprints": []},
            "message": "抓取部分完成，存在告警或降级",
            "_tool_meta": {"name": action, "elapsed_ms": 12, "risk_level": "high"},
        }

    monkeypatch.setattr(OpinionAgent, "_chat", fail_chat)
    monkeypatch.setattr(ToolManager, "call_tool", fake_tool)

    async def _run():
        await reset_agent_tables()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/agent/chat",
                json={
                    "query": "实时采集抖音关于“首届南北早餐争霸赛”的前10个帖子及每条100条评论",
                    "session_id": "s-direct-crawl",
                },
            )
        assert response.status_code == 200
        payload = response.json()
        assert payload["used_tool"] == "crawl_data"
        assert payload["tool_observation"]["status"] == "partial_success"
        assert "实时采集部分完成" in payload["answer"]
        assert "LLM" not in payload["answer"]
        assert recorded == {
            "action": "crawl_data",
            "params": {
                "platform": "douyin",
                "keyword": "首届南北早餐争霸赛",
                "post_count": 10,
                "comment_count": 100,
            },
        }

    asyncio.run(_run())


def test_agent_chat_answer_generation_timeout_keeps_tool_result(monkeypatch):
    responses = iter(
        [
            '{"thought":"先查数据","action":"fetch_data","parameters":{"keyword":"小米","platform":"weibo"},"final":true}',
        ]
    )
    calls = []

    async def fake_chat(self, prompt: str, temperature: float, **kwargs) -> str:
        calls.append(kwargs)
        if len(calls) == 1:
            return next(responses)
        raise RuntimeError("LLM API 调用失败: Request timed out.")

    async def fake_tool(self, action, params, session_id):
        self.used_tool = action
        return {
            "task_id": 1,
            "keyword": params["keyword"],
            "platform": params["platform"],
            "status": "completed",
            "summary": "已有任务摘要",
            "sample_posts": ["帖子样本"],
            "sample_comments": ["评论样本"],
        }

    monkeypatch.setattr(OpinionAgent, "_chat", fake_chat)
    monkeypatch.setattr(ToolManager, "call_tool", fake_tool)

    async def _run():
        await reset_agent_tables()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/agent/chat",
                json={"query": "帮我看看微博上小米的舆情", "session_id": "s-timeout-fallback"},
            )
        assert response.status_code == 200
        payload = response.json()
        assert payload["used_tool"] == "fetch_data"
        assert payload["tool_observation"]["summary"] == "已有任务摘要"
        assert "当前 Agent 无法访问大模型服务" in payload["answer"]
        assert len(calls) == 2
        assert calls[1]["max_retries"] == 0

    asyncio.run(_run())


def test_agent_chat_crawl_permission_without_context_asks_for_details(monkeypatch):
    async def fail_chat(self, prompt: str, temperature: float, **kwargs) -> str:
        raise AssertionError("缺少采集对象时不应调用 LLM 猜测上下文")

    async def fail_tool(self, action, params, session_id):
        raise AssertionError("缺少平台或关键词时不应调用爬虫")

    monkeypatch.setattr(OpinionAgent, "_chat", fail_chat)
    monkeypatch.setattr(ToolManager, "call_tool", fail_tool)

    async def _run():
        await reset_agent_tables()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/agent/chat",
                json={"query": "明确要求实时采集，允许爬虫工具调用", "session_id": "s-missing-crawl"},
            )
        assert response.status_code == 200
        payload = response.json()
        assert payload["used_tool"] == "direct_answer"
        assert "请在同一句里说明平台、关键词和数量" in payload["answer"]
        assert payload["tool_observation"]["error"] == "缺少实时采集所需的平台或关键词。"
        assert payload["agent_trace"][0]["status"] == "blocked"

    asyncio.run(_run())


def test_agent_existing_data_query_does_not_direct_crawl(monkeypatch):
    responses = iter(
        [
            '```json\n{"thought":"查询已有任务数据","action":"fetch_data","parameters":{"keyword":"小米","platform":"weibo"},"final":true}\n```',
            "这是基于已有数据的分析。",
        ]
    )
    recorded = {}

    async def fake_chat(self, prompt: str, temperature: float, **kwargs) -> str:
        return next(responses)

    async def fake_tool(self, action, params, session_id):
        self.used_tool = action
        recorded["action"] = action
        recorded["params"] = params
        return {
            "task_id": 1,
            "keyword": params["keyword"],
            "platform": params["platform"],
            "status": "completed",
            "summary": "已有任务摘要",
        }

    monkeypatch.setattr(OpinionAgent, "_chat", fake_chat)
    monkeypatch.setattr(ToolManager, "call_tool", fake_tool)

    async def _run():
        await reset_agent_tables()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/agent/chat",
                json={"query": "分析当前任务已采集的微博小米数据", "session_id": "s-existing-data"},
            )
        assert response.status_code == 200
        payload = response.json()
        assert payload["answer"] == "这是基于已有数据的分析。"
        assert payload["used_tool"] == "fetch_data"
        assert recorded == {
            "action": "fetch_data",
            "params": {"keyword": "小米", "platform": "weibo"},
        }

    asyncio.run(_run())
