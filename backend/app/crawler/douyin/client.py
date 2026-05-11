import copy
import json
import logging
import os
import random
import urllib.parse
from typing import Any, Dict, List, Optional

import httpx
from playwright.async_api import BrowserContext, Page
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from .exception import DataFetchError

logger = logging.getLogger(__name__)


def get_web_id() -> str:
    def build(seed: Optional[int]) -> str:
        if seed is not None:
            return str(seed ^ (int(16 * random.random()) >> (seed // 4)))
        return "-".join(
            [
                str(int(1e7)),
                str(int(1e3)),
                str(int(4e3)),
                str(int(8e3)),
                str(int(1e11)),
            ]
        )

    value = "".join(build(int(ch)) if ch in "018" else ch for ch in build(None))
    return value.replace("-", "")[:19]


class DouyinClient:
    def __init__(
        self,
        timeout: int = 60,
        proxy: Optional[str] = None,
        *,
        headers: Dict[str, str],
        playwright_page: Page,
        cookie_dict: Dict[str, str],
    ):
        self.proxy = proxy
        self.timeout = timeout
        self.headers = headers
        self._host = "https://www.douyin.com"
        self.playwright_page = playwright_page
        self.cookie_dict = cookie_dict
        self.sign_script_path = os.path.join(os.path.dirname(__file__), "douyin_sign.js")
        self._sign_script_loaded = False

    async def _ensure_sign_script_loaded(self) -> None:
        if self._sign_script_loaded:
            return

        try:
            has_sign = await self.playwright_page.evaluate(
                "() => typeof window.sign_datail === 'function' && typeof window.sign_reply === 'function'"
            )
            if not has_sign:
                await self.playwright_page.add_script_tag(path=self.sign_script_path)
            self._sign_script_loaded = True
        except Exception as exc:
            logger.error(f"Failed to load Douyin sign script: {exc}")
            raise DataFetchError("抖音签名脚本加载失败")

    async def _build_common_params(self) -> Dict[str, str]:
        local_storage = await self.playwright_page.evaluate("() => window.localStorage")
        browser_env = await self.playwright_page.evaluate(
            """() => ({
                language: navigator.language || 'zh-CN',
                platform: navigator.platform || 'Win32',
                appVersion: navigator.appVersion || '',
                userAgent: navigator.userAgent || '',
                width: String(window.screen.width || 1920),
                height: String(window.screen.height || 1080),
                memory: String(navigator.deviceMemory || 8),
                online: navigator.onLine ? 'true' : 'false',
                cpu: String(navigator.hardwareConcurrency || 8),
                effectiveType: (navigator.connection && navigator.connection.effectiveType) || '4g',
                rtt: String((navigator.connection && navigator.connection.rtt) || 50)
            })"""
        )

        return {
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
            "version_code": "190600",
            "version_name": "19.6.0",
            "update_version_code": "170400",
            "pc_client_type": "1",
            "cookie_enabled": "true",
            "browser_language": browser_env["language"],
            "browser_platform": browser_env["platform"],
            "browser_name": "Chrome",
            "browser_version": self._extract_browser_version(browser_env["userAgent"]),
            "browser_online": browser_env["online"],
            "engine_name": "Blink",
            "os_name": "Windows" if "Win" in browser_env["platform"] else "Mac OS",
            "os_version": browser_env["appVersion"],
            "cpu_core_num": browser_env["cpu"],
            "device_memory": browser_env["memory"],
            "engine_version": self._extract_browser_version(browser_env["userAgent"]),
            "platform": "PC",
            "screen_width": browser_env["width"],
            "screen_height": browser_env["height"],
            "effective_type": browser_env["effectiveType"],
            "round_trip_time": browser_env["rtt"],
            "webid": get_web_id(),
            "msToken": local_storage.get("xmst", ""),
        }

    @staticmethod
    def _extract_browser_version(user_agent: str) -> str:
        marker = "Chrome/"
        if marker in user_agent:
            return user_agent.split(marker, 1)[1].split(" ", 1)[0]
        return "125.0.0.0"

    async def _prepare_params(
        self,
        uri: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        data = dict(params or {})
        data.update(await self._build_common_params())

        if "/aweme/v1/web/general/search" not in uri:
            await self._ensure_sign_script_loaded()
            query_string = urllib.parse.urlencode(data)
            sign_func = "sign_reply" if "/reply/" in uri else "sign_datail"
            user_agent = (headers or self.headers).get("User-Agent", "")
            data["a_bogus"] = await self.playwright_page.evaluate(
                "([fnName, query, ua]) => window[fnName](query, ua)",
                [sign_func, query_string, user_agent],
            )

        return data

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_random_exponential(min=1, max=10),
        retry=retry_if_exception_type((httpx.ConnectError, httpx.ReadTimeout, DataFetchError)),
        reraise=True,
    )
    async def request(self, method: str, url: str, **kwargs) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(proxy=self.proxy, follow_redirects=True) as client:
                response = await client.request(method, url, timeout=self.timeout, **kwargs)
            response.raise_for_status()
            if not response.text or response.text == "blocked":
                raise DataFetchError("抖音接口返回空内容或被风控拦截")
            return response.json()
        except json.JSONDecodeError as exc:
            logger.error(f"Douyin response is not valid JSON: {response.text[:500]}")
            raise DataFetchError("抖音接口返回了非 JSON 内容") from exc
        except httpx.HTTPError as exc:
            raise DataFetchError(f"抖音请求失败: {exc}") from exc

    async def get(self, uri: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None):
        request_headers = headers or self.headers
        final_params = await self._prepare_params(uri, params, request_headers)
        return await self.request("GET", f"{self._host}{uri}", params=final_params, headers=request_headers)

    async def pong(self, browser_context: BrowserContext) -> bool:
        try:
            local_storage = await self.playwright_page.evaluate("() => window.localStorage")
            if local_storage.get("HasUserLogin", "") == "1":
                return True
        except Exception:
            pass

        cookies = await browser_context.cookies()
        cookie_dict = {cookie["name"]: cookie["value"] for cookie in cookies}
        return cookie_dict.get("LOGIN_STATUS") == "1" or bool(cookie_dict.get("passport_csrf_token"))

    async def update_cookies(self, browser_context: BrowserContext):
        cookies = await browser_context.cookies()
        cookie_dict = {cookie["name"]: cookie["value"] for cookie in cookies}
        self.cookie_dict = cookie_dict
        self.headers["Cookie"] = "; ".join(f"{key}={value}" for key, value in cookie_dict.items())

    async def search_info_by_keyword(
        self,
        keyword: str,
        offset: int = 0,
        search_id: str = "",
    ) -> Dict[str, Any]:
        params = {
            "search_channel": "aweme_general",
            "enable_history": "1",
            "keyword": keyword,
            "search_source": "tab_search",
            "query_correct_type": "1",
            "is_filter_search": "0",
            "from_group_id": "",
            "offset": offset,
            "count": 15,
            "need_filter_settings": "1",
            "list_type": "multi",
            "search_id": search_id,
        }
        referer_url = f"https://www.douyin.com/search/{urllib.parse.quote(keyword)}?type=general"
        headers = copy.copy(self.headers)
        headers["Referer"] = referer_url
        return await self.get("/aweme/v1/web/general/search/single/", params, headers=headers)

    async def get_video_by_id(self, aweme_id: str) -> Dict[str, Any]:
        headers = copy.copy(self.headers)
        headers.pop("Origin", None)
        result = await self.get(
            "/aweme/v1/web/aweme/detail/",
            {"aweme_id": aweme_id},
            headers=headers,
        )
        return result.get("aweme_detail", {})

    async def get_aweme_comments(self, aweme_id: str, cursor: int = 0) -> Dict[str, Any]:
        return await self.get(
            "/aweme/v1/web/comment/list/",
            {"aweme_id": aweme_id, "cursor": cursor, "count": 20, "item_type": 0},
        )

    async def get_sub_comments(self, aweme_id: str, comment_id: str, cursor: int = 0) -> Dict[str, Any]:
        return await self.get(
            "/aweme/v1/web/comment/list/reply/",
            {
                "comment_id": comment_id,
                "cursor": cursor,
                "count": 20,
                "item_type": 0,
                "item_id": aweme_id,
            },
        )

    async def get_aweme_all_comments(
        self,
        aweme_id: str,
        crawl_interval: float = 1.0,
        is_fetch_sub_comments: bool = False,
        max_count: int = 100,
    ) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        has_more = 1
        cursor = 0

        while has_more and len(result) < max_count:
            comments_res = await self.get_aweme_comments(aweme_id, cursor)
            has_more = comments_res.get("has_more", 0)
            cursor = comments_res.get("cursor", 0)
            comments = comments_res.get("comments", []) or []

            if not comments:
                break

            if len(result) + len(comments) > max_count:
                comments = comments[: max_count - len(result)]
            result.extend(comments)

            if is_fetch_sub_comments:
                for comment in comments:
                    if len(result) >= max_count:
                        break
                    reply_total = comment.get("reply_comment_total", 0) or 0
                    if reply_total <= 0:
                        continue
                    sub_cursor = 0
                    sub_has_more = 1
                    while sub_has_more and len(result) < max_count:
                        sub_res = await self.get_sub_comments(aweme_id, str(comment.get("cid")), sub_cursor)
                        sub_has_more = sub_res.get("has_more", 0)
                        sub_cursor = sub_res.get("cursor", 0)
                        sub_comments = sub_res.get("comments", []) or []
                        if not sub_comments:
                            break
                        if len(result) + len(sub_comments) > max_count:
                            sub_comments = sub_comments[: max_count - len(result)]
                        result.extend(sub_comments)

            if crawl_interval > 0:
                import asyncio

                await asyncio.sleep(crawl_interval)

        return result
