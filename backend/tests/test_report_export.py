import asyncio
import os
from datetime import datetime

from httpx import ASGITransport, AsyncClient

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_task.db"

from app.core.database import AsyncSessionLocal, Base, engine
from app.main import app
from app.models.sql_models import Task
from app.services.report_service import ReportService


def test_export_analysis_report_pdf(monkeypatch):
    async def fake_generate_task_report(self, task_id: int):
        return {
            "filename": "report_test.pdf",
            "content": b"%PDF-1.4 mock content",
            "task_id": task_id,
        }

    monkeypatch.setattr(ReportService, "generate_task_report", fake_generate_task_report)

    async def _run():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with AsyncSessionLocal() as session:
            task = Task(
                user_id=1,
                platform="weibo",
                keyword="导出测试",
                post_count=10,
                comment_count=10,
                status="completed",
                created_at=datetime.now(),
            )
            session.add(task)
            await session.commit()
            await session.refresh(task)
            task_id = task.id

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"/api/analysis/report/{task_id}/pdf")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert "attachment; filename=report_test.pdf" == response.headers["content-disposition"]
        assert response.content.startswith(b"%PDF-1.4")

    asyncio.run(_run())
