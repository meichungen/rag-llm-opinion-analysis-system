import asyncio
import logging
import os
import re
from typing import Dict, List, Optional
from urllib.parse import quote

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from .client import WeiboClient
from .exception import DataFetchError

logger = logging.getLogger(__name__)

class WeiboCrawler:
    def __init__(self, browser: Browser):
        self.browser = browser
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.client: Optional[WeiboClient] = None
        self.mobile_index_url = "https://m.weibo.cn"

    async def init_client(self):
        """Initialize the WeiboClient with cookies from the browser context"""
        if not self.context:
            # Create a context with mobile user agent
            ua = 'Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.91 Mobile Safari/537.36'
            self.context = await self.browser.new_context(
                user_agent=ua,
                viewport={'width': 375, 'height': 812},
                locale='zh-CN'
            )
        
        if not self.page:
            self.page = await self.context.new_page()

        # Navigate to mobile site to ensure cookies are set/retrieved for the right domain
        try:
            await self.page.goto(self.mobile_index_url, wait_until='domcontentloaded')
            # If we have a cookie file, we might want to load it here.
            # But SocialMediaCrawler handles loading cookies into the context before creating WeiboCrawler?
            # No, SocialMediaCrawler calls `load_cookies` and `add_cookies` to the context *before* passing browser to crawler?
            # Actually SocialMediaCrawler passes `browser` to `WeiboCrawler`.
            # SocialMediaCrawler creates context and adds cookies, then sets `crawler.context = context`.
            # So we should use the context provided by SocialMediaCrawler if available.
            pass
        except Exception as e:
            logger.warning(f"Failed to navigate to mobile index: {e}")

        # 只提取移动站 Cookie，避免桌面端和移动端 Cookie 混用导致接口判定未登录。
        cookies = await self.context.cookies(urls=[self.mobile_index_url])
        cookie_str = ""
        cookie_dict = {}
        for cookie in cookies:
            cookie_str += f"{cookie['name']}={cookie['value']}; "
            cookie_dict[cookie['name']] = cookie['value']

        headers = {
            "User-Agent": 'Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.91 Mobile Safari/537.36',
            "Cookie": cookie_str.strip("; "),
            "Origin": "https://m.weibo.cn",
            "Referer": "https://m.weibo.cn",
            "Content-Type": "application/json;charset=UTF-8",
            "Accept": "application/json, text/plain, */*",
            "MWeibo-Pwa": "1",
            "X-Requested-With": "XMLHttpRequest"
        }

        self.client = WeiboClient(
            headers=headers,
            playwright_page=self.page,
            cookie_dict=cookie_dict
        )

        if not await self.client.pong():
            # 某些用户上传的是 www.weibo.com Cookie，需要先在 PC 站落库，再跳转移动站换取有效移动 Cookie。
            try:
                await self.page.goto("https://www.weibo.com", wait_until='domcontentloaded')
                await asyncio.sleep(2)
                await self.page.goto(self.mobile_index_url, wait_until='domcontentloaded')
                await asyncio.sleep(2)
                await self.client.update_cookies(self.context, urls=[self.mobile_index_url])
            except Exception as exc:
                logger.warning(f"Failed to refresh mobile weibo cookies: {exc}")

            if not await self.client.pong():
                raise DataFetchError("微博移动端登录态无效，请重新更新微博 Cookie（建议从 m.weibo.cn 或登录后刷新页面获取）")

    async def search_posts(self, keyword: str, count: int = 100) -> List[Dict]:
        if not self.client:
            await self.init_client()

        logger.info(f"Searching Weibo posts for keyword: {keyword}")
        
        all_posts = []
        page = 1
        
        while len(all_posts) < count:
            try:
                result = await self.client.get_note_by_keyword(keyword, page=page)
                cards = result.get("cards", [])
                
                if not cards:
                    logger.info(f"No more cards found at page {page}")
                    break
                
                found_new = False
                for card in cards:
                    # card_type 9 is usually the post
                    if card.get("card_type") == 9:
                        mblog = card.get("mblog")
                        if mblog:
                            if mblog.get("isLongText") and mblog.get("id"):
                                detail = await self.client.get_note_info_by_id(str(mblog["id"]))
                                mblog = detail.get("mblog", mblog)
                            post_data = self._parse_mblog(mblog)
                            if post_data:
                                all_posts.append(post_data)
                                found_new = True
                    # Sometimes posts are in card_group
                    elif card.get("card_group"):
                        for group_card in card.get("card_group"):
                            if group_card.get("card_type") == 9:
                                mblog = group_card.get("mblog")
                                if mblog:
                                    if mblog.get("isLongText") and mblog.get("id"):
                                        detail = await self.client.get_note_info_by_id(str(mblog["id"]))
                                        mblog = detail.get("mblog", mblog)
                                    post_data = self._parse_mblog(mblog)
                                    if post_data:
                                        all_posts.append(post_data)
                                        found_new = True
                
                if not found_new:
                     logger.info(f"No valid posts found at page {page}")
                     # Try one more page just in case
                     if page > 5: # limit retries
                         break

                if len(all_posts) >= count:
                    break
                
                page += 1
                await asyncio.sleep(1) # Sleep to avoid rate limit
                
            except Exception as e:
                logger.error(f"Error searching posts at page {page}: {e}")
                break
                
        return all_posts[:count]

    def _parse_mblog(self, mblog: Dict) -> Optional[Dict]:
        """Parse mblog dictionary to Post format"""
        try:
            user = mblog.get("user", {})
            content = mblog.get("text", "")
            if content:
                content = re.sub(r'<[^>]+>', '', content)
            
            return {
                'id': str(mblog.get("id")),
                'content': content,
                'author': user.get("screen_name", ""),
                'post_time': mblog.get("created_at", ""), # Needs parsing
                'likes': mblog.get("attitudes_count", 0),
                'comments': mblog.get("comments_count", 0),
                'shares': mblog.get("reposts_count", 0),
                'platform': 'weibo',
                'raw_data': mblog # Store raw data if needed
            }
        except Exception as e:
            logger.warning(f"Failed to parse mblog: {e}")
            return None

    async def get_comments(self, post_id: str, count: int = 1000) -> List[Dict]:
        if not self.client:
            await self.init_client()
            
        logger.info(f"Getting comments for post {post_id}")
        
        raw_comments = await self.client.get_note_all_comments(post_id, max_count=count)
        parsed_comments = []
        
        for comment in raw_comments:
            try:
                parsed = self._parse_comment(comment, post_id)
                if parsed:
                    parsed_comments.append(parsed)
            except Exception as e:
                logger.warning(f"Failed to parse comment: {e}")
                
        return parsed_comments

    def _parse_comment(self, comment: Dict, post_id: str) -> Optional[Dict]:
        try:
            user = comment.get("user", {})
            content = comment.get("text", "")
            if content:
                content = re.sub(r'<[^>]+>', '', content)
                
            return {
                'id': str(comment.get("id")),
                'post_id': post_id,
                'content': content,
                'author': user.get("screen_name", ""),
                'comment_time': comment.get("created_at", ""),
                'likes': comment.get("like_count", 0),
                'platform': 'weibo'
            }
        except Exception as e:
            logger.warning(f"Failed to parse comment: {e}")
            return None
