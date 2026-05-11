# 社交媒体爬虫模块
import asyncio
import json
import os
import random
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import logging
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Database imports
from app.core.settings import get_cookie_file_candidates
from sqlalchemy.future import select
from app.core.database import AsyncSessionLocal
from app.models.sql_models import Post, Comment, Task

# Import sub-crawlers
from .weibo import WeiboCrawler
from .bili import BilibiliCrawler
from .douyin import DouyinCrawler
from .zhihu import ZhihuCrawler

from playwright.async_api import async_playwright, Page, Browser, TimeoutError, Error as PlaywrightError

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SocialMediaCrawler:
    """社交媒体爬虫主类"""
    
    def __init__(self):
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.platforms = {
            'weibo': WeiboCrawler,
            'bilibili': BilibiliCrawler,
            'douyin': DouyinCrawler,
            'zhihu': ZhihuCrawler,
        }
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        import os
        import sys
        
        # Ensure correct event loop policy for Windows before starting Playwright
        if sys.platform == 'win32':
             # Playwright requires ProactorEventLoopPolicy on Windows
             # But it should be set at the process level (in main.py/run.py)
             # Here we just verify or log
             pass

        self.playwright = await async_playwright().start()
        proxy_server = os.environ.get('CRAWLER_PROXY') or os.environ.get('HTTP_PROXY') or os.environ.get('ALL_PROXY')
        launch_kwargs = {
            'headless': True,
            'args': ['--no-sandbox', '--disable-dev-shm-usage']
        }
        if proxy_server:
            launch_kwargs['proxy'] = {'server': proxy_server}
            
        # Add timeout to launch to avoid hanging indefinitely
        try:
            self.browser = await self.playwright.chromium.launch(**launch_kwargs)
        except Exception as e:
            logger.error(f"Failed to launch browser: {e}")
            if hasattr(self, 'playwright'):
                await self.playwright.stop()
            raise e
            
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        if self.browser:
            await self.browser.close()
        if hasattr(self, 'playwright'):
            await self.playwright.stop()
    
    async def crawl(self, platform: str, keyword: str, post_count: int = 100, 
                   comment_count: int = 1000, task_id: int = None):
        """主爬取方法"""
        
        if platform not in self.platforms:
            raise ValueError(f"Unsupported platform: {platform}")
        
        crawler_class = self.platforms[platform]
        crawler = crawler_class(self.browser)
        
        # Load cookies
        cookies = await self.load_cookies(platform)
        ua = self._get_user_agent_for_platform(platform)
        context = await self.browser.new_context(
            user_agent=ua,
            locale='zh-CN',
            extra_http_headers={'Accept-Language': 'zh-CN,zh;q=0.9'}
        )
        try:
            context.set_default_timeout(20000)
            context.set_default_navigation_timeout(40000)
        except Exception:
            pass
            
        if cookies:
            try:
                await context.add_cookies(cookies)
            except Exception as e:
                logger.warning(f"Failed to add cookies: {e}")
        
        if hasattr(crawler, 'context'):
            crawler.context = context
            
        crawler.page = await context.new_page()
        
        logger.info(f"Starting crawl for {platform} with keyword: {keyword}")
        await self._update_task_progress(task_id, 5.0, f"开始爬取 {platform} 平台...")
        
        try:
            # 爬取帖子 - 增加重试机制
            @retry(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1, min=2, max=10),
                retry=retry_if_exception_type((TimeoutError, PlaywrightError)),
                reraise=True
            )
            async def fetch_posts():
                return await crawler.search_posts(keyword, post_count)

            posts = await fetch_posts()
            logger.info(f"Found {len(posts)} posts")
            await self._update_task_progress(task_id, 20.0, f"已找到 {len(posts)} 条帖子，准备保存...")
            
            # 保存帖子数据 (Async)
            await self.save_posts(posts, task_id, platform)
            
            # 爬取评论 - 提高并发度
            all_comments = []
            max_concurrent = 10 # 提高并发
            sem = asyncio.Semaphore(max_concurrent) 
            
            async def fetch_comments_safe(post, index):
                async with sem:
                    try:
                        post_id = post['id']
                        # 随机延迟避免被封
                        await asyncio.sleep(random.uniform(0.5, 2.0))
                        
                        # 评论抓取也增加重试
                        @retry(
                            stop=stop_after_attempt(2),
                            wait=wait_exponential(multiplier=1, min=1, max=5),
                            retry=retry_if_exception_type((TimeoutError, PlaywrightError)),
                            reraise=False
                        )
                        async def get_comments_with_retry():
                            return await crawler.get_comments(post_id, comment_count)

                        comments = await get_comments_with_retry()
                        if not comments:
                            return []
                            
                        for comment in comments:
                            comment['post_id'] = post_id
                        
                        # 实时汇报进度
                        if index % 5 == 0:
                            progress = 30.0 + (index / len(posts)) * 40.0
                            await self._update_task_progress(task_id, progress, f"正在抓取评论: {index}/{len(posts)}...")
                            
                        return comments
                    except Exception as e:
                        logger.error(f"Error fetching comments for post {post.get('id')}: {e}")
                        return []

            tasks = [fetch_comments_safe(post, i) for i, post in enumerate(posts)]
            results = await asyncio.gather(*tasks)
            
            for comments in results:
                all_comments.extend(comments)
            
            logger.info(f"Found {len(all_comments)} comments")
            await self._update_task_progress(task_id, 80.0, f"抓取完成，共 {len(all_comments)} 条评论，正在保存...")
            
            # 保存评论数据 (Async)
            await self.save_comments(all_comments, task_id, platform)
            await self._update_task_progress(task_id, 100.0, "任务完成")
            
            return {
                'posts': posts,
                'comments': all_comments,
                'total_posts': len(posts),
                'total_comments': len(all_comments)
            }
            
        except Exception as e:
            logger.error(f"Crawl failed: {str(e)}")
            await self._update_task_progress(task_id, None, f"抓取失败: {str(e)}", status='failed')
            raise e
        finally:
            if hasattr(crawler, 'context') and crawler.context:
                await crawler.context.close()

    async def _update_task_progress(self, task_id: Optional[int], progress: Optional[float], 
                                   message: str, status: str = None):
        """更新任务进度的统一辅助方法"""
        if not task_id:
            return
            
        async with AsyncSessionLocal() as session:
            try:
                stmt = select(Task).filter_by(id=task_id)
                result = await session.execute(stmt)
                task = result.scalars().first()
                if task:
                    if progress is not None:
                        task.progress = progress
                    task.progress_message = message
                    if status:
                        task.status = status
                    await session.commit()
            except Exception as e:
                logger.error(f"Failed to update task progress: {e}")

    async def load_cookies(self, platform: str) -> List[Dict]:
        return await asyncio.to_thread(self._load_cookies_sync, platform)

    def _load_cookies_sync(self, platform: str) -> List[Dict]:
        for cookie_file in self._cookie_file_candidates(platform):
            if not os.path.exists(cookie_file):
                continue
            try:
                with open(cookie_file, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    try:
                        return self._normalize_cookie_objects(platform, json.loads(content))
                    except json.JSONDecodeError:
                        if '=' in content:
                            cookies = []
                            domains = self._default_cookie_domains(platform) or [None]
                            for item in content.split(';'):
                                if '=' not in item:
                                    continue
                                name, value = item.strip().split('=', 1)
                                for domain in domains:
                                    cookie = {
                                        'name': name,
                                        'value': value,
                                        'path': '/'
                                    }
                                    if domain:
                                        cookie['domain'] = domain
                                    cookies.append(cookie)
                            return cookies
            except Exception as e:
                logger.error(f"Failed to load cookies from {cookie_file}: {e}")
        return []

    def _cookie_file_candidates(self, platform: str) -> List[str]:
        return get_cookie_file_candidates(platform)

    def _default_cookie_domains(self, platform: str) -> List[str]:
        domains = {
            "bilibili": [".bilibili.com"],
            "weibo": [".weibo.cn", "m.weibo.cn", ".weibo.com"],
            "douyin": [".douyin.com", "www.douyin.com"],
            "zhihu": [".zhihu.com"],
        }
        return domains.get(platform, [])

    def _get_user_agent_for_platform(self, platform: str) -> str:
        if platform == "weibo":
            return (
                "Mozilla/5.0 (Linux; Android 11; Pixel 5) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Mobile Safari/537.36"
            )
        return (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36'
        )

    def _normalize_cookie_objects(self, platform: str, cookies_data) -> List[Dict]:
        if not isinstance(cookies_data, list):
            return []

        normalized: List[Dict] = []
        default_domains = self._default_cookie_domains(platform)
        for item in cookies_data:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            value = item.get("value")
            if not name or value is None:
                continue

            base_cookie = {
                "name": str(name),
                "value": str(value),
                "path": item.get("path", "/"),
                "httpOnly": bool(item.get("httpOnly", False)),
                "secure": bool(item.get("secure", False)),
                "sameSite": item.get("sameSite", "Lax"),
            }

            domains = [item.get("domain")] if item.get("domain") else []
            if platform == "weibo" and item.get("domain", "").endswith(".weibo.com"):
                domains.extend([".weibo.cn", "m.weibo.cn"])
            domains.extend(default_domains)

            seen_domains = set()
            for domain in domains:
                if not domain or domain in seen_domains:
                    continue
                seen_domains.add(domain)
                cookie = dict(base_cookie)
                cookie["domain"] = domain
                normalized.append(cookie)

        return normalized

    async def save_posts(self, posts: List[Dict], task_id: int, platform: str):
        """保存帖子数据 (Async)"""
        if not task_id:
            return

        async with AsyncSessionLocal() as session:
            try:
                # Update task status
                stmt_task = select(Task).filter_by(id=task_id)
                res_task = await session.execute(stmt_task)
                task = res_task.scalars().first()
                if task:
                    task.progress = 30.0
                    task.progress_message = f"正在保存 {len(posts)} 条帖子..."
                    # Don't commit yet, will commit with posts
                
                for post_data in posts:
                    # Check if post exists for THIS task
                    stmt = select(Post).filter_by(
                        task_id=task_id,
                        platform=platform, 
                        platform_post_id=str(post_data['id'])
                    )
                    result = await session.execute(stmt)
                    existing_post = result.scalars().first()
                    
                    if not existing_post:
                        new_post = Post(
                            task_id=task_id,
                            platform_post_id=str(post_data['id']),
                            platform=platform,
                            content=post_data.get('content', ''),
                            author=post_data.get('author', ''),
                            post_time=self._parse_time(post_data.get('post_time')),
                            likes=self._to_int(post_data.get('likes', 0)),
                            comments_count=self._to_int(post_data.get('comments', 0)),
                            shares=self._to_int(post_data.get('shares', 0)),
                            views=self._to_int(post_data.get('views', 0))
                        )
                        session.add(new_post)
                
                await session.commit()
                logger.info(f"Saved {len(posts)} posts to database")
            except Exception as e:
                await session.rollback()
                logger.error(f"Failed to save posts: {str(e)}")

    async def save_comments(self, comments: List[Dict], task_id: int, platform: str):
        """保存评论数据 (Async)"""
        if not task_id:
            return
        
        async with AsyncSessionLocal() as session:
            try:
                # Update task status
                stmt_task = select(Task).filter_by(id=task_id)
                res_task = await session.execute(stmt_task)
                task = res_task.scalars().first()
                if task:
                    task.progress = 50.0
                    task.progress_message = f"正在保存 {len(comments)} 条评论..."
                    
                for comment_data in comments:
                    # Find the post in DB for THIS task
                    stmt = select(Post).filter_by(
                        task_id=task_id,
                        platform=platform,
                        platform_post_id=str(comment_data['post_id'])
                    )
                    result = await session.execute(stmt)
                    post = result.scalars().first()
                    
                    if post:
                        # Check if comment already exists for this post
                        stmt_comment = select(Comment).filter_by(
                            post_id=post.id,
                            platform_comment_id=str(comment_data['id'])
                        )
                        res_comment = await session.execute(stmt_comment)
                        existing_comment = res_comment.scalars().first()
                        
                        if not existing_comment:
                            new_comment = Comment(
                                post_id=post.id,
                                platform_comment_id=str(comment_data['id']),
                                content=comment_data.get('content', ''),
                                author=comment_data.get('author', ''),
                                comment_time=self._parse_time(comment_data.get('comment_time')),
                                likes=self._to_int(comment_data.get('likes', 0))
                            )
                            session.add(new_comment)
                
                await session.commit()
                logger.info(f"Saved {len(comments)} comments to database")
            except Exception as e:
                await session.rollback()
                logger.error(f"Failed to save comments: {str(e)}")

    def _parse_time(self, time_str):
        """Simple time parser"""
        if not time_str:
            return datetime.now()
        try:
            if isinstance(time_str, str) and time_str.isdigit():
                ts = float(time_str)
                return datetime.fromtimestamp(ts)
            if isinstance(time_str, (int, float)):
                return datetime.fromtimestamp(time_str)
        except:
            pass
        try:
            if isinstance(time_str, str):
                time_str = time_str.strip()
                relative_time = self._parse_relative_time(time_str)
                if relative_time:
                    return relative_time
                try:
                    return datetime.fromisoformat(time_str)
                except ValueError:
                    pass
                formats = [
                    '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d',
                    '%Y/%m/%d %H:%M:%S', '%Y年%m月%d日',
                    '%a %b %d %H:%M:%S %z %Y'
                ]
                for fmt in formats:
                    try:
                        parsed = datetime.strptime(time_str, fmt)
                        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
                    except ValueError:
                        continue
            return datetime.now() 
        except:
            return datetime.now()

    def _parse_relative_time(self, time_str: str) -> Optional[datetime]:
        now = datetime.now()
        try:
            if time_str == "刚刚":
                return now
            if match := re.match(r"(\d+)\s*秒前", time_str):
                return now - timedelta(seconds=int(match.group(1)))
            if match := re.match(r"(\d+)\s*分钟前", time_str):
                return now - timedelta(minutes=int(match.group(1)))
            if match := re.match(r"(\d+)\s*小时前", time_str):
                return now - timedelta(hours=int(match.group(1)))
            if match := re.match(r"昨天\s*(\d{1,2}:\d{1,2})", time_str):
                hour, minute = match.group(1).split(":")
                yesterday = now - timedelta(days=1)
                return yesterday.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
            if match := re.match(r"(\d{1,2})-(\d{1,2})", time_str):
                return datetime(now.year, int(match.group(1)), int(match.group(2)))
        except Exception:
            return None
        return None

    def _to_int(self, value) -> int:
        if value is None:
            return 0
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return int(value)
        text = str(value).strip()
        if not text:
            return 0
        text = re.sub(r"<[^>]+>", "", text)
        text = text.replace(",", "").replace("+", "")
        multiplier = 1
        if text.endswith("万"):
            multiplier = 10000
            text = text[:-1]
        elif text.endswith("亿"):
            multiplier = 100000000
            text = text[:-1]
        try:
            return int(float(text) * multiplier)
        except ValueError:
            digits = re.sub(r"[^\d.]", "", text)
            try:
                return int(float(digits) * multiplier) if digits else 0
            except ValueError:
                return 0
