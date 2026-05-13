from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sql_models import AnalysisResult, Comment, Post, Task
from app.agent.vector_backends import VectorBackendClient

try:
    from sentence_transformers import SentenceTransformer
except ImportError:  # pragma: no cover
    SentenceTransformer = None

_INDEX_MODEL = None
_INDEX_MODEL_NAME = None


class KnowledgeIndexer:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        config = config or {}
        self.backend = str(config.get("retrieval_backend", "local_embedding")).lower()
        self.model_name = config.get("embedding_model", "moka-ai/m3e-base")
        self.vector_client = VectorBackendClient(config)

    async def sync_task(self, db: AsyncSession, task_id: int) -> Dict[str, Any]:
        docs = await self.build_documents(db, task_id)
        if not docs:
            return {"backend": self.backend, "synced_count": 0, "skipped": True}
        if self.backend == "local_embedding":
            return {"backend": self.backend, "synced_count": 0, "skipped": True}
        if self.backend == "redis_vector":
            await self.vector_client.redis_upsert(self._get_model(), docs)
            return {"backend": self.backend, "synced_count": len(docs), "skipped": False}
        if self.backend == "milvus":
            await self.vector_client.milvus_upsert(self._get_model(), docs)
            return {"backend": self.backend, "synced_count": len(docs), "skipped": False}
        return {"backend": self.backend, "synced_count": 0, "skipped": True}

    async def build_documents(self, db: AsyncSession, task_id: int) -> List[Dict[str, Any]]:
        row = (
            await db.execute(
                select(Task, AnalysisResult)
                .join(AnalysisResult, AnalysisResult.task_id == Task.id, isouter=True)
                .where(Task.id == task_id)
            )
        ).first()
        if not row:
            return []
        task, result = row
        docs = []
        if result and result.summary:
            docs.append(self._doc(task, "summary", result.summary, 0))
        posts = (await db.execute(select(Post.content).where(Post.task_id == task_id).limit(5))).scalars().all()
        comments = (
            await db.execute(select(Comment.content).join(Post).where(Post.task_id == task_id).limit(8))
        ).scalars().all()
        for idx, text in enumerate([item for item in posts if item], start=1):
            docs.append(self._doc(task, "post", text, idx))
        for idx, text in enumerate([item for item in comments if item], start=1):
            docs.append(self._doc(task, "comment", text, idx))
        return docs

    def _doc(self, task: Task, doc_type: str, content: str, idx: int) -> Dict[str, Any]:
        return {
            "doc_id": f"{task.id}:{doc_type}:{idx}",
            "task_id": task.id,
            "platform": task.platform,
            "keyword": task.keyword,
            "type": doc_type,
            "content": content[:1000],
        }

    def _get_model(self):
        global _INDEX_MODEL, _INDEX_MODEL_NAME
        if not SentenceTransformer:
            raise ValueError("未安装 sentence-transformers，无法生成索引向量。")
        if _INDEX_MODEL is None or _INDEX_MODEL_NAME != self.model_name:
            _INDEX_MODEL = SentenceTransformer(self.model_name, device="cpu")
            _INDEX_MODEL_NAME = self.model_name
        return _INDEX_MODEL
