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
    def __init__(self, browser: Browser):
        self.browser = browser
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.client: Optional[BilibiliClient] = None
        self.index_url = "https://www.bilibili.com"

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
            cookie_dict=cookie_dict
        )

    async def search_posts(self, keyword: str, count: int = 100) -> List[Dict]:
        if not self.client:
            await self.init_client()

        logger.info(f"Searching Bilibili videos for keyword: {keyword}")
        
        all_posts = []
        page = 1
        page_size = 20 # B站通常一页20条
        
        while len(all_posts) < count:
            try:
                result = await self.client.search_video_by_keyword(keyword, page=page, page_size=page_size)
                
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
            
        logger.info(f"Getting comments for video {post_id}")
        
        # post_id is bvid. We need aid (oid) for comments API.
        # Ideally we stored aid in 'extra' or we need to fetch detail to get aid.
        # If post_id is passed directly from search_posts result, we might not have aid easily accessible 
        # if we only pass the dict. 
        # SocialMediaCrawler passes post['id'] which is bvid.
        # So we need to get aid from bvid.
        
        aid = await self._get_aid_by_bvid(post_id)
        if not aid:
            logger.warning(f"Could not find aid for bvid {post_id}")
            return []

        all_comments = []
        next_page = 0
        
        while len(all_comments) < count:
            try:
                res = await self.client.get_video_comments(str(aid), next_page=next_page)
                cursor = res.get("cursor", {})
                replies = res.get("replies", [])
                
                if not replies:
                    break
                    
                for reply in replies:
                    parsed = self._parse_comment(reply, post_id)
                    if parsed:
                        all_comments.append(parsed)
                        if len(all_comments) >= count:
                            break
                
                if len(all_comments) >= count:
                    break

                if cursor.get("is_end"):
                    break
                    
                next_page = cursor.get("next", 0)
                if next_page == 0:
                     break
                     
                await asyncio.sleep(random.uniform(0.5, 1.5))
                
            except Exception as e:
                logger.error(f"Error getting comments for {post_id}: {e}")
                break
                
        return all_comments

    async def _get_aid_by_bvid(self, bvid: str) -> Optional[int]:
        # Try to fetch video info
        try:
            info = await self.client.get_video_info(bvid)
            # The response structure for /x/web-interface/view/detail can be complex
            # Usually it has 'View' or just the data directly
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
