import asyncio

from app.agent import crawler_tools as crawler_tools_module
from app.agent.crawler_tools import AgentCrawlerTool, crawl_platform
from app.crawler.bili.client import BilibiliClient
from app.crawler.bili.crawler import BilibiliCrawler
from app.crawler.bili.exception import DataFetchError


def test_load_plain_text_cookies_for_douyin(tmp_path, monkeypatch):
    cookie_file = tmp_path / "cookies_douyin.json"
    cookie_file.write_text("sessionid=abc123; passport_csrf_token=token456", encoding="utf-8")

    monkeypatch.setattr(
        crawler_tools_module,
        "get_cookie_file_candidates",
        lambda platform: [str(cookie_file)],
    )

    cookies = AgentCrawlerTool._load_cookies_sync("douyin")

    assert len(cookies) == 2
    assert all(cookie["domain"] == ".douyin.com" for cookie in cookies)
    assert cookies[0]["name"] == "sessionid"
    assert cookies[0]["value"] == "abc123"


def test_bilibili_search_fallback_to_unsigned(monkeypatch):
    client = BilibiliClient(
        headers={"User-Agent": "pytest"},
        playwright_page=None,
        cookie_dict={},
    )
    calls = []

    async def fake_get(uri, params=None, enable_params_sign=True):
        calls.append((uri, enable_params_sign, params["page"]))
        if uri == "/x/web-interface/wbi/search/type":
            raise DataFetchError("Failed to get wbi keys")
        return {"result": [{"bvid": "BV1xx", "type": "video"}]}

    monkeypatch.setattr(client, "get", fake_get)

    async def _run():
        result = await client.search_video_by_keyword("原神", page=2, page_size=20)
        assert result["result"][0]["bvid"] == "BV1xx"

    asyncio.run(_run())

    assert calls == [
        ("/x/web-interface/wbi/search/type", True, 2),
        ("/x/web-interface/search/type", False, 2),
    ]


def test_bilibili_comments_fallback_to_unsigned(monkeypatch):
    crawler = BilibiliCrawler(browser=None)
    calls = []

    class FakeClient:
        async def get(self, uri, params=None, enable_params_sign=True):
            calls.append((uri, enable_params_sign, params["mode"]))
            if uri == "/x/v2/reply/wbi/main":
                raise DataFetchError("Failed to get wbi keys")
            return {"replies": [{"rpid": 1}]}

    crawler.client = FakeClient()

    async def _run():
        result = await crawler.get_video_comments_by_mode("123", next_page=0, mode=2)
        assert result["replies"][0]["rpid"] == 1

    asyncio.run(_run())

    assert calls == [
        ("/x/v2/reply/wbi/main", True, 2),
        ("/x/v2/reply/main", False, 2),
    ]


def test_crawl_platform_respects_requested_post_count(monkeypatch):
    class FakePage:
        async def close(self):
            return None

    class FakeContext:
        async def new_page(self):
            return FakePage()

    class FakeCrawler:
        def __init__(self, browser, config=None):
            self.browser = browser
            self.config = config or {}
            self.context = None
            self.page = None
            self.client = None
            self.comment_calls = []

        async def init_client(self):
            return None

        async def search_posts(self, keyword, count):
            return [{"id": f"post-{idx}", "content": keyword} for idx in range(1, 6)]

        async def get_comments(self, post_id, count):
            self.comment_calls.append((post_id, count))
            return [{"id": f"{post_id}-comment", "content": "ok"}]

    fake_crawler_instances = []

    def fake_crawler_factory(browser, config=None):
        crawler = FakeCrawler(browser, config)
        fake_crawler_instances.append(crawler)
        return crawler

    async def fake_ensure_browser():
        return object()

    async def fake_ensure_context(platform):
        return FakeContext()

    monkeypatch.setattr(crawler_tools_module, "DouyinCrawler", fake_crawler_factory)
    monkeypatch.setattr(AgentCrawlerTool, "ensure_browser", fake_ensure_browser)
    monkeypatch.setattr(AgentCrawlerTool, "ensure_context", fake_ensure_context)
    monkeypatch.setattr(crawler_tools_module, "read_cookie_metadata", lambda platform: {"health": "healthy", "issues": []})

    async def _run():
        result = await crawl_platform("douyin", "原神", post_count=3, comment_count=12)
        assert result["success"] is True
        assert result["status"] == "partial_success"
        assert len(result["posts"]) == 3
        assert result["diagnostics"]["processed_posts"] == 3
        assert result["diagnostics"]["comments_per_post"] == 4
        assert len(result["comments"]) == 3

    asyncio.run(_run())

    assert fake_crawler_instances[0].comment_calls == [
        ("post-1", 4),
        ("post-2", 4),
        ("post-3", 4),
    ]


def test_crawl_platform_collects_cookie_warning(monkeypatch):
    class FakePage:
        async def close(self):
            return None

    class FakeContext:
        async def new_page(self):
            return FakePage()

    class FakeCrawler:
        def __init__(self, browser, config=None):
            self.browser = browser
            self.config = config or {}
            self.context = None
            self.page = None

        async def init_client(self):
            return None

        async def search_posts(self, keyword, count):
            return [{"id": "post-1", "content": keyword}]

        async def get_comments(self, post_id, count):
            return [{"id": "comment-1", "content": "ok"}]

    async def fake_ensure_browser():
        return object()

    async def fake_ensure_context(platform):
        return FakeContext()

    monkeypatch.setattr(crawler_tools_module, "DouyinCrawler", lambda browser, config=None: FakeCrawler(browser, config))
    monkeypatch.setattr(AgentCrawlerTool, "ensure_browser", fake_ensure_browser)
    monkeypatch.setattr(AgentCrawlerTool, "ensure_context", fake_ensure_context)
    monkeypatch.setattr(
        crawler_tools_module,
        "read_cookie_metadata",
        lambda platform: {"health": "warning", "issues": ["缺少关键 Cookie: passport_csrf_token"]},
    )

    async def _run():
        result = await crawl_platform("douyin", "测试", post_count=1, comment_count=1)
        assert result["success"] is True
        assert result["status"] == "partial_success"
        assert result["warnings"][0]["scope"] == "cookie"
        assert result["diagnostics"]["cookie_health"]["health"] == "warning"

    asyncio.run(_run())
