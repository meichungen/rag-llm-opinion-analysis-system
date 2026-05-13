from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional, Dict, Any, Union, Literal
from datetime import datetime

class TaskBase(BaseModel):
    platform: Literal["weibo", "douyin", "bilibili"]
    keyword: str
    post_count: int = Field(default=100, ge=1, le=1000)
    comment_count: int = Field(default=1000, ge=1, le=10000)

class TaskCreate(TaskBase):
    user_id: Optional[int] = 1

class Task(TaskBase):
    id: int
    user_id: int
    status: str
    progress: float
    progress_message: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Additional fields for list view
    sentiment_distribution: Optional[Dict[str, int]] = None

    model_config = ConfigDict(from_attributes=True)

class TaskDetail(Task):
    # Additional fields for detail view
    post_count_actual: Optional[int] = None # Renamed to avoid conflict with config
    comment_count_actual: Optional[int] = None
    warnings: Optional[List[Dict[str, Any]]] = None
    risk_fingerprints: Optional[List[Dict[str, Any]]] = None
    diagnostics: Optional[Dict[str, Any]] = None
    
class TaskListResponse(BaseModel):
    tasks: List[Task]
    total: int

class PostBase(BaseModel):
    id: int
    content: Optional[str] = None
    author: Optional[str] = None
    time: Optional[Union[datetime, str]] = None
    likes: int = 0
    comments_count: int = 0

class CommentBase(BaseModel):
    id: int
    content: Optional[str] = None
    author: Optional[str] = None
    time: Optional[Union[datetime, str]] = None
    likes: int = 0
    sentiment: Optional[Dict[str, Any]] = None

class DataPreviewResponse(BaseModel):
    items: List[Union[PostBase, CommentBase]]
    total: int
    page: int
    per_page: int
    pages: int

class KeywordWeight(BaseModel):
    name: str
    weight: float

class Topic(BaseModel):
    id: int
    keywords: List[KeywordWeight]

class LDAResponse(BaseModel):
    topics: List[Topic]

class SentimentStat(BaseModel):
    label: str
    count: int
    confidence: float

class SentimentTrend(BaseModel):
    date: str
    positive: int = 0
    neutral: int = 0
    negative: int = 0

class SentimentAnalysisResponse(BaseModel):
    sentiment_distribution: List[SentimentStat]
    trend_data: List[SentimentTrend]

class WordCloudItem(BaseModel):
    name: str
    value: int

class WordCloudResponse(BaseModel):
    words: List[WordCloudItem]

class TaskAction(BaseModel):
    action: str


class DashboardMetricsResponse(BaseModel):
    totalCollected: int
    activeTasks: int
    todayNewTasks: int

class SettingsUpdate(BaseModel):
    key: str
    value: Any


class PlatformCookieUpdate(BaseModel):
    platform: str
    cookie_content: str

class QARequest(BaseModel):
    question: str
    context_task_id: Optional[int] = None
    history: Optional[List[Dict[str, str]]] = None

class QAResponse(BaseModel):
    answer: str
    sources: Optional[List[Any]] = None
    error: Optional[str] = None
    suggestion: Optional[str] = None


class AgentChatRequest(BaseModel):
    query: str
    session_id: str


class AgentChatResponse(BaseModel):
    answer: str
    used_tool: str
    decision_summary: Optional[str] = None
    observation_summary: Optional[str] = None
    short_memory_turns: Optional[int] = None
    long_memory_hits: Optional[int] = None
    tool_observation: Optional[Dict[str, Any]] = None

class HotTopicBase(BaseModel):
    source: str
    title: str
    url: Optional[str] = None
    rank: Optional[int] = None
    hot_value: Optional[str] = None
    extra_data: Optional[Dict[str, Any]] = None

class HotTopic(HotTopicBase):
    id: int
    created_at: datetime
    batch_id: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)

class HotTopicListResponse(BaseModel):
    items: List[HotTopic]
    source: str
    updated_at: Optional[datetime] = None

class HotTopicSettings(BaseModel):
    interval_minutes: int

class HotTopicAnalysisRequest(BaseModel):
    title: str
    summary: Optional[str] = None
    url: Optional[str] = None
    source: Optional[str] = None

class HotTopicAnalysisResponse(BaseModel):
    summary: str
    analysis: str

class ExportRequest(BaseModel):
    title: str
    summary: str
    analysis: str
    format: str
