import asyncio
import sys
import os
import logging
from app.crawler.crawler import SocialMediaCrawler
from app.core.database import AsyncSessionLocal
from app.core.settings import get_default_setting
from sqlalchemy.future import select
from app.models.sql_models import SystemConfig, Task

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_crawler_process(task_id: int):
    # Set policy explicitly for this process
    if sys.platform == 'win32':
        # Check if policy is already set (it shouldn't be in a fresh process, but good to be safe)
        if not isinstance(asyncio.get_event_loop_policy(), asyncio.WindowsProactorEventLoopPolicy):
             asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
             logger.info("Worker: Set WindowsProactorEventLoopPolicy")
    
    logger.info(f"Worker starting for task {task_id}")
    
    platform = None
    keyword = None
    post_count = 0
    comment_count = 0
    platform_settings = get_default_setting("platform")
    
    # Worker 进程启动后先从数据库重新读取任务参数，
    # 使主进程与子进程仅通过 task_id 协同，便于保持职责边界清晰。
    # 1. Fetch task info
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Task).filter_by(id=task_id))
            task = result.scalars().first()
            if not task:
                logger.error(f"Task {task_id} not found in DB")
                sys.exit(1)
                
            platform = task.platform
            keyword = task.keyword
            post_count = task.post_count
            comment_count = task.comment_count

            platform_config_result = await session.execute(select(SystemConfig).filter_by(key="platform"))
            platform_config = platform_config_result.scalars().first()
            if platform_config and isinstance(platform_config.value, dict):
                platform_settings.update(platform_config.value)
            
            # Update status to crawling in worker (double check)
            task.progress_message = f"Worker: 正在启动 {platform} 爬虫..."
            await session.commit()
    except Exception as e:
        logger.error(f"Failed to fetch task info: {e}")
        sys.exit(1)
    
    # 浏览器自动化采集在子进程中执行，
    # 以便在采集异常时将影响范围限制在当前 Worker 内部。
    # 2. Run crawler
    # Note: We create a NEW instance of crawler here
    crawler = SocialMediaCrawler(platform_settings=platform_settings)
    try:
        async with crawler:
            await crawler.crawl(
                platform=platform,
                keyword=keyword,
                post_count=post_count,
                comment_count=comment_count,
                task_id=task_id
            )
        logger.info("Worker: Crawling finished successfully")
    except Exception as e:
        logger.error(f"Worker: Crawling failed: {e}")
        # Try to update task status
        try:
             async with AsyncSessionLocal() as session:
                result = await session.execute(select(Task).filter_by(id=task_id))
                task = result.scalars().first()
                if task:
                    task.status = 'failed'
                    task.progress_message = f"爬虫Worker失败: {str(e)}"
                    await session.commit()
        except:
            pass
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m app.crawler.worker <task_id>")
        sys.exit(1)
    
    # Add project root to path if needed (though running with -m app.crawler.worker handles it)
    sys.path.append(os.getcwd())
    
    task_id = int(sys.argv[1])
    
    # Windows specific policy for the worker process - BEFORE asyncio.run
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        
    try:
        asyncio.run(run_crawler_process(task_id))
    except Exception as e:
        logger.error(f"Crawler worker process failed: {e}")
        sys.exit(1)
