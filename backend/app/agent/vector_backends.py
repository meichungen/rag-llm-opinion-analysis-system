import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

import numpy as np

try:
    from redis import asyncio as redis_async
except ImportError:  # pragma: no cover
    redis_async = None

try:
    from pymilvus import Collection, connections
except ImportError:  # pragma: no cover
    Collection = None
    connections = None


logger = logging.getLogger(__name__)


class VectorBackendClient:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        config = config or {}
        self.redis_url = config.get("redis_url") or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.redis_index_name = config.get("redis_index_name", "idx:agent_knowledge")
        self.redis_vector_field = config.get("redis_vector_field", "embedding")
        self.redis_doc_prefix = config.get("redis_doc_prefix", "agent:doc")
        self.milvus_collection = config.get("milvus_collection", "agent_knowledge")
        self.milvus_host = config.get("milvus_host", "localhost")
        self.milvus_port = str(config.get("milvus_port", "19530"))
        self.milvus_uri = config.get("milvus_uri")
        self.milvus_token = config.get("milvus_token")

    async def redis_search(self, model, query: str, top_k: int) -> List[Dict[str, Any]]:
        if not redis_async:
            raise ValueError("未安装 redis 异步客户端，无法使用 Redis Vector 检索。")
        query_vector = self.encode_query_vector(model, query)
        client = redis_async.from_url(self.redis_url, decode_responses=False)
        try:
            response = await client.execute_command(
                "FT.SEARCH",
                self.redis_index_name,
                f"*=>[KNN {top_k} @{self.redis_vector_field} $vec AS score]",
                "PARAMS",
                2,
                "vec",
                query_vector,
                "SORTBY",
                "score",
                "RETURN",
                6,
                "task_id",
                "platform",
                "keyword",
                "type",
                "content",
                "score",
                "DIALECT",
                2,
            )
            return self.parse_redis_search_response(response)
        finally:
            await client.close()

    async def milvus_search(self, model, query: str, top_k: int) -> List[Dict[str, Any]]:
        if not Collection or not connections:
            raise ValueError("未安装 pymilvus，无法使用 Milvus 检索。")
        return await asyncio.to_thread(self._milvus_search_sync, model, query, top_k)

    async def redis_upsert(self, model, docs: List[Dict[str, Any]]) -> None:
        if not redis_async:
            raise ValueError("未安装 redis 异步客户端，无法写入 Redis Vector。")
        client = redis_async.from_url(self.redis_url, decode_responses=False)
        try:
            for doc in docs:
                key = f"{self.redis_doc_prefix}:{doc['doc_id']}"
                await client.hset(
                    key,
                    mapping={
                        "task_id": str(doc["task_id"]),
                        "platform": doc["platform"],
                        "keyword": doc["keyword"],
                        "type": doc["type"],
                        "content": doc["content"],
                        "embedding": self.encode_query_vector(
                            model, f"{doc['keyword']} {doc['content']}"
                        ),
                    },
                )
        finally:
            await client.close()

    async def milvus_upsert(self, model, docs: List[Dict[str, Any]]) -> None:
        if not Collection or not connections:
            raise ValueError("未安装 pymilvus，无法写入 Milvus。")
        await asyncio.to_thread(self._milvus_upsert_sync, model, docs)

    def _milvus_search_sync(self, model, query: str, top_k: int) -> List[Dict[str, Any]]:
        args = {"alias": "agent_retriever"}
        self._fill_milvus_args(args)
        connections.connect(**args)
        collection = Collection(self.milvus_collection, using="agent_retriever")
        search_result = collection.search(
            data=[self.encode_query_vector(model, query, as_bytes=False)],
            anns_field="embedding",
            param={"metric_type": "COSINE", "params": {"nprobe": 10}},
            limit=top_k,
            output_fields=["task_id", "platform", "keyword", "type", "content"],
        )
        results: List[Dict[str, Any]] = []
        for hit in search_result[0]:
            entity = hit.entity
            results.append(
                {
                    "task_id": entity.get("task_id"),
                    "platform": entity.get("platform"),
                    "keyword": entity.get("keyword"),
                    "type": entity.get("type"),
                    "content": entity.get("content"),
                    "score": round(float(hit.score), 4),
                }
            )
        return results

    def _milvus_upsert_sync(self, model, docs: List[Dict[str, Any]]) -> None:
        args = {"alias": "agent_indexer"}
        self._fill_milvus_args(args)
        connections.connect(**args)
        collection = Collection(self.milvus_collection, using="agent_indexer")
        collection.insert(
            [
                [doc["doc_id"] for doc in docs],
                [doc["task_id"] for doc in docs],
                [doc["platform"] for doc in docs],
                [doc["keyword"] for doc in docs],
                [doc["type"] for doc in docs],
                [doc["content"] for doc in docs],
                [
                    self.encode_query_vector(
                        model, f"{doc['keyword']} {doc['content']}", as_bytes=False
                    )
                    for doc in docs
                ],
            ]
        )

    def _fill_milvus_args(self, args: Dict[str, Any]) -> None:
        if self.milvus_uri:
            args["uri"] = self.milvus_uri
        else:
            args["host"] = self.milvus_host
            args["port"] = self.milvus_port
        if self.milvus_token:
            args["token"] = self.milvus_token

    def encode_query_vector(self, model, query: str, as_bytes: bool = True):
        vector = np.asarray(model.encode(query), dtype=np.float32)
        return vector.tobytes() if as_bytes else vector.tolist()

    def parse_redis_search_response(self, response: Any) -> List[Dict[str, Any]]:
        if not isinstance(response, list) or len(response) < 3:
            return []
        results: List[Dict[str, Any]] = []
        for idx in range(1, len(response), 2):
            if idx + 1 >= len(response):
                break
            fields = response[idx + 1]
            if not isinstance(fields, list):
                continue
            record = self._pairs_to_dict(fields)
            if not record:
                continue
            results.append(
                {
                    "task_id": self._safe_int(record.get("task_id")),
                    "platform": record.get("platform", ""),
                    "keyword": record.get("keyword", ""),
                    "type": record.get("type", ""),
                    "content": record.get("content", ""),
                    "score": self._safe_float(record.get("score")),
                }
            )
        return results

    def _pairs_to_dict(self, fields: List[Any]) -> Dict[str, str]:
        record: Dict[str, str] = {}
        for idx in range(0, len(fields), 2):
            if idx + 1 >= len(fields):
                break
            record[str(self._decode_value(fields[idx]))] = str(self._decode_value(fields[idx + 1]))
        return record

    def _decode_value(self, value: Any) -> Any:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="ignore")
        return value

    def _safe_int(self, value: Any) -> Optional[int]:
        try:
            return int(value)
        except Exception:
            return None

    def _safe_float(self, value: Any) -> float:
        try:
            return round(float(value), 4)
        except Exception:
            return 0.0
