import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional
from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright

from app.crawler.bili import BilibiliCrawler
from app.crawler.weibo import WeiboCrawler
from app.crawler.douyin import DouyinCrawler
from app.core.settings import (
    get_cookie_file_candidates,
    get_platform_crawler_config,
    read_cookie_metadata,
)


logger = logging.getLogger(__name__)


def _detect_risk_fingerprints(platform: str, text: str) -> List[Dict[str, str]]:
    haystack = (text or "").lower()
    fingerprints: List[Dict[str, str]] = []
    rules = [
        ("bilibili_412", ["错误号: 412", "security control policy", "请求被拒绝", "验证码"], "触发平台风控或验证码拦截"),
        ("captcha", ["captcha", "verify", "验证"], "命中验证码校验"),
        ("wbi_failed", ["failed to get wbi keys", "wbi"], "Bilibili wbi 签名获取失败"),
        ("empty_json", ["非 json", "decode json", "empty content", "空内容"], "接口返回空内容或非 JSON"),
        ("login_required", ["未登录", "login", "-101", "passport_csrf_token"], "登录态可能失效"),
        ("blocked", ["blocked", "风控拦截"], "请求被平台拦截"),
    ]
    for code, keywords, message in rules:
        if any(keyword.lower() in haystack for keyword in keywords):
            fingerprints.append({"code": code, "message": message, "platform": platform})
    return fingerprints


def _merge_risk_fingerprints(*groups: List[Dict[str, str]]) -> List[Dict[str, str]]:
    merged: List[Dict[str, str]] = []
    seen = set()
    for group in groups:
        for item in group or []:
            key = (item.get("platform"), item.get("code"))
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged


def _build_warning(message: str, platform: str, scope: str) -> Dict[str, Any]:
    return {
        "scope": scope,
        "message": message,
        "risk_fingerprints": _detect_risk_fingerprints(platform, message),
    }


def _finalize_crawl_result(
    *,
    platform: str,
    keyword: str,
    posts: List[Dict[str, Any]],
    comments: List[Dict[str, Any]],
    post_count: int,
    comment_count: int,
    warnings: List[Dict[str, Any]],
    diagnostics: Dict[str, Any],
    error: Optional[str] = None,
) -> Dict[str, Any]:
    fetched_posts = len(posts)
    fetched_comments = len(comments)
    all_risks = _merge_risk_fingerprints(
        diagnostics.get("risk_fingerprints", []),
        *[warning.get("risk_fingerprints", []) for warning in warnings],
    )
    diagnostics["risk_fingerprints"] = all_risks

    if error:
        return {
            "success": False,
            "status": "failed",
            "platform": platform,
            "keyword": keyword,
            "posts": posts,
            "comments": comments,
            "total_posts": fetched_posts,
            "total_comments": fetched_comments,
            "warnings": warnings,
            "diagnostics": diagnostics,
            "error": error,
        }

    partial = (
        bool(warnings)
        or fetched_posts < min(post_count, diagnostics.get("available_posts", fetched_posts))
        or (comment_count > 0 and fetched_comments < comment_count and fetched_posts > 0)
    )
    status = "partial_success" if partial else "success"
    message = "抓取完成" if status == "success" else "抓取部分完成，存在告警或降级"
    return {
        "success": True,
        "status": status,
        "platform": platform,
        "keyword": keyword,
        "posts": posts,
        "comments": comments,
        "total_posts": fetched_posts,
        "total_comments": fetched_comments,
        "warnings": warnings,
        "diagnostics": diagnostics,
        "message": message,
    }


class AgentCrawlerTool:
    _browser: Optional[Browser] = None
    _playwright: Optional[Playwright] = None
    _contexts: Dict[str, BrowserContext] = {}
    
    @classmethod
    async def ensure_browser(cls) -> Browser:
        if cls._browser is None:
            cls._playwright = await async_playwright().start()
            cls._browser = await cls._playwright.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-dev-shm-usage']
            )
            logger.info("AgentCrawlerTool: Browser launched")
        return cls._browser
    
    @classmethod
    async def ensure_context(cls, platform: str) -> BrowserContext:
        browser = await cls.ensure_browser()
        
        if platform not in cls._contexts:
            ua_map = {
                'bilibili': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'weibo': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'douyin': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1',
            }
            ua = ua_map.get(platform, ua_map['bilibili'])
            
            context = await browser.new_context(
                user_agent=ua,
                locale='zh-CN',
                extra_http_headers={'Accept-Language': 'zh-CN,zh;q=0.9'}
            )
            
            cookies = await cls._load_cookies(platform)
            if cookies:
                try:
                    await context.add_cookies(cookies)
                    logger.info(f"AgentCrawlerTool: Loaded {len(cookies)} cookies for {platform}")
                except Exception as e:
                    logger.warning(f"Failed to add cookies: {e}")
            else:
                logger.warning(f"AgentCrawlerTool: No cookies found for {platform}")
            
            cls._contexts[platform] = context
            logger.info(f"AgentCrawlerTool: Context created for {platform}")
        
        return cls._contexts[platform]
    
    @classmethod
    async def _load_cookies(cls, platform: str) -> List[Dict]:
        return await asyncio.to_thread(cls._load_cookies_sync, platform)
    
    @classmethod
    def _load_cookies_sync(cls, platform: str) -> List[Dict]:
        candidates = get_cookie_file_candidates(platform)
        logger.info(f"AgentCrawlerTool: Cookie candidates for {platform}: {candidates}")

        for cookie_file in candidates:
            if not os.path.exists(cookie_file):
                logger.info(f"AgentCrawlerTool: Cookie file not found: {cookie_file}")
                continue
            try:
                with open(cookie_file, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    logger.info(f"AgentCrawlerTool: Read {len(content)} chars from {cookie_file}")

                    cookies = None
                    try:
                        cookies = json.loads(content)
                        logger.info(f"AgentCrawlerTool: Parsed JSON, type={type(cookies)}, length={len(cookies) if isinstance(cookies, list) else 'N/A'}")
                    except json.JSONDecodeError:
                        logger.warning(f"AgentCrawlerTool: JSON decode error, trying plain text cookie format")
                        cookies = cls._parse_plain_text_cookies(platform, content)

                    if isinstance(cookies, dict) and isinstance(cookies.get("cookies"), list):
                        cookies = cookies["cookies"]

                    if isinstance(cookies, list) and len(cookies) > 0:
                        logger.info(f"AgentCrawlerTool: Found {len(cookies)} cookies in {cookie_file}")
                        return cls._normalize_cookies(platform, cookies)
                    elif isinstance(cookies, dict) and len(cookies) > 0:
                        cookie_list = [{"name": k, "value": v} for k, v in cookies.items()]
                        logger.info(f"AgentCrawlerTool: Found {len(cookie_list)} cookies in {cookie_file}")
                        return cls._normalize_cookies(platform, cookie_list)

            except Exception as e:
                logger.warning(f"AgentCrawlerTool: Failed to load cookies from {cookie_file}: {e}")
        logger.warning(f"AgentCrawlerTool: No valid cookies found for {platform} from {len(candidates)} candidates")
        return []

    @classmethod
    def _parse_plain_text_cookies(cls, platform: str, content: str) -> List[Dict]:
        platform_domain_map = {
            'bilibili': '.bilibili.com',
            'bili': '.bilibili.com',
            'douyin': '.douyin.com',
            'weibo': '.weibo.com',
        }
        default_domain = platform_domain_map.get(platform, '.bilibili.com')
        cookies = []
        for part in content.split(';'):
            part = part.strip()
            if '=' in part:
                name, value = part.split('=', 1)
                name = name.strip()
                value = value.strip()
                if not name:
                    continue
                cookies.append({
                    "name": name,
                    "value": value,
                    "domain": default_domain,
                    "path": "/",
                })
        logger.info(f"AgentCrawlerTool: Parsed {len(cookies)} cookies from plain text format")
        return cookies
    
    @classmethod
    def _normalize_cookies(cls, platform: str, cookies: List[Dict]) -> List[Dict]:
        platform_domain_map = {
            'bilibili': '.bilibili.com',
            'bili': '.bilibili.com',
            'douyin': '.douyin.com',
            'weibo': '.weibo.com',
        }
        default_domain = platform_domain_map.get(platform, '.bilibili.com')

        normalized = []
        for cookie in cookies:
            if isinstance(cookie, dict):
                name = cookie.get('name', '')
                value = cookie.get('value', '')
                if not name or value is None:
                    continue
                normalized_cookie = {
                    'name': name,
                    'value': str(value),
                    'domain': cookie.get('domain') or default_domain,
                    'path': cookie.get('path', '/'),
                    'secure': cookie.get('secure', True),
                    'httpOnly': cookie.get('httpOnly', False),
                }
                normalized.append(normalized_cookie)
            elif isinstance(cookie, str):
                normalized.append({
                    'name': cookie,
                    'value': '',
                    'domain': default_domain,
                    'path': '/',
                    'secure': True,
                    'httpOnly': False,
                })

        return normalized
    
    @classmethod
    async def close(cls):
        for platform, context in cls._contexts.items():
            await context.close()
        cls._contexts = {}
        if cls._browser:
            await cls._browser.close()
            cls._browser = None
        if cls._playwright:
            await cls._playwright.stop()
            cls._playwright = None
        logger.info("AgentCrawlerTool: Browser closed")


async def crawl_platform(
    platform: str,
    keyword: str,
    post_count: int = 10,
    comment_count: int = 10,
    platform_settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    runtime_platform = "bilibili" if platform == "bili" else platform
    warnings: List[Dict[str, Any]] = []
    diagnostics: Dict[str, Any] = {
        "requested_posts": post_count,
        "requested_comments": comment_count,
        "risk_fingerprints": [],
    }
    try:
        browser = await AgentCrawlerTool.ensure_browser()
        context = await AgentCrawlerTool.ensure_context(runtime_platform)
        cookie_health = read_cookie_metadata(runtime_platform)
        crawler_config = get_platform_crawler_config(runtime_platform, platform_settings)
        diagnostics["cookie_health"] = cookie_health
        diagnostics["crawler_config"] = crawler_config
        if cookie_health.get("health") not in {"healthy"}:
            warnings.append(
                _build_warning(
                    f"{runtime_platform} Cookie 健康状态为 {cookie_health.get('health')}: {'; '.join(cookie_health.get('issues', []))}",
                    runtime_platform,
                    "cookie",
                )
            )
        
        crawler_map = {
            'bilibili': BilibiliCrawler,
            'bili': BilibiliCrawler,
            'weibo': WeiboCrawler,
            'douyin': DouyinCrawler,
        }
        
        if platform not in crawler_map:
            return _finalize_crawl_result(
                platform=platform,
                keyword=keyword,
                posts=[],
                comments=[],
                post_count=post_count,
                comment_count=comment_count,
                warnings=warnings,
                diagnostics=diagnostics,
                error=f"不支持的平台: {platform}",
            )
        
        crawler_class = crawler_map[platform]
        crawler = crawler_class(browser, crawler_config)
        crawler.context = context
        crawler.page = await context.new_page()
        try:
            await crawler.init_client()
            
            logger.info(f"Successfully initialized crawler for {platform}")
            
            logger.info(f"Searching {platform} for: {keyword}")
            posts = await crawler.search_posts(keyword, post_count)
            posts = posts[:post_count]
            diagnostics["available_posts"] = len(posts)
            
            if not posts:
                warnings.append(_build_warning("未找到相关帖子，可能是关键词无结果或请求被限流。", platform, "search"))
                return _finalize_crawl_result(
                    platform=platform,
                    keyword=keyword,
                    posts=[],
                    comments=[],
                    post_count=post_count,
                    comment_count=comment_count,
                    warnings=warnings,
                    diagnostics=diagnostics,
                )
            
            comments = []
            
            posts_to_process = posts[:max(1, min(post_count, len(posts)))]
            comment_request_cap = int(crawler_config.get("max_comments_per_post_request", 50))
            
            for post in posts_to_process:
                post_id = post.get('id') or post.get('bvid')
                remaining_comments = comment_count - len(comments)
                if not post_id or remaining_comments <= 0:
                    continue
                
                try:
                    request_count = min(remaining_comments, max(1, comment_request_cap))
                    post_comments = await crawler.get_comments(post_id, request_count)
                    post_comments = post_comments[:remaining_comments]
                    for c in post_comments:
                        c['post_id'] = post_id
                    comments.extend(post_comments)
                    logger.info(f"从视频 {post_id} 获取到 {len(post_comments)} 条评论")
                except Exception as e:
                    logger.warning(f"获取评论失败 {post_id}: {e}")
                    warning = _build_warning(f"帖子 {post_id} 评论抓取失败: {e}", platform, "comments")
                    warnings.append(warning)

            diagnostics.update({
                "processed_posts": len(posts_to_process),
                "comment_request_cap": comment_request_cap,
                "fetched_posts": len(posts[:post_count]),
                "fetched_comments": len(comments),
            })
            if len(comments) < comment_count and comment_count > 0:
                warnings.append(
                    _build_warning(
                        f"评论抓取数量不足，目标 {comment_count}，实际 {len(comments)}。",
                        platform,
                        "comments",
                    )
                )

            return _finalize_crawl_result(
                platform=platform,
                keyword=keyword,
                posts=posts[:post_count],
                comments=comments,
                post_count=post_count,
                comment_count=comment_count,
                warnings=warnings,
                diagnostics=diagnostics,
            )
        finally:
            if crawler.page:
                await crawler.page.close()
        
    except Exception as e:
        logger.error(f"Crawl failed: {e}")
        warnings.append(_build_warning(str(e), platform, "runtime"))
        diagnostics["risk_fingerprints"] = _merge_risk_fingerprints(
            diagnostics.get("risk_fingerprints", []),
            *[warning.get("risk_fingerprints", []) for warning in warnings],
        )
        return _finalize_crawl_result(
            platform=platform,
            keyword=keyword,
            posts=[],
            comments=[],
            post_count=post_count,
            comment_count=comment_count,
            warnings=warnings,
            diagnostics=diagnostics,
            error=str(e),
        )


async def analyze_crawled_data(data: Dict[str, Any]) -> Dict[str, Any]:
    if not data.get("success"):
        return data
    
    posts = data.get("posts", [])
    comments = data.get("comments", [])
    
    texts = []
    for post in posts:
        content = post.get("content", "")
        if content:
            texts.append(content)
    
    for comment in comments:
        content = comment.get("content", "")
        if content:
            texts.append(content)
    
    return {
        "success": True,
        "status": data.get("status", "success"),
        "data_summary": {
            "total_posts": len(posts),
            "total_comments": len(comments),
            "texts_for_analysis": len(texts)
        },
        "warnings": data.get("warnings", []),
        "diagnostics": data.get("diagnostics", {}),
        "posts_sample": posts[:3] if posts else [],
        "comments_sample": comments[:10] if comments else []
    }
