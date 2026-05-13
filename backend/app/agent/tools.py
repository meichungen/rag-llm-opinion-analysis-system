from typing import Any, Awaitable, Callable, Dict, List

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.retriever import RagRetriever
from app.agent.crawler_tools import crawl_platform, analyze_crawled_data
from app.models.sql_models import AnalysisResult, Comment, Post, Task
from app.sentiment.analyzer import SentimentAnalyzer
from app.services.text_analysis import TextAnalysisService


def tool(description: str) -> Callable:
    def decorator(func: Callable[..., Awaitable[Dict[str, Any]]]) -> Callable:
        func._is_tool = True
        func._description = description
        return func

    return decorator


class AgentTools:
    def __init__(self, db: AsyncSession, config: Dict[str, Any] | None = None):
        self.db = db
        self.config = config or {}
        self._analyzer: SentimentAnalyzer | None = None
        self._text_service: TextAnalysisService | None = None
        self._retriever = RagRetriever(db, self.config)

    @property
    def analyzer(self) -> SentimentAnalyzer:
        if self._analyzer is None:
            self._analyzer = SentimentAnalyzer()
        return self._analyzer

    @property
    def text_service(self) -> TextAnalysisService:
        if self._text_service is None:
            self._text_service = TextAnalysisService()
        return self._text_service

    def list_tools(self) -> Dict[str, Callable[..., Awaitable[Dict[str, Any]]]]:
        tools: Dict[str, Callable[..., Awaitable[Dict[str, Any]]]] = {}
        for name in dir(self):
            func = getattr(self.__class__, name, None)
            if getattr(func, "_is_tool", False):
                tools[name] = getattr(self, name)
        return tools

    async def _load_task_texts(self, keyword: str, platform: str) -> List[str]:
        task_stmt = (
            select(Task.id)
            .where(Task.keyword.like(f"%{keyword}%"), Task.platform == platform)
            .order_by(desc(Task.created_at))
            .limit(1)
        )
        task_id = (await self.db.execute(task_stmt)).scalar_one_or_none()
        if not task_id:
            raise ValueError("未找到匹配的采集任务，请先完成对应关键词任务。")
        post_stmt = select(Post.content).where(Post.task_id == task_id)
        comment_stmt = select(Comment.content).join(Post).where(Post.task_id == task_id)
        posts = [text for text in (await self.db.execute(post_stmt)).scalars().all() if text]
        comments = [text for text in (await self.db.execute(comment_stmt)).scalars().all() if text]
        texts = posts + comments
        if not texts:
            raise ValueError("任务存在，但暂无可分析文本。")
        return texts

    @tool(
        "对单条文本做情感分析。参数: text(str)。返回: sentiment/confidence/probabilities。"
    )
    async def sentiment_analysis(self, text: str) -> Dict[str, Any]:
        return self.analyzer.predict(text)

    @tool(
        "按关键词和平台查询已采集数据。参数: keyword(str), platform(str)。返回任务摘要与样本文本。"
    )
    async def fetch_data(self, keyword: str, platform: str) -> Dict[str, Any]:
        stmt = (
            select(Task, AnalysisResult)
            .join(AnalysisResult, AnalysisResult.task_id == Task.id, isouter=True)
            .where(Task.keyword.like(f"%{keyword}%"), Task.platform == platform)
            .order_by(desc(Task.created_at))
            .limit(1)
        )
        row = (await self.db.execute(stmt)).first()
        if not row:
            raise ValueError("未找到匹配的数据任务。")
        task, result = row
        posts = (
            await self.db.execute(select(Post.content).where(Post.task_id == task.id).limit(3))
        ).scalars().all()
        comments = (
            await self.db.execute(
                select(Comment.content).join(Post).where(Post.task_id == task.id).limit(3)
            )
        ).scalars().all()
        return {
            "task_id": task.id,
            "keyword": task.keyword,
            "platform": task.platform,
            "status": task.status,
            "summary": result.summary if result else "",
            "sentiment_distribution": result.sentiment_distribution if result else {},
            "sample_posts": [item for item in posts if item],
            "sample_comments": [item for item in comments if item],
        }

    @tool(
        "按关键词和平台执行主题建模。参数: keyword(str), platform(str)。返回 LDA topics 列表。"
    )
    async def topic_modeling(self, keyword: str, platform: str) -> Dict[str, Any]:
        texts = await self._load_task_texts(keyword, platform)
        topics = self.text_service.perform_lda_analysis(texts, n_topics=5)
        if not topics:
            raise ValueError("当前文本不足以生成主题结果。")
        return {"keyword": keyword, "platform": platform, "topics": topics}

    @tool(
        "轻量级长期记忆检索。参数: query(str), top_k(int=3)。返回最相关任务摘要和文本片段。"
    )
    async def vector_search(self, query: str, top_k: int = 3) -> Dict[str, Any]:
        return await self._retriever.search(query=query, top_k=top_k)

    @tool(
        "实时爬取社交媒体数据。参数: platform(str: bilibili/weibo/douyin), keyword(str), post_count(int=10), comment_count(int=10)。直接调用你的爬虫系统，返回帖子和评论数据。"
    )
    async def crawl_data(self, platform: str, keyword: str, post_count: int = 10, comment_count: int = 10) -> Dict[str, Any]:
        return await crawl_platform(
            platform,
            keyword,
            post_count,
            comment_count,
            platform_settings=self.config.get("platform_settings"),
        )

    @tool(
        "对已爬取的社交媒体数据进行预处理摘要。参数: data(dict)。分析爬取结果，提取样本数据用于后续分析。"
    )
    async def summarize_crawled_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return await analyze_crawled_data(data)
