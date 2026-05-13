import logging
import inspect
import os
import re
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sql_models import AnalysisResult, Comment, Post, Task
from app.agent.vector_backends import VectorBackendClient

try:
    from sentence_transformers import SentenceTransformer, util
except ImportError:  # pragma: no cover
    SentenceTransformer = None
    util = None


logger = logging.getLogger(__name__)
_EMBEDDING_MODEL = None
_EMBEDDING_MODEL_NAME = None
_EMBEDDING_DISABLED = False


class RagRetriever:
    def __init__(self, db: AsyncSession, config: Optional[Dict[str, Any]] = None):
        config = config or {}
        self.db = db
        self.backend = str(config.get("retrieval_backend", "local_embedding")).lower()
        self.model_name = config.get("embedding_model", "moka-ai/m3e-base")
        self.candidate_limit = int(config.get("retrieval_candidate_limit", 24))
        self.score_threshold = float(config.get("retrieval_score_threshold", 0.15))
        self.embedding_allow_download = bool(config.get("embedding_allow_download", False))
        self.vector_client = VectorBackendClient(config)

    def _get_embedding_model(self):
        global _EMBEDDING_MODEL, _EMBEDDING_MODEL_NAME, _EMBEDDING_DISABLED
        if not SentenceTransformer or not util:
            return None
        if _EMBEDDING_DISABLED:
            return None
        if _EMBEDDING_MODEL is None or _EMBEDDING_MODEL_NAME != self.model_name:
            try:
                kwargs = {"device": "cpu"}
                if not self.embedding_allow_download:
                    os.environ.setdefault("HF_HUB_OFFLINE", "1")
                    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
                    if "local_files_only" in inspect.signature(SentenceTransformer).parameters:
                        kwargs["local_files_only"] = True
                _EMBEDDING_MODEL = SentenceTransformer(self.model_name, **kwargs)
                _EMBEDDING_MODEL_NAME = self.model_name
            except Exception as exc:
                _EMBEDDING_DISABLED = True
                logger.warning("加载 Embedding 模型失败，当前进程改用关键词检索: %s", exc)
                return None
        return _EMBEDDING_MODEL

    async def search(self, query: str, top_k: int = 3) -> Dict[str, Any]:
        candidates = await self._load_candidates(query)
        if not candidates:
            raise ValueError("未检索到相关背景知识。")
        last_error = None
        for backend in self._backend_chain():
            try:
                results = await self._search_by_backend(backend, query, candidates, top_k)
                if results:
                    return {"query": query, "retriever": backend, "results": results}
            except Exception as exc:
                last_error = exc
                logger.warning("检索后端 %s 执行失败，准备降级: %s", backend, exc)
        if last_error:
            raise ValueError(f"未检索到相关背景知识，最后一次错误: {last_error}")
        raise ValueError("未检索到相关背景知识。")

    def _backend_chain(self) -> List[str]:
        chain = [self.backend, "local_embedding", "keyword"]
        deduplicated: List[str] = []
        for name in chain:
            normalized = name.lower()
            if normalized not in deduplicated:
                deduplicated.append(normalized)
        return deduplicated

    async def _search_by_backend(
        self, backend: str, query: str, candidates: List[Dict[str, Any]], top_k: int
    ) -> List[Dict[str, Any]]:
        if backend == "redis_vector":
            return await self._redis_vector_search(query, top_k)
        if backend == "milvus":
            return await self._milvus_search(query, top_k)
        if backend == "local_embedding":
            return self._embedding_search(query, candidates, top_k)
        if backend == "keyword":
            return self._keyword_search(query, candidates, top_k)
        raise ValueError(f"不支持的检索后端: {backend}")

    async def _load_candidates(self, query: str) -> List[Dict[str, Any]]:
        task_stmt = (
            select(Task, AnalysisResult)
            .join(AnalysisResult, AnalysisResult.task_id == Task.id, isouter=True)
            .where(or_(Task.keyword.like(f"%{query}%"), AnalysisResult.summary.like(f"%{query}%")))
            .order_by(desc(Task.created_at))
            .limit(max(6, self.candidate_limit // 3))
        )
        rows = (await self.db.execute(task_stmt)).all()
        if not rows:
            rows = (
                await self.db.execute(
                    select(Task, AnalysisResult)
                    .join(AnalysisResult, AnalysisResult.task_id == Task.id, isouter=True)
                    .order_by(desc(Task.created_at))
                    .limit(6)
                )
            ).all()
        candidates: List[Dict[str, Any]] = []
        for task, result in rows:
            summary = result.summary if result else ""
            if summary:
                candidates.append(self._doc(task, "summary", summary))
            posts = (
                await self.db.execute(select(Post.content).where(Post.task_id == task.id).limit(2))
            ).scalars().all()
            comments = (
                await self.db.execute(
                    select(Comment.content).join(Post).where(Post.task_id == task.id).limit(2)
                )
            ).scalars().all()
            for text in [item for item in posts + comments if item]:
                candidates.append(self._doc(task, "snippet", text))
            if len(candidates) >= self.candidate_limit:
                break
        return candidates[: self.candidate_limit]

    def _doc(self, task: Task, doc_type: str, text: str) -> Dict[str, Any]:
        return {
            "task_id": task.id,
            "platform": task.platform,
            "keyword": task.keyword,
            "type": doc_type,
            "content": text[:500],
        }

    async def _redis_vector_search(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        model = self._get_embedding_model()
        if not model:
            return []
        return await self.vector_client.redis_search(model, query, top_k)

    async def _milvus_search(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        model = self._get_embedding_model()
        if not model:
            return []
        return await self.vector_client.milvus_search(model, query, top_k)

    def _parse_redis_search_response(self, response: Any) -> List[Dict[str, Any]]:
        return self.vector_client.parse_redis_search_response(response)

    def _embedding_search(
        self, query: str, candidates: List[Dict[str, Any]], top_k: int
    ) -> List[Dict[str, Any]]:
        model = self._get_embedding_model()
        if not model:
            return []
        query_vector = model.encode(query, convert_to_tensor=True)
        texts = [f"{item['keyword']} {item['content']}" for item in candidates]
        doc_vectors = model.encode(texts, convert_to_tensor=True)
        scores = util.cos_sim(query_vector, doc_vectors)[0]
        ranked = []
        for idx, score in enumerate(scores):
            score_value = float(score)
            if score_value < self.score_threshold:
                continue
            item = dict(candidates[idx])
            item["score"] = round(score_value, 4)
            ranked.append(item)
        ranked.sort(key=lambda item: item["score"], reverse=True)
        return ranked[:top_k]

    def _keyword_search(
        self, query: str, candidates: List[Dict[str, Any]], top_k: int
    ) -> List[Dict[str, Any]]:
        terms = [item for item in re.split(r"\s+", query.strip()) if item] or [query]
        ranked = []
        for item in candidates:
            text = f"{item['keyword']} {item['content']}"
            score = sum(text.count(term) for term in terms)
            if score <= 0:
                continue
            record = dict(item)
            record["score"] = float(score)
            ranked.append(record)
        ranked.sort(key=lambda item: item["score"], reverse=True)
        return ranked[:top_k]
