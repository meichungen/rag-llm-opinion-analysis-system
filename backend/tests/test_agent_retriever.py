import asyncio

from app.agent.retriever import RagRetriever


def test_retriever_falls_back_from_redis_vector_to_local_embedding(monkeypatch):
    retriever = RagRetriever(
        db=None,
        config={"retrieval_backend": "redis_vector", "embedding_model": "mock-model"},
    )

    async def fake_load_candidates(self, query):
        return [{"task_id": 1, "platform": "weibo", "keyword": "小米", "type": "summary", "content": "小米 热议"}]

    async def fake_redis(self, query, top_k):
        raise RuntimeError("redis vector unavailable")

    def fake_embedding(self, query, candidates, top_k):
        return [{"task_id": 1, "platform": "weibo", "keyword": "小米", "type": "summary", "content": "小米 热议", "score": 0.88}]

    monkeypatch.setattr(RagRetriever, "_load_candidates", fake_load_candidates)
    monkeypatch.setattr(RagRetriever, "_redis_vector_search", fake_redis)
    monkeypatch.setattr(RagRetriever, "_embedding_search", fake_embedding)

    async def _run():
        result = await retriever.search("小米", top_k=3)
        assert result["retriever"] == "local_embedding"
        assert result["results"][0]["score"] == 0.88

    asyncio.run(_run())


def test_retriever_uses_milvus_backend_when_results_exist(monkeypatch):
    retriever = RagRetriever(db=None, config={"retrieval_backend": "milvus"})

    async def fake_load_candidates(self, query):
        return [{"task_id": 1, "platform": "weibo", "keyword": "华为", "type": "summary", "content": "华为 热议"}]

    async def fake_milvus(self, query, top_k):
        return [{"task_id": 2, "platform": "weibo", "keyword": "华为", "type": "snippet", "content": "讨论很多", "score": 0.91}]

    monkeypatch.setattr(RagRetriever, "_load_candidates", fake_load_candidates)
    monkeypatch.setattr(RagRetriever, "_milvus_search", fake_milvus)

    async def _run():
        result = await retriever.search("华为", top_k=2)
        assert result["retriever"] == "milvus"
        assert result["results"][0]["task_id"] == 2

    asyncio.run(_run())


def test_parse_redis_search_response_handles_binary_fields():
    retriever = RagRetriever(db=None, config={})
    response = [
        1,
        b"doc:1",
        [
            b"task_id",
            b"12",
            b"platform",
            b"weibo",
            b"keyword",
            "小米".encode("utf-8"),
            b"type",
            b"summary",
            b"content",
            "这是一段摘要".encode("utf-8"),
            b"score",
            b"0.1234",
        ],
    ]
    results = retriever._parse_redis_search_response(response)
    assert results == [
        {
            "task_id": 12,
            "platform": "weibo",
            "keyword": "小米",
            "type": "summary",
            "content": "这是一段摘要",
            "score": 0.1234,
        }
    ]
