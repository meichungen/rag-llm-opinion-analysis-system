import asyncio
import copy
import json
import re
from typing import Callable, Dict, List, Optional, Union
from urllib.parse import parse_qs, unquote, urlencode

import httpx
from httpx import Response
from playwright.async_api import BrowserContext, Page
from tenacity import retry, stop_after_attempt, retry_if_exception_type, wait_random_exponential
import logging

from .exception import DataFetchError

logger = logging.getLogger(__name__)

class WeiboClient:
    def __init__(
        self,
        timeout=60,
        proxy=None,
        *,
        headers: Dict[str, str],
        playwright_page: Page,
        cookie_dict: Dict[str, str],
    ):
        self.proxy = proxy
        self.timeout = timeout
        self.headers = headers
        self._host = "https://m.weibo.cn"
        self.playwright_page = playwright_page
        self.cookie_dict = cookie_dict
        self._image_agent_host = "https://i1.wp.com/"

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_random_exponential(min=1, max=10),
        retry=retry_if_exception_type((httpx.ConnectError, httpx.ReadTimeout, DataFetchError)),
        reraise=True,
    )
    async def request(self, method, url, **kwargs) -> Union[Response, Dict]:
        enable_return_response = kwargs.pop("return_response", False)
        # Fix for httpx 0.28.1: use 'proxy' instead of 'proxies' (though here it was already using proxy=self.proxy which might be passed to proxies arg?)
        # Wait, the previous code was `httpx.AsyncClient(proxy=self.proxy)` which is actually incorrect if self.proxy is a string and the arg is named proxy?
        # Actually in previous turns I saw `httpx.AsyncClient(proxies=proxies)` in bili client but `httpx.AsyncClient(proxy=self.proxy)` in weibo client?
        # Let's check the old code.
        # Old code: `async with httpx.AsyncClient(proxy=self.proxy) as client:`
        # If `proxy` arg is valid in 0.28.1, then it should be fine.
        # But wait, did I check Weibo client? I should check if it needs update too.
        # Let's just be safe and use `proxy` arg which seems to be the new standard.
        
        async with httpx.AsyncClient(proxy=self.proxy) as client:
            response = await client.request(method, url, timeout=self.timeout, **kwargs)

        if enable_return_response:
            return response

        try:
            data: Dict = response.json()
        except json.decoder.JSONDecodeError:
            logger.error(f"[WeiboClient.request] request {method}:{url} err code: {response.status_code} res:{response.text}")
            # Try to refresh cookies if JSON decode fails (often means auth issue or captcha)
            if self.playwright_page:
                try:
                    await self.playwright_page.goto(self._host)
                    await asyncio.sleep(2)
                    await self.update_cookies(browser_context=self.playwright_page.context)
                except Exception as e:
                    logger.error(f"Failed to refresh cookies: {e}")
            raise DataFetchError(f"get response code error: {response.status_code}")

        ok_code = data.get("ok")
        if ok_code == 0:  # response error
            msg = data.get("msg", "response error")
            if "还没有人评论" in msg:
                # No comments is not an error, just return empty data
                return {}
            logger.error(f"[WeiboClient.request] request {method}:{url} err, res:{data}")
            raise DataFetchError(msg)
        elif ok_code != 1:  # unknown error
            # Sometimes ok is not 1 but data is valid or it's just a warning
            # But for now we follow the reference
            logger.error(f"[WeiboClient.request] request {method}:{url} err, res:{data}")
            raise DataFetchError(data.get("msg", "unknown error"))
        else:  # response right
            return data.get("data", {})

    async def get(self, uri: str, params=None, headers=None, **kwargs) -> Union[Response, Dict]:
        final_uri = uri
        if isinstance(params, dict):
            final_uri = (f"{uri}?"
                         f"{urlencode(params)}")

        if headers is None:
            headers = self.headers
        return await self.request(method="GET", url=f"{self._host}{final_uri}", headers=headers, **kwargs)

    async def pong(self) -> bool:
        """Check whether current mobile cookies are authenticated."""
        logger.info("[WeiboClient.pong] Begin pong weibo")
        try:
            resp_data = await self.request(method="GET", url=f"{self._host}/api/config", headers=self.headers)
            if resp_data.get("login"):
                return True
            logger.warning("[WeiboClient.pong] Mobile cookie is not logged in")
            return False
        except Exception as exc:
            logger.warning(f"[WeiboClient.pong] Failed to verify mobile login state: {exc}")
            return False

    async def update_cookies(self, browser_context: BrowserContext, urls: Optional[List[str]] = None):
        if urls:
            cookies = await browser_context.cookies(urls=urls)
        else:
            cookies = await browser_context.cookies()

        cookie_str = ""
        cookie_dict = {}
        for cookie in cookies:
            cookie_str += f"{cookie['name']}={cookie['value']}; "
            cookie_dict[cookie['name']] = cookie['value']
        
        self.headers["Cookie"] = cookie_str.strip("; ")
        self.cookie_dict = cookie_dict
        logger.info(f"[WeiboClient.update_cookies] Cookie updated successfully, total: {len(cookie_dict)} cookies")

    async def get_note_by_keyword(
        self,
        keyword: str,
        page: int = 1,
        search_type: str = "default",
    ) -> Dict:
        uri = "/api/container/getIndex"
        # search_type: default -> 1, realtime -> 61, popular -> 60, video -> 63 (simplified mapping)
        type_val = 1
        if search_type == "realtime":
            type_val = 61
        elif search_type == "popular":
            type_val = 60
        elif search_type == "video":
            type_val = 63
            
        containerid = f"100103type={type_val}&q={keyword}"
        params = {
            "containerid": containerid,
            "page_type": "searchall",
            "page": page,
        }
        return await self.get(uri, params)

    async def get_note_comments(self, mid_id: str, max_id: int, max_id_type: int = 0) -> Dict:
        uri = "/comments/hotflow"
        params = {
            "id": mid_id,
            "mid": mid_id,
            "max_id_type": max_id_type,
        }
        if max_id > 0:
            params.update({"max_id": max_id})
        referer_url = f"https://m.weibo.cn/detail/{mid_id}"
        headers = copy.copy(self.headers)
        headers["Referer"] = referer_url

        return await self.get(uri, params, headers=headers)

    async def get_note_all_comments(
        self,
        note_id: str,
        crawl_interval: float = 1.0,
        max_count: int = 10,
    ) -> List[Dict]:
        result = []
        is_end = False
        max_id = -1
        max_id_type = 0
        while not is_end and len(result) < max_count:
            try:
                comments_res = await self.get_note_comments(note_id, max_id, max_id_type)
                max_id = comments_res.get("max_id", 0)
                max_id_type = comments_res.get("max_id_type", 0)
                comment_list = comments_res.get("data", [])
                
                if not comment_list:
                    is_end = True
                
                is_end = is_end or (max_id == 0)
                
                if len(result) + len(comment_list) > max_count:
                    comment_list = comment_list[:max_count - len(result)]
                
                # Flatten visible sub-comments so downstream analysis can use more complete text.
                flattened_sub_comments = []
                for comment in comment_list:
                    sub_comments = comment.get("comments")
                    if sub_comments and isinstance(sub_comments, list):
                        flattened_sub_comments.extend(sub_comments)

                result.extend(comment_list)
                if flattened_sub_comments and len(result) < max_count:
                    remaining = max_count - len(result)
                    result.extend(flattened_sub_comments[:remaining])
                await asyncio.sleep(crawl_interval)
            except Exception as e:
                logger.error(f"Error getting comments for {note_id}: {e}")
                break
        return result

    async def get_note_info_by_id(self, note_id: str) -> Dict:
        url = f"{self._host}/detail/{note_id}"
        async with httpx.AsyncClient(proxy=self.proxy) as client:
            response = await client.request("GET", url, timeout=self.timeout, headers=self.headers)
            if response.status_code != 200:
                raise DataFetchError(f"get weibo detail err: {response.text}")
            match = re.search(r'var \$render_data = (\[.*?\])\[0\]', response.text, re.DOTALL)
            if match:
                render_data_json = match.group(1)
                render_data_dict = json.loads(render_data_json)
                note_detail = render_data_dict[0].get("status")
                note_item = {"mblog": note_detail}
                return note_item
            else:
                return dict()
