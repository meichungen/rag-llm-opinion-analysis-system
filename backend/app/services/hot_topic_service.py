import httpx
import logging
import uuid
from datetime import datetime
from typing import List, Dict, Optional
from sqlalchemy.future import select
from sqlalchemy import desc, func
from app.core.database import AsyncSessionLocal
from app.models.sql_models import HotTopic, SystemConfig

logger = logging.getLogger(__name__)

API_BASE_URL = "https://newsnow.busiyi.world/api/s"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

SUPPORTED_SOURCES = {
    "weibo": "微博热搜",
    "bilibili": "B站热搜",
    "douyin": "抖音热榜",
    "zhihu": "知乎热榜",
    "douban": "豆瓣小组",
    "coolapk": "酷安热榜",
    "wallstreetcn-hot": "华尔街见闻",
    "thepaper": "澎湃新闻",
    "toutiao": "今日头条",
    "baidu": "百度热搜",
    "hupu": "虎扑步行街",
    "github": "GitHub Trending",
    "xueqiu": "雪球热帖",
    "36kr-renqi": "36氪人气",
    "tieba": "百度贴吧",
    "cls-hot": "财联社热榜",
    "producthunt": "Product Hunt",
    "nowcoder": "牛客网",
    "steam": "Steam",
    "freebuf": "FreeBuf",
    "ifeng": "凤凰网",
    "chongbuluo-hot": "虫部落",
    "tencent-hot": "腾讯新闻",
    "sspai": "少数派",
    "juejin": "稀土掘金"
}

def get_supported_sources():
    return [{"id": k, "name": v} for k, v in SUPPORTED_SOURCES.items()]


def _truncate_text(value: Optional[str], limit: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:limit]

async def fetch_hot_topics(source_id: str = "weibo") -> List[Dict]:
    """
    Fetch hot topics from the external API with timeout and error handling.
    """
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(f"{API_BASE_URL}?id={source_id}", headers=HEADERS)
            if response.status_code == 200:
                data = response.json()
                if data.get("success") is False:
                    logger.warning(f"API returned failure for {source_id}: {data.get('message')}")
                    return []
                return data.get("items", [])
            else:
                logger.error(f"Failed to fetch hot topics for {source_id}: Status {response.status_code}")
                return []
    except httpx.TimeoutException:
        logger.error(f"Timeout fetching hot topics for {source_id}")
        return []
    except Exception as e:
        logger.error(f"Exception fetching hot topics for {source_id}: {e}")
        return []

async def save_hot_topics(source: str, items: List[Dict]):
    """
    Save hot topics to the database.
    """
    if not items:
        return

    batch_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as session:
        try:
            for index, item in enumerate(items):
                title = _truncate_text(item.get("title", "No Title"), 255) or "No Title"
                url = _truncate_text(item.get("url"), 500)
                hot_value = _truncate_text(item.get("extra", {}).get("hot"), 50)
                hot_topic = HotTopic(
                    source=source,
                    title=title,
                    url=url,
                    rank=index + 1,
                    hot_value=hot_value, # Try to get hot value if available
                    extra_data=item,
                    batch_id=batch_id
                )
                session.add(hot_topic)
            await session.commit()
            logger.info(f"Saved {len(items)} hot topics for {source} with batch_id {batch_id}")
        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to save hot topics: {e}")

async def get_latest_hot_topics(source: str, limit: int = 50) -> List[HotTopic]:
    """
    Get the latest batch of hot topics for a source.
    """
    async with AsyncSessionLocal() as session:
        # First find the latest batch_id for the source
        subquery = select(HotTopic.batch_id).filter(HotTopic.source == source).order_by(desc(HotTopic.created_at)).limit(1).scalar_subquery()
        
        query = select(HotTopic).filter(
            HotTopic.source == source,
            HotTopic.batch_id == subquery
        ).order_by(HotTopic.rank)
        
        result = await session.execute(query)
        return result.scalars().all()

async def update_hot_topics_task(source: str = "weibo"):
    """
    Task to be scheduled: fetch and save.
    """
    logger.info(f"Starting hot topic update for {source}")
    items = await fetch_hot_topics(source)
    if items:
        await save_hot_topics(source, items)
    logger.info(f"Finished hot topic update for {source}")
