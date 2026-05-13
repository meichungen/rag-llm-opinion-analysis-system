import os
import sys
import json
import asyncio
import logging
import io
from urllib.parse import quote
from datetime import datetime
from typing import List, Optional, Union, Dict, Any
from contextlib import asynccontextmanager

# Fix asyncio event loop policy for Windows
# This MUST be done before any asyncio loop is created
if sys.platform == 'win32':
    # Check if policy is already set to avoid warnings/errors
    if not isinstance(asyncio.get_event_loop_policy(), asyncio.WindowsProactorEventLoopPolicy):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        logging.info("Set WindowsProactorEventLoopPolicy for Playwright compatibility.")

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, Request, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, delete, desc, text
import time

from app.core.database import get_db, engine, Base, AsyncSessionLocal
from app.core.settings import (
    DEFAULT_SETTINGS,
    get_default_setting,
    get_cookie_file_path,
    normalize_cookie_content,
    read_platform_cookie_status,
)
from app.core.llm import resolve_llm_runtime_config
from app.models.sql_models import User, Task, Post, Comment, Sentiment, AnalysisResult, SystemConfig
from app.schemas.schemas import (
    TaskCreate, Task as TaskSchema, TaskListResponse, TaskDetail,
    DataPreviewResponse, LDAResponse, SentimentAnalysisResponse,
    WordCloudResponse, TaskAction, SettingsUpdate, PlatformCookieUpdate, QARequest, QAResponse,
    AgentChatRequest, AgentChatResponse, HotTopicListResponse, HotTopicSettings,
    HotTopicAnalysisRequest, HotTopicAnalysisResponse, ExportRequest,
    DashboardMetricsResponse
)
from app.agent import OpinionAgent
from app.services.services import run_task_logic, stop_task_process
from app.services.dashboard_service import DashboardService
from app.services.report_service import ReportService
from app.qa.llm_service import LLMQuestionAnswering
from app.services.hot_topic_service import get_latest_hot_topics, update_hot_topics_task, get_supported_sources, SUPPORTED_SOURCES
from app.core.scheduler import start_scheduler, shutdown_scheduler, scheduler
from apscheduler.triggers.interval import IntervalTrigger

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STOP_WORDS = set()

def load_stop_words():
    global STOP_WORDS
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(current_dir, 'stop_words.txt')
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                STOP_WORDS = set(line.strip() for line in f if line.strip())
            logger.info(f"Loaded {len(STOP_WORDS)} stop words from {file_path}")
        else:
            logger.warning(f"Stop words file not found at {file_path}")
    except Exception as e:
        logger.error(f"Failed to load stop words: {e}")

load_stop_words()


def merge_dict_values(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = merge_dict_values(merged.get(key), value)
        return merged
    return override


async def get_system_config_record(db: AsyncSession, key: str) -> Optional[SystemConfig]:
    result = await db.execute(select(SystemConfig).filter(SystemConfig.key == key))
    return result.scalars().first()


async def get_setting_value(db: AsyncSession, key: str) -> Any:
    record = await get_system_config_record(db, key)
    default_value = get_default_setting(key)
    if not record:
        return default_value
    if default_value:
        return merge_dict_values(default_value, record.value)
    return record.value


async def save_setting_value(
    db: AsyncSession,
    key: str,
    value: Any,
    description: Optional[str] = None,
) -> SystemConfig:
    record = await get_system_config_record(db, key)
    if record:
        record.value = value
        if description is not None:
            record.description = description
    else:
        record = SystemConfig(key=key, value=value, description=description)
        db.add(record)

    await db.commit()
    await db.refresh(record)
    return record


def mask_secret(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:4]}{'*' * max(4, len(secret) - 8)}{secret[-4:]}"


def sanitize_llm_settings(value: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = dict(value or {})
    sanitized["api_key"] = mask_secret(str(sanitized.get("api_key", "") or ""))
    sanitized["has_api_key"] = bool(value and value.get("api_key"))
    return sanitized


def preserve_secret_fields(current: Dict[str, Any], incoming: Dict[str, Any], fields: list[str]) -> Dict[str, Any]:
    merged = dict(incoming or {})
    for field in fields:
        raw = merged.get(field)
        if raw in (None, "", "******") and current.get(field):
            merged[field] = current[field]
    return merged


async def get_llm_runtime_config(db: AsyncSession) -> Dict[str, Any]:
    config = await get_setting_value(db, "llm")
    return resolve_llm_runtime_config(config)


async def build_settings_response(db: AsyncSession) -> Dict[str, Any]:
    llm_settings = await get_llm_runtime_config(db)
    return {
        "system": await get_setting_value(db, "system"),
        "model": await get_setting_value(db, "model"),
        "llm": sanitize_llm_settings(llm_settings),
        "agent": await get_setting_value(db, "agent"),
        "platform": await get_setting_value(db, "platform"),
        "platform_cookie_status": read_platform_cookie_status(DEFAULT_SETTINGS["platform"].keys()),
    }


def ensure_task_indexes(sync_conn) -> None:
    # 使用 SQLAlchemy 的 checkfirst 机制创建索引，避免不同数据库对
    # CREATE INDEX IF NOT EXISTS 语法支持不一致导致启动失败。
    for index in Task.__table__.indexes:
        index.create(bind=sync_conn, checkfirst=True)

# Lifespan events
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 服务启动时统一初始化数据表，确保系统首次运行即可完成持久化。
    # Startup: Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(ensure_task_indexes)
    
    # 预置默认管理员账户，便于在演示与测试环境中直接完成基础管理操作。
    # Create default user if not exists
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).filter_by(id=1))
        user = result.scalars().first()
        if not user:
            default_user = User(
                id=1,
                username='admin',
                email='admin@example.com',
                password_hash='hashed_password_placeholder',
                role='admin'
            )
            session.add(default_user)
            try:
                await session.commit()
                logger.info("Created default user")
            except Exception as e:
                logger.error(f"Failed to create default user: {e}")
    
    # Start scheduler
    start_scheduler()
    
    yield
    # Shutdown logic if any
    shutdown_scheduler()

app = FastAPI(title="Social Media Analysis API", lifespan=lifespan)

# Global Exception Handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error", "message": str(exc)},
    )

# Middleware for request logging and performance monitoring
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    logger.info(f"{request.method} {request.url.path} - {response.status_code} - {process_time:.4f}s")
    return response

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, specify domains
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes

@app.get("/api/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    try:
        # Check database connectivity
        await db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        logger.error(f"Health check DB error: {e}")
        db_status = "disconnected"
    
    return {
        "status": "healthy" if db_status == "connected" else "degraded",
        "database": db_status,
        "timestamp": datetime.now().isoformat(),
        "version": "1.1.0"
    }

@app.get("/api/hot-search")
async def get_hot_search():
    import random
    topics = [
        {'id': '1', 'title': 'Artificial Intelligence Breakthrough', 'heat': 987654, 'category': 'Tech', 'trend': 'up'},
        {'id': '2', 'title': 'Global Climate Summit', 'heat': 876543, 'category': 'News', 'trend': 'same'},
        {'id': '3', 'title': 'New Electric Vehicle Launch', 'heat': 765432, 'category': 'Auto', 'trend': 'up'},
        {'id': '4', 'title': 'International Film Festival', 'heat': 654321, 'category': 'Entertainment', 'trend': 'down'},
        {'id': '5', 'title': 'Space Exploration Mission', 'heat': 543210, 'category': 'Science', 'trend': 'up'},
        {'id': '6', 'title': 'World Cup Finals', 'heat': 432109, 'category': 'Sports', 'trend': 'up'},
        {'id': '7', 'title': 'Stock Market Trends', 'heat': 321098, 'category': 'Finance', 'trend': 'down'},
        {'id': '8', 'title': 'Healthy Eating Habits', 'heat': 210987, 'category': 'Health', 'trend': 'same'},
        {'id': '9', 'title': 'Virtual Reality Gaming', 'heat': 109876, 'category': 'Gaming', 'trend': 'up'},
        {'id': '10', 'title': 'Sustainable Fashion', 'heat': 98765, 'category': 'Lifestyle', 'trend': 'up'},
    ]
    return topics


@app.get("/api/v1/dashboard/metrics", response_model=DashboardMetricsResponse)
async def get_dashboard_metrics(db: AsyncSession = Depends(get_db)):
    try:
        return await DashboardService.get_metrics(db)
    except Exception as exc:
        logger.error(f"Failed to load dashboard metrics: {exc}")
        raise HTTPException(status_code=500, detail="Dashboard metrics unavailable")

@app.post("/api/tasks", status_code=201)
async def create_task(
    task_in: TaskCreate, 
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    # 检查用户当前运行中的任务数量
    system_settings = await get_setting_value(db, "system")
    max_tasks = system_settings.get("max_tasks_per_user", 10)
    
    # 查询该用户正在运行的任务数量 (running 或 pending)
    result = await db.execute(
        select(func.count(Task.id)).filter(
            Task.user_id == 1,
            Task.status.in_(['running', 'pending'])
        )
    )
    active_tasks_count = result.scalar()
    
    if active_tasks_count >= max_tasks:
        raise HTTPException(
            status_code=400, 
            detail=f"任务创建失败：当前已有 {active_tasks_count} 个运行中的任务，已达到系统限制 ({max_tasks}个)。"
        )

    # 该接口仅负责创建任务记录并快速返回响应，
    # 耗时较长的数据采集与分析流程交由后台任务异步执行。
    new_task = Task(
        user_id=1,  # Default admin user
        keyword=task_in.keyword,
        platform=task_in.platform,
        post_count=task_in.post_count,
        comment_count=task_in.comment_count,
        status='pending',
        created_at=datetime.now()
    )
    db.add(new_task)
    await db.commit()
    await db.refresh(new_task)
    
    # Trigger background task logic (Crawler -> Sentiment Analysis -> Store)
    background_tasks.add_task(run_task_logic, new_task.id)
    
    return new_task

@app.get("/api/tasks", response_model=TaskListResponse)
async def get_tasks(
    skip: int = 0, 
    limit: int = 100, 
    db: AsyncSession = Depends(get_db)
):
    # Query tasks with latest first
    result = await db.execute(
        select(Task).order_by(desc(Task.created_at)).offset(skip).limit(limit)
    )
    tasks = result.scalars().all()
    
    # Get total count (simplified for async)
    count_res = await db.execute(select(func.count(Task.id)))
    total = count_res.scalar()
    
    return {"tasks": tasks, "total": total}

@app.post("/api/tasks/{task_id}/report")
async def generate_task_report(
    task_id: int,
    force_regenerate: bool = False,
    db: AsyncSession = Depends(get_db)
):
    """
    Generate comprehensive AI analysis report for a task.
    """
    # Verify task exists
    result = await db.execute(select(Task).filter(Task.id == task_id))
    task = result.scalars().first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
        
    try:
        service = ReportService()
        report = await service.generate_comprehensive_report(task_id, force_regenerate=force_regenerate)
        return {"report": report}
    except Exception as e:
        logger.error(f"Failed to generate report: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/tasks/{task_id}/report")
async def get_task_report(
    task_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Read an existing comprehensive report for a task without triggering regeneration.
    """
    result = await db.execute(select(Task).filter(Task.id == task_id))
    task = result.scalars().first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    try:
        service = ReportService()
        report = await service.get_cached_report(task_id)
        return {"report": report}
    except Exception as e:
        logger.error(f"Failed to get cached report: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/analysis/report/{task_id}/pdf")
async def export_analysis_report_pdf(task_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Task).filter(Task.id == task_id))
    task = result.scalars().first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    service = ReportService()
    report_result = await service.generate_task_report(task_id)
    if report_result.get("error"):
        raise HTTPException(status_code=500, detail=report_result["error"])

    filename = report_result.get(
        "filename",
        f"report_{task.keyword}_{datetime.now().strftime('%Y%m%d')}.pdf",
    )
    return StreamingResponse(
        io.BytesIO(report_result["content"]),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={quote(filename)}"},
    )

@app.get("/api/tasks/{task_id}", response_model=TaskDetail)
async def get_task_detail(task_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Task).filter(Task.id == task_id))
    task = result.scalars().first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # Get stats
    # Post count
    post_count_res = await db.execute(select(func.count(Post.id)).filter(Post.task_id == task_id))
    post_count = post_count_res.scalar()
    
    # Comment count
    comment_count_res = await db.execute(
        select(func.count(Comment.id)).join(Post).filter(Post.task_id == task_id)
    )
    comment_count = comment_count_res.scalar()
    
    # Sentiment distribution
    ar_res = await db.execute(select(AnalysisResult).filter(AnalysisResult.task_id == task_id))
    ar = ar_res.scalars().first()
    
    sentiment_dist = {'positive': 0, 'neutral': 0, 'negative': 0}
    if ar and ar.sentiment_distribution:
        sentiment_dist = json.loads(ar.sentiment_distribution) if isinstance(ar.sentiment_distribution, str) else ar.sentiment_distribution
    
    # Construct flat response for TaskDetail
    task_data = {c.name: getattr(task, c.name) for c in task.__table__.columns}
    task_data["sentiment_distribution"] = sentiment_dist
    task_data["post_count_actual"] = post_count
    task_data["comment_count_actual"] = comment_count
    
    return task_data

@app.post("/api/tasks/{task_id}/action")
async def task_action(
    task_id: int, 
    action: TaskAction, 
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Task).filter(Task.id == task_id))
    task = result.scalars().first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if action.action in ('retry', 'restart'):
        await stop_task_process(task_id)
        task.status = 'pending'
        task.progress = 0.0
        task.progress_message = None
        task.completed_at = None
        await db.commit()
        background_tasks.add_task(run_task_logic, task.id)
        return {"message": "Task retry initiated"}
    elif action.action == 'pause':
        task.status = 'paused'
        task.progress_message = '任务已暂停'
        await db.commit()
        await stop_task_process(task_id)
        return {"message": "Task paused"}
    elif action.action == 'resume':
        await stop_task_process(task_id)
        task.status = 'pending'
        task.progress_message = None
        task.completed_at = None
        await db.commit()
        background_tasks.add_task(run_task_logic, task.id)
        return {"message": "Task resumed"}
    elif action.action == 'stop':
        task.status = 'failed'
        task.progress_message = 'Stopped by user'
        await db.commit()
        await stop_task_process(task_id)
        return {"message": "Task marked as stopped"}
    elif action.action == 'delete':
        await stop_task_process(task_id)
        await db.delete(task)
        await db.commit()
        await DashboardService.refresh_total_collected_cache(db)
        return {"message": "Task deleted"}
    
    raise HTTPException(status_code=400, detail="Invalid action")

@app.get("/api/settings")
async def get_settings(db: AsyncSession = Depends(get_db)):
    return await build_settings_response(db)

@app.post("/api/settings")
async def update_settings(settings: SettingsUpdate, db: AsyncSession = Depends(get_db)):
    if settings.key not in DEFAULT_SETTINGS:
        raise HTTPException(status_code=400, detail=f"Unsupported settings key: {settings.key}")

    if not isinstance(settings.value, dict):
        raise HTTPException(status_code=400, detail="Settings value must be a JSON object")

    current_value = await get_setting_value(db, settings.key)
    next_value = settings.value
    if settings.key == "llm":
        next_value = preserve_secret_fields(current_value, next_value, ["api_key"])
    merged_value = merge_dict_values(current_value, next_value)
    await save_setting_value(db, settings.key, merged_value, description=f"{settings.key} settings")
    response_value = sanitize_llm_settings(merged_value) if settings.key == "llm" else merged_value
    return {
        "message": "Settings updated",
        "key": settings.key,
        "value": response_value,
    }


@app.post("/api/settings/platform-cookie")
async def update_platform_cookie(
    payload: PlatformCookieUpdate,
    db: AsyncSession = Depends(get_db),
):
    platform_config = await get_setting_value(db, "platform")
    if payload.platform not in platform_config:
        raise HTTPException(status_code=400, detail=f"Unsupported platform: {payload.platform}")

    try:
        normalized = normalize_cookie_content(payload.cookie_content)
        cookie_path = get_cookie_file_path(payload.platform)
        cookie_path.write_text(str(normalized["content"]), encoding="utf-8")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        logger.error(f"Failed to save cookie for {payload.platform}: {exc}")
        raise HTTPException(status_code=500, detail="保存 Cookie 文件失败") from exc

    return {
        "message": f"{payload.platform} Cookie 更新成功",
        "platform": payload.platform,
        "cookie_status": read_platform_cookie_status([payload.platform])[payload.platform],
    }

# Analysis Data Preview Routes
@app.get("/api/analysis/preview/{task_id}", response_model=DataPreviewResponse)
async def get_data_preview(
    task_id: int, 
    type: str = "posts", 
    sentiment: Optional[str] = None,
    page: int = 1, 
    page_size: int = 10, 
    db: AsyncSession = Depends(get_db)
):
    offset = (page - 1) * page_size
    
    if type == "comments":
        query = select(Comment).join(Post).filter(Post.task_id == task_id)
        if sentiment:
            query = query.join(Sentiment).filter(Sentiment.sentiment_label == sentiment)
        
        count_res = await db.execute(select(func.count()).select_from(query.subquery()))
        total = count_res.scalar() or 0
        
        result = await db.execute(query.offset(offset).limit(page_size))
        comments = result.scalars().all()
        
        data_items = []
        for c in comments:
            # Get sentiment
            sent_res = await db.execute(select(Sentiment).filter(Sentiment.comment_id == c.id))
            sent = sent_res.scalars().first()
            
            data_items.append({
                "id": c.id,
                "content": c.content,
                "author": c.author,
                "time": c.comment_time,
                "likes": c.likes,
                "sentiment": {
                    "label": sent.sentiment_label if sent else None,
                    "score": sent.confidence if sent else None
                } if sent else None
            })
    else:
        query = select(Post).filter(Post.task_id == task_id)
        # Note: Posts don't have direct sentiment, it's aggregated from comments.
        # But if we want to filter posts by sentiment, it's ambiguous. 
        # Usually preview shows posts or comments.
        
        count_res = await db.execute(select(func.count(Post.id)).filter(Post.task_id == task_id))
        total = count_res.scalar() or 0
        
        result = await db.execute(query.offset(offset).limit(page_size))
        posts = result.scalars().all()
        
        data_items = []
        for p in posts:
            data_items.append({
                "id": p.id,
                "content": p.content,
                "author": p.author,
                "time": p.post_time,
                "likes": p.likes,
                "comments_count": p.comments_count
            })
    
    pages = (total + page_size - 1) // page_size if page_size > 0 else 0
    
    return {
        "items": data_items, 
        "total": total,
        "page": page,
        "per_page": page_size,
        "pages": pages
    }

@app.get("/api/analysis/sentiment/{task_id}", response_model=SentimentAnalysisResponse)
async def get_sentiment_analysis(task_id: int, db: AsyncSession = Depends(get_db)):
    # Check result table
    ar_res = await db.execute(select(AnalysisResult).filter(AnalysisResult.task_id == task_id))
    ar = ar_res.scalars().first()
    
    distribution = {'positive': 0, 'neutral': 0, 'negative': 0}
    trend = []
    
    if ar:
        if ar.sentiment_distribution:
             dist_data = json.loads(ar.sentiment_distribution) if isinstance(ar.sentiment_distribution, str) else ar.sentiment_distribution
             if isinstance(dist_data, dict):
                 distribution.update(dist_data)
        
        if ar.trend_data:
             trend = json.loads(ar.trend_data) if isinstance(ar.trend_data, str) else ar.trend_data
             
    # Map keys to match schema
    sentiment_distribution_list = [
        {"label": k, "count": v, "confidence": 0.0} 
        for k, v in distribution.items()
    ]
    
    # Simple fallback trend if empty
    if not trend:
        # Check if we have at least some data to show
        has_data = any(v > 0 for v in distribution.values())
        if has_data:
            trend = [
                {
                    "date": datetime.now().strftime("%Y-%m-%d"), 
                    "positive": distribution.get('positive', 0), 
                    "neutral": distribution.get('neutral', 0), 
                    "negative": distribution.get('negative', 0)
                }
            ]
        else:
            trend = []

    return {
        "sentiment_distribution": sentiment_distribution_list,
        "trend_data": trend
    }

@app.get("/api/analysis/wordcloud/{task_id}", response_model=WordCloudResponse)
async def get_wordcloud(
    task_id: int, 
    source_type: str = "all",
    db: AsyncSession = Depends(get_db)
):
    ar_res = await db.execute(select(AnalysisResult).filter(AnalysisResult.task_id == task_id))
    ar = ar_res.scalars().first()
    
    words = []
    if ar and ar.word_cloud:
        data = json.loads(ar.word_cloud) if isinstance(ar.word_cloud, str) else ar.word_cloud
        if isinstance(data, dict):
            words = data.get(source_type, data.get("all", []))
        else:
            words = data # Fallback for old data structure
            
    return {"words": words}

from app.services.text_analysis import TextAnalysisService

@app.get("/api/analysis/lda/{task_id}", response_model=LDAResponse)
async def get_lda_analysis(
    task_id: int, 
    source_type: str = "all",
    num_topics: int = 5,
    db: AsyncSession = Depends(get_db)
):
    # 尝试先从缓存（AnalysisResult表）读取
    ar_res = await db.execute(select(AnalysisResult).filter(AnalysisResult.task_id == task_id))
    ar = ar_res.scalars().first()
    
    # 如果请求的主题数与缓存一致，且缓存存在，则直接返回
    # 但为了确保参数“有效”，我们在这里增加实时计算逻辑，或者根据参数判断是否重新计算
    
    # 逻辑：如果用户指定了非默认的主题数，或者数据库里还没存，我们就实时算一遍
    # 这样既能保证参数有效，也能处理初始化数据
    
    topics = []
    need_recompute = True
    
    if ar and ar.lda_topics:
        data = json.loads(ar.lda_topics) if isinstance(ar.lda_topics, str) else ar.lda_topics
        if isinstance(data, dict):
            cached_topics = data.get(source_type, [])
            # 如果缓存的主题数量正好等于请求的数量，就不重算了
            if len(cached_topics) == num_topics:
                topics = cached_topics
                need_recompute = False
    
    if need_recompute:
        logger.info(f"Recomputing LDA for task {task_id} with {num_topics} topics (source: {source_type})")
        text_service = TextAnalysisService()
        
        texts = []
        if source_type == "posts" or source_type == "all":
            p_res = await db.execute(select(Post.content).filter(Post.task_id == task_id))
            texts.extend([c for c in p_res.scalars().all() if c])
            
        if source_type == "comments" or source_type == "all":
            c_res = await db.execute(select(Comment.content).join(Post).filter(Post.task_id == task_id))
            texts.extend([c for c in c_res.scalars().all() if c])
            
        if texts:
            topics = text_service.perform_lda_analysis(texts, n_topics=num_topics)
            # 可选：更新缓存以提升下次速度
            # if ar: ... (此处暂时只返回不更新，保证响应速度)
            
    return {"topics": topics}

@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Task).filter(Task.id == task_id))
    task = result.scalars().first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    await stop_task_process(task_id)
    await db.delete(task)
    await db.commit()
    await DashboardService.refresh_total_collected_cache(db)
    return {"message": "Task deleted"}

# QA / Chat Routes
async def get_qa_context_docs(task_id: int, db: AsyncSession):
    """Fetch task data and format for LLM context"""
    docs = []
    
    # 先组织任务元信息与分析汇总，此类内容作为固定上下文参与问答，
    # 用于向模型提供稳定的任务背景与总体分析结果。
    # 1. Get Task and Analysis Result
    task_res = await db.execute(select(Task).filter(Task.id == task_id))
    task = task_res.scalars().first()
    if not task:
        return docs
        
    ar_res = await db.execute(select(AnalysisResult).filter(AnalysisResult.task_id == task_id))
    ar = ar_res.scalars().first()
    
    # Add metadata
    docs.append({
        'title': f'任务信息: {task.keyword}',
        'content': f'平台: {task.platform}, 关键词: {task.keyword}, 状态: {task.status}',
        'type': 'metadata'
    })
    
    if ar:
        docs.append({
            'title': '情感分析汇总',
            'content': ar.summary or "暂无摘要",
            'type': 'analysis'
        })
        if ar.sentiment_distribution:
            dist = json.loads(ar.sentiment_distribution) if isinstance(ar.sentiment_distribution, str) else ar.sentiment_distribution
            docs.append({
                'title': '情感分布数据',
                'content': f'正面: {dist.get("positive", 0)}, 中性: {dist.get("neutral", 0)}, 负面: {dist.get("negative", 0)}',
                'type': 'analysis_result'
            })

    # 原始文本规模可能较大，因此这里只选取部分代表性帖子与评论，
    # 以控制上下文长度，并为后续检索提供更有效的候选文本。
    # 2. Get some sample posts and comments
    # We can't fetch all if there are thousands, so we fetch top/recent ones
    posts_res = await db.execute(select(Post).filter(Post.task_id == task_id).limit(10))
    posts = posts_res.scalars().all()
    for p in posts:
        docs.append({
            'title': f'帖子 (作者: {p.author})',
            'content': p.content,
            'type': 'post'
        })
        
    # Get comments with their sentiments
    comments_res = await db.execute(
        select(Comment, Sentiment)
        .join(Sentiment, isouter=True)
        .join(Post)
        .filter(Post.task_id == task_id)
        .limit(30)
    )
    for c, s in comments_res:
        sentiment_info = f" [情感: {s.sentiment_label}]" if s else ""
        docs.append({
            'title': f'评论 (作者: {c.author}){sentiment_info}',
            'content': c.content,
            'type': 'comment'
        })
        
    return docs


@app.post("/api/agent/chat", response_model=AgentChatResponse)
async def agent_chat(request: AgentChatRequest, db: AsyncSession = Depends(get_db)):
    # Agent 层只做调度，不改动现有采集、分析和问答主链路。
    llm_config = await get_llm_runtime_config(db)
    agent_config = await get_setting_value(db, "agent")
    agent = OpinionAgent(db=db, llm_config=llm_config, agent_config=agent_config)
    result = await agent.run_detail(request.query, request.session_id)
    return result

@app.post("/api/qa", response_model=QAResponse)
async def qa_chat(request: QARequest, db: AsyncSession = Depends(get_db)):
    llm_config = await get_llm_runtime_config(db)
    qa_service = LLMQuestionAnswering(
        api_key=llm_config.get("api_key", ""),
        api_base=llm_config.get("api_base"),
        model=llm_config.get("model", "qwen-plus"),
    )
    
    if request.context_task_id:
        context_docs = await get_qa_context_docs(request.context_task_id, db)
        qa_service.set_context_documents(context_docs)
        
    answer = await qa_service.answer_question(request.question, use_context=True)
    return {"answer": answer, "sources": []}

@app.post("/api/qa/stream")
async def qa_stream(request: QARequest, db: AsyncSession = Depends(get_db)):
    llm_config = await get_llm_runtime_config(db)
    qa_service = LLMQuestionAnswering(
        api_key=llm_config.get("api_key", ""),
        api_base=llm_config.get("api_base"),
        model=llm_config.get("model", "qwen-plus"),
    )
    
    if request.context_task_id:
        context_docs = await get_qa_context_docs(request.context_task_id, db)
        qa_service.set_context_documents(context_docs)
    
    async def generate():
        async for chunk in qa_service.stream_answer_question(request.question, use_context=True):
            yield chunk

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

# ... imports ...

# Hot Topic Routes
@app.get("/api/hot-topics/sources")
async def get_hot_topic_sources():
    return get_supported_sources()

@app.get("/api/hot-topics", response_model=HotTopicListResponse)
async def get_hot_topics(
    source: str = Query("weibo", description="Source of hot topics"),
    limit: int = 50,
    db: AsyncSession = Depends(get_db)
):
    items = await get_latest_hot_topics(source, limit)
    updated_at = items[0].created_at if items else None
    return {"items": items, "source": source, "updated_at": updated_at}

@app.post("/api/hot-topics/settings")
async def update_hot_topic_settings(
    settings: HotTopicSettings,
    db: AsyncSession = Depends(get_db)
):
    # Update scheduler job for all sources
    for source_id in SUPPORTED_SOURCES.keys():
        job_id = f"fetch_hot_topics_{source_id}"
        if scheduler.get_job(job_id):
            scheduler.reschedule_job(
                job_id, 
                trigger=IntervalTrigger(minutes=settings.interval_minutes)
            )
        else:
            # If job doesn't exist, create it
             scheduler.add_job(
                update_hot_topics_task, 
                trigger=IntervalTrigger(minutes=settings.interval_minutes), 
                id=job_id, 
                replace_existing=True,
                args=[source_id]
            )
            
    return {"message": f"Settings updated, interval set to {settings.interval_minutes} minutes"}

@app.post("/api/hot-topics/refresh")
async def refresh_hot_topics(
    source: Optional[str] = Query(None, description="Source to refresh, if None refresh all"),
    background_tasks: BackgroundTasks = None
):
    if background_tasks is None:
        background_tasks = BackgroundTasks()
    if source:
        background_tasks.add_task(update_hot_topics_task, source)
        msg = f"Refresh started for {source}"
    else:
        for source_id in SUPPORTED_SOURCES.keys():
            background_tasks.add_task(update_hot_topics_task, source_id)
        msg = "Refresh started for all sources"
        
    return {"message": msg}

@app.post("/api/hot-topics/analyze", response_model=HotTopicAnalysisResponse)
async def analyze_hot_topic(request: HotTopicAnalysisRequest):
    report_service = ReportService()
    result = await report_service.generate_hot_topic_analysis(
        title=request.title,
        summary=request.summary,
        extra_data={'url': request.url, 'source': request.source}
    )
    return result

@app.post("/api/hot-topics/export")
async def export_hot_topic(request: ExportRequest):
    report_service = ReportService()
    try:
        file_bytes = report_service.export_hot_topic_report(
            title=request.title,
            summary=request.summary,
            analysis=request.analysis,
            format=request.format
        )
        
        filename = f"report_{datetime.now().strftime('%Y%m%d%H%M')}.{request.format}"
        if request.format == 'word':
            filename = filename.replace('.word', '.docx')
            media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        else:
            media_type = "application/pdf"
            
        return StreamingResponse(
            io.BytesIO(file_bytes),
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={quote(filename)}"}
        )
    except Exception as e:
        logger.error(f"Export failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
