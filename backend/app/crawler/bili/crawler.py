import asyncio
import logging
import os
import json
import random
import re
from typing import Dict, List, Optional
from urllib.parse import quote

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from .client import BilibiliClient
from .exception import DataFetchError

logger = logging.getLogger(__name__)

class BilibiliCrawler:
    def __init__(self, browser: Browser, config: Optional[Dict] = None):
        self.browser = browser
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.client: Optional[BilibiliClient] = None
        self.index_url = "https://www.bilibili.com"
        self.config = config or {}

    async def init_client(self):
        """Initialize the BilibiliClient with cookies from the browser context"""
        if not self.context:
            ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            self.context = await self.browser.new_context(
                user_agent=ua,
                locale='zh-CN'
            )
        
        if not self.page:
            self.page = await self.context.new_page()

        try:
            await self.page.goto(self.index_url, wait_until='domcontentloaded')
        except Exception as e:
            logger.warning(f"Failed to navigate to index: {e}")

        # Get cookies from context
        cookies = await self.context.cookies()
        if not cookies:
            logger.warning("No cookies found in context! Crawler might fail or get limited results.")
        
        cookie_str = ""
        cookie_dict = {}
        for cookie in cookies:
            cookie_str += f"{cookie['name']}={cookie['value']}; "
            cookie_dict[cookie['name']] = cookie['value']

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Cookie": cookie_str.strip("; "),
            "Referer": "https://www.bilibili.com/",
            "Origin": "https://www.bilibili.com"
        }

        self.client = BilibiliClient(
            headers=headers,
            playwright_page=self.page,
            cookie_dict=cookie_dict,
            request_retry_attempts=int(self.config.get("request_retry_attempts", 5)),
            enable_unsigned_search_fallback=bool(self.config.get("enable_unsigned_search_fallback", True)),
        )

    async def search_posts(self, keyword: str, count: int = 100) -> List[Dict]:
        if not self.client:
            await self.init_client()

        logger.info(f"Searching Bilibili videos for keyword: {keyword}")
        
        all_posts = []
        page = 1
        page_size = 20 # B站通常一页20条
        max_pages = max(
            1,
            int(self.config.get("max_search_pages", max(3, (count + page_size - 1) // page_size + 2))),
        )
        
        while len(all_posts) < count and page <= max_pages:
            try:
                search_retry_attempts = max(1, int(self.config.get("search_retry_attempts", 1)))
                last_error = None
                result = None
                for _ in range(search_retry_attempts):
                    try:
                        result = await self.client.search_video_by_keyword(keyword, page=page, page_size=page_size)
                        break
                    except Exception as exc:
                        last_error = exc
                        await asyncio.sleep(random.uniform(0.5, 1.5))
                if result is None and last_error is not None:
                    raise last_error
                
                # Bilibili search API returns 'result' field in 'data'
                items = []
                if "result" in result:
                    res_data = result["result"]
                    if isinstance(res_data, list):
                        # Filter only video items if there are other types
                        items = [i for i in res_data if i.get("type") == "video" or "bvid" in i]
                    elif isinstance(res_data, dict):
                        # Sometimes it's nested
                        items = res_data.get("video", []) or res_data.get("result", [])
                
                if not items:
                    logger.info(f"No items found at page {page}. Result keys: {list(result.keys()) if isinstance(result, dict) else 'not a dict'}")
                    if page > 1 and page < 5: # limit retry logic
                        logger.info("Trying next page just in case...")
                        page += 1
                        await asyncio.sleep(random.uniform(2, 3))
                        continue
                    break
                
                page_items_added = 0
                for item in items:
                    post_data = self._parse_video(item)
                    if post_data:
                        all_posts.append(post_data)
                        page_items_added += 1
                        if len(all_posts) >= count:
                            break
                
                logger.info(f"Page {page}: Found {len(items)} items, Added {page_items_added} valid posts. Total: {len(all_posts)}")

                if len(all_posts) >= count:
                    break
                
                if page_items_added == 0 and len(items) > 0:
                    logger.warning(f"Page {page} had {len(items)} items but none were valid posts.")

                page += 1
                await asyncio.sleep(random.uniform(2, 4)) # Increase sleep to avoid rate limit
                
            except Exception as e:
                logger.error(f"Error searching videos at page {page}: {e}")
                # Continue to next page instead of breaking
                page += 1
                await asyncio.sleep(random.uniform(3, 5))
                continue

        if page > max_pages and len(all_posts) < count:
            logger.warning(
                f"Stopped Bilibili search after reaching max_pages={max_pages}, collected {len(all_posts)} posts"
            )

        return all_posts[:count]

    def _parse_video(self, item: Dict) -> Optional[Dict]:
        """Parse video item to Post format"""
        try:
            # Clean HTML tags from title and description
            title = item.get("title", "")
            description = item.get("description", "")
            if title:
                title = re.sub(r'<[^>]+>', '', title)
            if description:
                description = re.sub(r'<[^>]+>', '', description)

            # item 结构通常包含 title, description, pic, arcurl, bvid, aid, play, video_review (弹幕), pubdate
            return {
                'id': str(item.get("bvid")), # 使用 bvid 作为唯一标识
                'content': title + "\n" + description,
                'author': item.get("author", ""),
                'post_time': str(item.get("pubdate", "")), # timestamp
                'likes': 0, # 搜索接口可能不直接返回点赞数，或者在 stat 字段里
                'comments': item.get("review", 0), # 评论数
                'shares': item.get("favorites", 0), # 映射收藏数为分享数，或者 favorites
                'views': item.get("play", 0), # 播放量
                'platform': 'bilibili',
                'raw_data': item,
                'extra': {'aid': item.get("aid")} # 保存 aid 用于获取评论
            }
        except Exception as e:
            logger.warning(f"Failed to parse video item: {e}")
            return None

    async def get_comments(self, post_id: str, count: int = 1000) -> List[Dict]:
        if not self.client:
            await self.init_client()

        logger.info(f"Getting comments for video {post_id}, target count: {count}")

        aid = await self._get_aid_by_bvid(post_id)
        if not aid:
            logger.warning(f"Could not find aid for bvid {post_id}")
            return []

        all_comments = []
        next_page = 0
        page_count = 0
        max_pages = 100
        max_pages = max(1, int(self.config.get("max_comment_pages", max_pages)))
        modes_to_try = [3, 2, 1]
        current_mode_index = 0
        mode = modes_to_try[current_mode_index]

        while len(all_comments) < count and page_count < max_pages:
            try:
                page_count += 1
                logger.info(f"Fetching comment page {page_count} for video {post_id}, current count: {len(all_comments)}, mode={mode}")

                comment_retry_attempts = max(1, int(self.config.get("comment_retry_attempts", 1)))
                last_error = None
                res = None
                for _ in range(comment_retry_attempts):
                    try:
                        res = await self.get_video_comments_by_mode(str(aid), next_page=next_page, mode=mode)
                        break
                    except Exception as exc:
                        last_error = exc
                        await asyncio.sleep(random.uniform(0.5, 1.5))
                if res is None and last_error is not None:
                    raise last_error
                cursor = res.get("cursor", {})
                replies = res.get("replies", [])

                if not replies:
                    logger.info(f"No replies in mode {mode} for video {post_id}, trying different mode")
                    current_mode_index += 1
                    if current_mode_index < len(modes_to_try):
                        mode = modes_to_try[current_mode_index]
                        next_page = 0
                        page_count = 0
                        logger.info(f"Switching to mode {mode} for video {post_id}")
                        continue
                    logger.info(f"No more modes to try for video {post_id}, breaking (fetched {len(all_comments)} comments)")
                    break

                for reply in replies:
                    parsed = self._parse_comment(reply, post_id)
                    if parsed:
                        all_comments.append(parsed)
                        if len(all_comments) >= count:
                            break

                if len(all_comments) >= count:
                    break

                is_end = cursor.get("is_end", False)
                next_page = cursor.get("next", 0)

                logger.debug(f"Cursor info for {post_id}: next={next_page}, is_end={is_end}")

                if next_page == 0:
                    if len(all_comments) < 5 and current_mode_index < len(modes_to_try) - 1:
                        current_mode_index += 1
                        mode = modes_to_try[current_mode_index]
                        next_page = 0
                        page_count = 0
                        logger.info(f"Only got {len(all_comments)} comments, switching to mode {mode}")
                        await asyncio.sleep(random.uniform(0.5, 1.5))
                        continue
                    logger.info(f"End of comments for video {post_id}: next=0, no more pages")
                    break

                await asyncio.sleep(random.uniform(0.5, 1.5))

            except Exception as e:
                logger.error(f"Error getting comments for {post_id} at page {page_count}: {e}")
                break

        logger.info(f"Finished getting comments for video {post_id}: total {len(all_comments)} comments from {page_count} pages")
        return all_comments[:count]

    async def get_video_comments_by_mode(
        self,
        video_id: str,
        next_page: int = 0,
        mode: int = 3,
    ) -> Dict:
        params = {"oid": video_id, "mode": mode, "type": 1, "ps": 20, "next": next_page}
        try:
            return await self.client.get("/x/v2/reply/wbi/main", params, enable_params_sign=True)
        except DataFetchError as exc:
            if not bool(self.config.get("enable_unsigned_comment_fallback", True)):
                raise
            logger.warning(
                f"WBI comments request failed for oid={video_id}, mode={mode}, fallback to unsigned API: {exc}"
            )
            return await self.client.get("/x/v2/reply/main", params, enable_params_sign=False)

    async def _get_aid_by_bvid(self, bvid: str) -> Optional[int]:
        try:
            info = await self.client.get_video_info(bvid)
            if 'View' in info:
                return info['View'].get("aid")
            return info.get("aid")
        except Exception as e:
            logger.error(f"Failed to get video info for {bvid}: {e}")
            return None

    def _parse_comment(self, comment: Dict, post_id: str) -> Optional[Dict]:
        try:
            member = comment.get("member", {})
            content = comment.get("content", {})
            return {
                'id': str(comment.get("rpid")),
                'post_id': post_id,
                'content': content.get("message", ""),
                'author': member.get("uname", ""),
                'comment_time': str(comment.get("ctime", "")),
                'likes': comment.get("like", 0),
                'platform': 'bilibili'
            }
        except Exception as e:
            logger.warning(f"Failed to parse comment: {e}")
            return None
