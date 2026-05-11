from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from app.services.hot_topic_service import update_hot_topics_task, SUPPORTED_SOURCES
import logging
import asyncio

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()
BOOTSTRAP_SOURCES = ("weibo", "bilibili", "douyin", "zhihu")

def start_scheduler():
    if not scheduler.running:
        # Schedule jobs for all supported sources
        # Stagger them slightly if needed, but for now concurrent execution is fine
        for source_id in SUPPORTED_SOURCES.keys():
            scheduler.add_job(
                update_hot_topics_task, 
                trigger=IntervalTrigger(minutes=60), 
                id=f"fetch_hot_topics_{source_id}", 
                replace_existing=True,
                args=[source_id]
            )
            logger.info(f"Scheduled task for {source_id}")
            
        scheduler.start()
        logger.info("Scheduler started")
        
        # 仅预热常用来源，避免启动时一次并发拉取全部来源导致界面长时间卡住。
        for source_id in BOOTSTRAP_SOURCES:
             if source_id not in SUPPORTED_SOURCES:
                 continue
             asyncio.create_task(update_hot_topics_task(source_id))
             logger.info(f"Triggered immediate hot topic update for {source_id}")

def shutdown_scheduler():
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler shutdown")
