import asyncio
import logging
import random
from typing import Dict, List, Optional

from playwright.async_api import Browser, BrowserContext, Page

from .client import DouyinClient

logger = logging.getLogger(__name__)


class DouyinCrawler:
    def __init__(self, browser: Browser):
        self.browser = browser
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.client: Optional[DouyinClient] = None
        self.index_url = "https://www.douyin.com"

    async def init_client(self):
        if not self.context:
            user_agent = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            )
            self.context = await self.browser.new_context(user_agent=user_agent, locale="zh-CN")

        if not self.page:
            self.page = await self.context.new_page()

        try:
            await self.page.goto(self.index_url, wait_until="domcontentloaded")
            await self.page.wait_for_timeout(3000)
        except Exception as exc:
            logger.warning(f"Failed to navigate to Douyin index page: {exc}")

        cookies = await self.context.cookies()
        cookie_dict = {cookie["name"]: cookie["value"] for cookie in cookies}
        cookie_str = "; ".join(f"{name}={value}" for name, value in cookie_dict.items())

        headers = {
            "User-Agent": await self.page.evaluate("() => navigator.userAgent"),
            "Cookie": cookie_str,
            "Host": "www.douyin.com",
            "Origin": "https://www.douyin.com",
            "Referer": "https://www.douyin.com/",
            "Content-Type": "application/json;charset=UTF-8",
        }

        self.client = DouyinClient(
            headers=headers,
            playwright_page=self.page,
            cookie_dict=cookie_dict,
        )

    async def search_posts(self, keyword: str, count: int = 100) -> List[Dict]:
        if not self.client:
            await self.init_client()

        logger.info(f"Searching Douyin posts for keyword: {keyword}")
        all_posts: List[Dict] = []
        page = 0
        search_id = ""
        page_size = 15

        while len(all_posts) < count:
            try:
                result = await self.client.search_info_by_keyword(
                    keyword=keyword,
                    offset=page * page_size,
                    search_id=search_id,
                )
                search_id = (result.get("extra") or {}).get("logid", "")
                items = result.get("data") or []
                if not items:
                    break

                page_added = 0
                for item in items:
                    aweme = item.get("aweme_info")
                    if not aweme:
                        mix_info = item.get("aweme_mix_info") or {}
                        mix_items = mix_info.get("mix_items") or []
                        aweme = mix_items[0] if mix_items else None
                    if not aweme:
                        continue

                    parsed = self._parse_aweme(aweme)
                    if parsed:
                        all_posts.append(parsed)
                        page_added += 1
                        if len(all_posts) >= count:
                            break

                logger.info(
                    f"Douyin page {page}: found {len(items)} raw items, added {page_added} posts, total {len(all_posts)}"
                )
                if page_added == 0:
                    break

                page += 1
                await asyncio.sleep(random.uniform(1.0, 2.0))
            except Exception as exc:
                logger.error(f"Error searching Douyin posts at page {page}: {exc}")
                break

        return all_posts[:count]

    def _parse_aweme(self, aweme: Dict) -> Optional[Dict]:
        try:
            author = aweme.get("author") or {}
            stats = aweme.get("statistics") or {}
            desc = (aweme.get("desc") or "").strip()
            return {
                "id": str(aweme.get("aweme_id")),
                "content": desc,
                "author": author.get("nickname", ""),
                "post_time": str(aweme.get("create_time", "")),
                "likes": stats.get("digg_count", 0),
                "comments": stats.get("comment_count", 0),
                "shares": stats.get("share_count", 0),
                "views": stats.get("play_count", 0),
                "platform": "douyin",
                "raw_data": aweme,
            }
        except Exception as exc:
            logger.warning(f"Failed to parse Douyin aweme: {exc}")
            return None

    async def get_comments(self, post_id: str, count: int = 1000) -> List[Dict]:
        if not self.client:
            await self.init_client()

        logger.info(f"Getting Douyin comments for post {post_id}")
        raw_comments = await self.client.get_aweme_all_comments(
            aweme_id=post_id,
            crawl_interval=0.8,
            is_fetch_sub_comments=True,
            max_count=count,
        )
        parsed_comments: List[Dict] = []
        for comment in raw_comments:
            parsed = self._parse_comment(comment, post_id)
            if parsed:
                parsed_comments.append(parsed)
        return parsed_comments

    def _parse_comment(self, comment: Dict, post_id: str) -> Optional[Dict]:
        try:
            user = comment.get("user") or {}
            text = (comment.get("text") or "").strip()
            if not text:
                return None

            return {
                "id": str(comment.get("cid")),
                "post_id": post_id,
                "content": text,
                "author": user.get("nickname", ""),
                "comment_time": str(comment.get("create_time", "")),
                "likes": comment.get("digg_count", 0),
                "platform": "douyin",
            }
        except Exception as exc:
            logger.warning(f"Failed to parse Douyin comment: {exc}")
            return None
