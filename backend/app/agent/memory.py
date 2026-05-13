import json
import os
import logging
from collections import defaultdict
from typing import Any, Awaitable, Callable, Dict, List, Optional

try:
    from redis import asyncio as redis
except ImportError:  # pragma: no cover
    redis = None


_LOCAL_MEMORY: Dict[str, List[str]] = defaultdict(list)
logger = logging.getLogger(__name__)


class AgentMemory:
    def __init__(
        self,
        searcher: Optional[Callable[[str, int], Awaitable[Dict[str, Any]]]] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        config = config or {}
        self.searcher = searcher
        self.backend = str(config.get("memory_backend", "redis")).lower()
        self.ttl_seconds = int(config.get("session_ttl_seconds", 3600))
        self.round_limit = int(config.get("session_round_limit", 5))
        self.redis_url = config.get("redis_url") or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.redis_connect_timeout = float(config.get("redis_connect_timeout", 0.5))
        self.redis_socket_timeout = float(config.get("redis_socket_timeout", 0.5))
        self.client = self._build_client()
        self._redis_disabled = False

    def _build_client(self):
        if self.backend != "redis" or not redis:
            return None
        try:
            return redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=self.redis_connect_timeout,
                socket_timeout=self.redis_socket_timeout,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("初始化 Redis 记忆失败，已降级到本地内存: %s", exc)
            return None

    def _disable_redis(self, action: str, exc: Exception) -> None:
        if self._redis_disabled:
            return
        self._redis_disabled = True
        self.client = None
        logger.warning("%s Redis 短期记忆失败，当前进程后续将直接使用本地内存: %s", action, exc)

    def _key(self, session_id: str) -> str:
        return f"agent:session:{session_id}"

    async def get(self, session_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        size = max(limit, 1) * 2
        if self.client:
            try:
                items = await self.client.lrange(self._key(session_id), -size, -1)
                return [json.loads(item) for item in items]
            except Exception as exc:
                self._disable_redis("读取", exc)
        messages = _LOCAL_MEMORY.get(session_id, [])
        return [json.loads(item) for item in messages[-size:]]

    async def add(self, session_id: str, message: Dict[str, Any]) -> None:
        payload = json.dumps(message, ensure_ascii=False)
        keep_size = self.round_limit * 2
        if self.client:
            try:
                key = self._key(session_id)
                await self.client.rpush(key, payload)
                await self.client.ltrim(key, -keep_size, -1)
                await self.client.expire(key, self.ttl_seconds)
                return
            except Exception as exc:
                self._disable_redis("写入", exc)
        _LOCAL_MEMORY[session_id].append(payload)
        _LOCAL_MEMORY[session_id] = _LOCAL_MEMORY[session_id][-keep_size:]

    async def search_long_term(self, query: str, top_k: int = 3) -> Dict[str, Any]:
        if not self.searcher:
            return {"query": query, "results": []}
        try:
            return await self.searcher(query, top_k)
        except Exception:
            return {"query": query, "results": []}
