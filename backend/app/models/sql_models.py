from sqlalchemy import BigInteger, Column, DateTime, Enum, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import relationship
from app.core.database import Base

class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(Enum('user', 'admin'), default='user')
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    tasks = relationship('Task', back_populates='user')

class HotTopic(Base):
    __tablename__ = 'hot_topics'
    
    id = Column(Integer, primary_key=True)
    source = Column(String(50), nullable=False) # e.g., 'weibo', 'zhihu'
    title = Column(String(255), nullable=False)
    url = Column(String(500), nullable=True)
    rank = Column(Integer, nullable=True)
    hot_value = Column(String(50), nullable=True)
    extra_data = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=func.now())
    batch_id = Column(String(100), nullable=True) # To group fetches by timestamp/batch


class Task(Base):
    __tablename__ = 'tasks'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    platform = Column(String(20), nullable=False)
    keyword = Column(String(200), nullable=False)
    post_count = Column(Integer, default=100)
    comment_count = Column(Integer, default=1000)
    status = Column(Enum('pending', 'running', 'completed', 'failed', 'paused'), default='pending')
    progress = Column(Float, default=0.0)
    progress_message = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=func.now())
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index('ix_tasks_status', 'status'),
        Index('ix_tasks_created_at', 'created_at'),
    )
    
    user = relationship('User', back_populates='tasks')
    posts = relationship('Post', back_populates='task', cascade="all, delete-orphan")
    analysis_result = relationship('AnalysisResult', back_populates='task', uselist=False, cascade="all, delete-orphan")

class Post(Base):
    __tablename__ = 'posts'
    
    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey('tasks.id'), nullable=False)
    platform_post_id = Column(String(100), nullable=False)
    platform = Column(String(20), nullable=False)
    content = Column(Text)
    author = Column(String(100))
    post_time = Column(DateTime)
    likes = Column(Integer, default=0)
    comments_count = Column(Integer, default=0)
    shares = Column(Integer, default=0)
    views = Column(Integer, default=0)
    created_at = Column(DateTime, default=func.now())
    
    # 移除 UniqueConstraint 以支持多个任务共享或抓取相同内容
    # __table_args__ = (UniqueConstraint('platform', 'platform_post_id', name='unique_platform_post'),)
    
    task = relationship('Task', back_populates='posts')
    comments = relationship('Comment', back_populates='post', cascade="all, delete-orphan")

class Comment(Base):
    __tablename__ = 'comments'
    
    id = Column(Integer, primary_key=True)
    post_id = Column(Integer, ForeignKey('posts.id'), nullable=False)
    platform_comment_id = Column(String(100), nullable=False)
    content = Column(Text)
    author = Column(String(100))
    comment_time = Column(DateTime)
    likes = Column(Integer, default=0)
    created_at = Column(DateTime, default=func.now())
    
    post = relationship('Post', back_populates='comments')
    sentiment = relationship('Sentiment', back_populates='comment', uselist=False, cascade="all, delete-orphan")

class Sentiment(Base):
    __tablename__ = 'sentiments'
    
    id = Column(Integer, primary_key=True)
    comment_id = Column(Integer, ForeignKey('comments.id'), nullable=False)
    sentiment_label = Column(Enum('positive', 'neutral', 'negative'), nullable=False)
    confidence = Column(Float, nullable=False)
    model_version = Column(String(100), nullable=False)
    analyzed_at = Column(DateTime, default=func.now())
    
    __table_args__ = (UniqueConstraint('comment_id', name='unique_comment_sentiment'),)
    
    comment = relationship('Comment', back_populates='sentiment')

class AnalysisResult(Base):
    __tablename__ = 'analysis_results'
    
    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey('tasks.id'), nullable=False)
    sentiment_distribution = Column(JSON)
    trend_data = Column(JSON)
    word_cloud = Column(JSON)
    lda_topics = Column(JSON)
    summary = Column(Text)
    generated_at = Column(DateTime, default=func.now())
    
    __table_args__ = (UniqueConstraint('task_id', name='unique_task_result'),)
    
    task = relationship('Task', back_populates='analysis_result')

class SystemConfig(Base):
    __tablename__ = 'system_configs'
    
    id = Column(Integer, primary_key=True)
    key = Column(String(50), unique=True, nullable=False)
    value = Column(JSON, nullable=False)
    description = Column(String(200))
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class DashboardMetricCache(Base):
    __tablename__ = 'dashboard_metric_caches'

    id = Column(Integer, primary_key=True)
    cache_key = Column(String(100), unique=True, nullable=False)
    metric_value = Column(BigInteger, nullable=False, default=0)
    refreshed_at = Column(DateTime, default=func.now(), nullable=False)
