import asyncio
import json
import random
from typing import Any, Dict, Tuple
from urllib.parse import urlencode
import time
import httpx
from playwright.async_api import Page
import logging

from .exception import DataFetchError
from .help import BilibiliSign

logger = logging.getLogger(__name__)

class BilibiliClient:
    def __init__(
        self,
        timeout=60,
        proxy=None,
        *,
        headers: Dict[str, str],
        playwright_page: Page,
        cookie_dict: Dict[str, str],
        request_retry_attempts: int = 5,
        enable_unsigned_search_fallback: bool = True,
    ):
        self.proxy = proxy
        self.timeout = timeout
        self.headers = headers
        self._host = "https://api.bilibili.com"
        self.playwright_page = playwright_page
        self.cookie_dict = cookie_dict
        self._wbi_keys_cache: Tuple[str, str] | None = None
        self.request_retry_attempts = max(1, int(request_retry_attempts))
        self.enable_unsigned_search_fallback = enable_unsigned_search_fallback

    @staticmethod
    def _classify_response_text(response_text: str) -> tuple[str, str] | None:
        text = response_text or ""
        lower_text = text.lower()
        if "错误号: 412" in text or "security control policy" in lower_text:
            return "bilibili_412", "Bilibili 请求触发 412 风控拦截"
        if "captcha" in lower_text or "验证" in text:
            return "captcha", "Bilibili 请求命中验证码校验"
        return None

    async def request(self, method, url, **kwargs) -> Any:
        last_error: Exception | None = None
        proxy = self.proxy or None
        for attempt in range(1, self.request_retry_attempts + 1):
            try:
                async with httpx.AsyncClient(proxy=proxy) as client:
                    response = await client.request(method, url, timeout=self.timeout, **kwargs)
                try:
                    data: Dict = response.json()
                except json.JSONDecodeError:
                    fingerprint = self._classify_response_text(response.text)
                    if fingerprint:
                        raise DataFetchError(
                            fingerprint[1],
                            fingerprint=fingerprint[0],
                            details={"status_code": response.status_code},
                        )
                    logger.error(
                        f"[BilibiliClient.request] Failed to decode JSON from response. "
                        f"status_code: {response.status_code}, response_text: {response.text[:500]}"
                    )
                    raise DataFetchError("Bilibili 接口返回了非 JSON 内容", fingerprint="empty_json")
                if data.get("code") != 0:
                    code = data.get("code")
                    message = data.get("message", "unknown error")
                    logger.error(f"[BilibiliClient.request] API Error: code={code} message={message}")
                    if code == -101:
                        raise DataFetchError("Bilibili 账号未登录或登录态失效", fingerprint="login_required")
                    raise DataFetchError(message)
                return data.get("data", {})
            except (httpx.ConnectError, httpx.ReadTimeout, DataFetchError) as exc:
                last_error = exc
                logger.warning(
                    "Bilibili request attempt %s/%s failed: %s %s error=%s",
                    attempt,
                    self.request_retry_attempts,
                    method,
                    url,
                    exc,
                )
                if attempt >= self.request_retry_attempts:
                    raise exc
                await asyncio.sleep(min(2 ** (attempt - 1) + random.random(), 10))
            except Exception as e:
                logger.error(f"Request failed: {method} {url} kwargs={kwargs.keys()} error: {e}")
                raise e
        if last_error:
            raise last_error
        raise DataFetchError("Bilibili 请求失败")

    async def pre_request_data(self, req_data: Dict) -> Dict:
        """
        发送请求进行请求参数签名
        """
        if not req_data:
            req_data = {}
        img_key, sub_key = await self.get_wbi_keys()
        return BilibiliSign(img_key, sub_key).sign(req_data)

    async def get_wbi_keys(self) -> Tuple[str, str]:
        """
        获取最新的 img_key 和 sub_key
        """
        if self._wbi_keys_cache:
            return self._wbi_keys_cache

        # 尝试从 localStorage 获取
        try:
            local_storage = await self.playwright_page.evaluate("() => window.localStorage")
            wbi_img_urls = local_storage.get("wbi_img_urls", "")
            if not wbi_img_urls:
                img_url_from_storage = local_storage.get("wbi_img_url")
                sub_url_from_storage = local_storage.get("wbi_sub_url")
                if img_url_from_storage and sub_url_from_storage:
                    wbi_img_urls = f"{img_url_from_storage}-{sub_url_from_storage}"
            
            if wbi_img_urls and "-" in wbi_img_urls:
                img_url, sub_url = wbi_img_urls.split("-")
                img_key = img_url.rsplit('/', 1)[1].split('.')[0]
                sub_key = sub_url.rsplit('/', 1)[1].split('.')[0]
                self._wbi_keys_cache = (img_key, sub_key)
                return self._wbi_keys_cache
        except Exception as e:
            logger.warning(f"Failed to get wbi keys from local storage: {e}")

        # 如果失败，请求 nav 接口
        try:
            # 不需要签名
            resp = await self.request(
                method="GET",
                url=self._host + "/x/web-interface/nav",
                headers=self.headers,
            )
            img_url: str = resp['wbi_img']['img_url']
            sub_url: str = resp['wbi_img']['sub_url']
            img_key = img_url.rsplit('/', 1)[1].split('.')[0]
            sub_key = sub_url.rsplit('/', 1)[1].split('.')[0]
            self._wbi_keys_cache = (img_key, sub_key)
            return self._wbi_keys_cache
        except Exception as e:
            logger.error(f"Failed to get wbi keys from nav: {e}")
            # 返回默认值或者抛出异常，这里返回空字符串会导致签名失败
            # 为了保证流程，我们可以硬编码一些旧的 key 或者抛出
            raise DataFetchError("Failed to get wbi keys")

    async def get(self, uri: str, params=None, enable_params_sign: bool = True) -> Dict:
        final_uri = uri
        if enable_params_sign:
            params = await self.pre_request_data(params)
        if isinstance(params, dict):
            final_uri = (f"{uri}?"
                         f"{urlencode(params)}")
        return await self.request(method="GET", url=f"{self._host}{final_uri}", headers=self.headers)

    async def search_video_by_keyword(
        self,
        keyword: str,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict:
        signed_uri = "/x/web-interface/wbi/search/type"
        unsigned_uri = "/x/web-interface/search/type"
        params = {
            "search_type": "video",
            "keyword": keyword,
            "page": page,
            "page_size": page_size,
            "order": "totalrank", # 综合排序
        }
        try:
            return await self.get(signed_uri, params, enable_params_sign=True)
        except DataFetchError as exc:
            if not self.enable_unsigned_search_fallback:
                raise
            logger.warning(f"WBI search failed for page {page}, fallback to unsigned search: {exc}")
            return await self.get(unsigned_uri, params, enable_params_sign=False)

    async def get_video_info(self, bvid: str) -> Dict:
        uri = "/x/web-interface/view/detail"
        params = {"bvid": bvid}
        # 详情接口通常不需要 wbi 签名，但带上也没事，或者参考原代码 enable_params_sign=False
        return await self.get(uri, params, enable_params_sign=False)

    async def get_video_comments(
        self,
        video_id: str, # oid (aid)
        next_page: int = 0,
    ) -> Dict:
        uri = "/x/v2/reply/wbi/main"
        # mode 3: 热度排序, 2: 时间排序? 默认用 3
        params = {"oid": video_id, "mode": 3, "type": 1, "ps": 20, "next": next_page}
        return await self.get(uri, params)
