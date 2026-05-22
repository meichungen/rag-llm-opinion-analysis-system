from typing import Any, Awaitable, Callable, Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.crawler_tools import analyze_crawled_data, crawl_platform
from app.agent.retriever import RagRetriever
from app.models.sql_models import AnalysisResult, Comment, Post, Task
from app.sentiment.analyzer import SentimentAnalyzer
from app.services.text_analysis import TextAnalysisService


ToolRiskLevel = Literal["low", "medium", "high"]


class SentimentAnalysisParams(BaseModel):
    text: str = Field(..., min_length=1, description="需要分析情感的文本")


class FetchDataParams(BaseModel):
    keyword: str = Field(..., min_length=1, description="任务关键词")
    platform: Literal["weibo", "douyin", "bilibili"] = Field(..., description="平台")


class TopicModelingParams(FetchDataParams):
    pass


class VectorSearchParams(BaseModel):
    query: str = Field(..., min_length=1, description="检索查询")
    top_k: int = Field(default=3, ge=1, le=10, description="返回结果数")


class CrawlDataParams(BaseModel):
    platform: Literal["weibo", "douyin", "bilibili"] = Field(..., description="平台")
    keyword: str = Field(..., min_length=1, description="采集关键词")
    post_count: int = Field(default=10, ge=1, le=100, description="目标采集帖子数")
    comment_count: int = Field(default=10, ge=1, le=500, description="目标采集评论总数")


class SummarizeCrawledDataParams(BaseModel):
    data: Dict[str, Any] = Field(..., description="crawl_data 返回的数据")


class ToolSpec(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str
    parameters_model: type[BaseModel]
    risk_level: ToolRiskLevel = "low"
    requires_confirmation: bool = False
    function: Callable[..., Awaitable[Dict[str, Any]]]

    def parameters_schema(self) -> Dict[str, Any]:
        return self.parameters_model.model_json_schema()


def tool(
    description: str,
    *,
    parameters_model: type[BaseModel],
    risk_level: ToolRiskLevel = "low",
    requires_confirmation: bool = False,
) -> Callable:
    def decorator(func: Callable[..., Awaitable[Dict[str, Any]]]) -> Callable:
        func._is_tool = True
        func._description = description
        func._parameters_model = parameters_model
        func._parameters_schema = parameters_model.model_json_schema()
        func._risk_level = risk_level
        func._requires_confirmation = requires_confirmation
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
        return {spec.name: spec.function for spec in self.list_tool_specs().values()}

    def list_tool_specs(self) -> Dict[str, ToolSpec]:
        specs: Dict[str, ToolSpec] = {}
        for name in dir(self):
            func = getattr(self.__class__, name, None)
            if not getattr(func, "_is_tool", False):
                continue
            bound = getattr(self, name)
            specs[name] = ToolSpec(
                name=name,
                description=getattr(func, "_description", ""),
                parameters_model=getattr(func, "_parameters_model"),
                risk_level=getattr(func, "_risk_level", "low"),
                requires_confirmation=getattr(func, "_requires_confirmation", False),
                function=bound,
            )
        return specs

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
        "对单条文本做情感分析，返回 sentiment、confidence 和 probabilities。",
        parameters_model=SentimentAnalysisParams,
        risk_level="low",
    )
    async def sentiment_analysis(self, text: str) -> Dict[str, Any]:
        return self.analyzer.predict(text)

    @tool(
        "按关键词和平台查询已采集数据，返回任务摘要、情感分布和样本文本。",
        parameters_model=FetchDataParams,
        risk_level="low",
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
        "按关键词和平台执行主题建模，返回 LDA topics 列表。",
        parameters_model=TopicModelingParams,
        risk_level="medium",
    )
    async def topic_modeling(self, keyword: str, platform: str) -> Dict[str, Any]:
        texts = await self._load_task_texts(keyword, platform)
        topics = self.text_service.perform_lda_analysis(texts, n_topics=5)
        if not topics:
            raise ValueError("当前文本不足以生成主题结果。")
        return {"keyword": keyword, "platform": platform, "topics": topics}

    @tool(
        "轻量级长期记忆检索，返回最相关任务摘要和文本片段。",
        parameters_model=VectorSearchParams,
        risk_level="low",
    )
    async def vector_search(self, query: str, top_k: int = 3) -> Dict[str, Any]:
        return await self._retriever.search(query=query, top_k=top_k)

    @tool(
        "实时采集社交媒体数据，直接调用爬虫系统，返回帖子和评论数据。",
        parameters_model=CrawlDataParams,
        risk_level="high",
        requires_confirmation=True,
    )
    async def crawl_data(
        self, platform: str, keyword: str, post_count: int = 10, comment_count: int = 10
    ) -> Dict[str, Any]:
        return await crawl_platform(
            platform,
            keyword,
            post_count,
            comment_count,
            platform_settings=self.config.get("platform_settings"),
        )

    @tool(
        "对已采集的社交媒体数据进行预处理摘要，提取样本数据用于后续分析。",
        parameters_model=SummarizeCrawledDataParams,
        risk_level="low",
    )
    async def summarize_crawled_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return await analyze_crawled_data(data)
