from datetime import datetime, timedelta
from typing import Dict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sql_models import Comment, DashboardMetricCache, Post, Task


TOTAL_COLLECTED_CACHE_KEY = "total_collected"
CACHE_TTL_SECONDS = 60


class DashboardService:
    @staticmethod
    def _is_cache_stale(refreshed_at: datetime | None, now: datetime | None = None) -> bool:
        if refreshed_at is None:
            return True
        current_time = now or datetime.now()
        return refreshed_at < current_time - timedelta(seconds=CACHE_TTL_SECONDS)

    @staticmethod
    async def _recompute_total_collected(db: AsyncSession) -> int:
        post_count = await db.scalar(select(func.count(Post.id)))
        comment_count = await db.scalar(select(func.count(Comment.id)))
        return int(post_count or 0) + int(comment_count or 0)

    @staticmethod
    async def get_total_collected(db: AsyncSession) -> int:
        result = await db.execute(
            select(DashboardMetricCache).filter(
                DashboardMetricCache.cache_key == TOTAL_COLLECTED_CACHE_KEY
            )
        )
        cache_record = result.scalars().first()

        if cache_record and not DashboardService._is_cache_stale(cache_record.refreshed_at):
            return int(cache_record.metric_value)

        total_collected = await DashboardService._recompute_total_collected(db)
        refreshed_at = datetime.now()

        if cache_record:
            cache_record.metric_value = total_collected
            cache_record.refreshed_at = refreshed_at
        else:
            cache_record = DashboardMetricCache(
                cache_key=TOTAL_COLLECTED_CACHE_KEY,
                metric_value=total_collected,
                refreshed_at=refreshed_at,
            )
            db.add(cache_record)

        await db.commit()
        return total_collected

    @staticmethod
    async def refresh_total_collected_cache(db: AsyncSession) -> int:
        total_collected = await DashboardService._recompute_total_collected(db)
        result = await db.execute(
            select(DashboardMetricCache).filter(
                DashboardMetricCache.cache_key == TOTAL_COLLECTED_CACHE_KEY
            )
        )
        cache_record = result.scalars().first()
        refreshed_at = datetime.now()

        if cache_record:
            cache_record.metric_value = total_collected
            cache_record.refreshed_at = refreshed_at
        else:
            db.add(
                DashboardMetricCache(
                    cache_key=TOTAL_COLLECTED_CACHE_KEY,
                    metric_value=total_collected,
                    refreshed_at=refreshed_at,
                )
            )

        await db.commit()
        return total_collected

    @staticmethod
    async def get_active_tasks(db: AsyncSession) -> int:
        active_tasks = await db.scalar(
            select(func.count(Task.id)).filter(Task.status == "running")
        )
        return int(active_tasks or 0)

    @staticmethod
    async def get_today_new_tasks(db: AsyncSession) -> int:
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_new_tasks = await db.scalar(
            select(func.count(Task.id)).filter(Task.created_at >= today_start)
        )
        return int(today_new_tasks or 0)

    @staticmethod
    async def get_metrics(db: AsyncSession) -> Dict[str, int]:
        total_collected = await DashboardService.get_total_collected(db)
        active_tasks = await DashboardService.get_active_tasks(db)
        today_new_tasks = await DashboardService.get_today_new_tasks(db)

        return {
            "totalCollected": total_collected,
            "activeTasks": active_tasks,
            "todayNewTasks": today_new_tasks,
        }
