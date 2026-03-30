"""AutoReels Pro v10 — Production Database Schema"""

from sqlalchemy import (
    Column, String, Integer, Float, DateTime, Boolean, JSON, Text,
    ForeignKey, Index, create_engine, event
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

Base = declarative_base()

class Video(Base):
    """Source YouTube video"""
    __tablename__ = "videos"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    youtube_id = Column(String(20), unique=True, index=True)
    title = Column(String(500))
    channel_id = Column(String(50))
    duration_seconds = Column(Integer)
    upload_timestamp = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime)
    status = Column(String(50), default="pending")  # pending, processing, done, failed
    error_message = Column(Text)
    extra_metadata = Column(JSON, default={})
    
    clips = relationship("Clip", back_populates="video", cascade="all, delete-orphan")
    
    __table_args__ = (Index("idx_yt_id_status", "youtube_id", "status"),)

class Clip(Base):
    """Processed video clip"""
    __tablename__ = "clips"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    video_id = Column(String(36), ForeignKey("videos.id"), index=True)
    start_sec = Column(Float)
    end_sec = Column(Float)
    duration_sec = Column(Float)
    clip_type = Column(String(50))  # scene, highlight, transition
    scene_score = Column(Float, default=0.0)
    motion_score = Column(Float, default=0.0)
    audio_energy = Column(Float, default=0.0)
    
    video = relationship("Video", back_populates="clips")
    uploads = relationship("Upload", back_populates="clip", cascade="all, delete-orphan")
    scores = relationship("ClipScore", back_populates="clip", cascade="all, delete-orphan")
    
    __table_args__ = (Index("idx_video_type", "video_id", "clip_type"),)

class ClipScore(Base):
    """ML engagement scoring per clip"""
    __tablename__ = "clip_scores"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    clip_id = Column(String(36), ForeignKey("clips.id"), index=True)
    narrative_score = Column(Float, default=0.0)
    hook_quality = Column(Float, default=0.0)
    retention_potential = Column(Float, default=0.0)
    viral_index = Column(Float, default=0.0)
    
    clip = relationship("Clip", back_populates="scores")

class Hook(Base):
    """Hook phrase library with learnings"""
    __tablename__ = "hooks"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    niche = Column(String(100), index=True)
    angle = Column(String(100), index=True)
    platform = Column(String(50), index=True)
    phrase = Column(String(500))
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    retention_3s = Column(Float, default=0.0)
    engagement_rate = Column(Float, default=0.0)
    ucb1_weight = Column(Float, default=1.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (Index("idx_hook_niche_angle_platform", "niche", "angle", "platform"),)

class Upload(Base):
    """Platform upload record"""
    __tablename__ = "uploads"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    clip_id = Column(String(36), ForeignKey("clips.id"), index=True)
    platform = Column(String(50))  # facebook, tiktok, instagram, youtube, threads
    platform_post_id = Column(String(200))
    account_id = Column(String(100))
    posted_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String(50), default="live")  # live, deleted, failed
    caption = Column(Text)
    hook_used = Column(String(500))
    thumbnail_variant = Column(String(20))  # a, b, c
    
    clip = relationship("Clip", back_populates="uploads")
    metrics = relationship("PostMetric", back_populates="upload", cascade="all, delete-orphan")
    
    __table_args__ = (Index("idx_platform_post", "platform", "platform_post_id"),)

class PostMetric(Base):
    """Engagement metrics at multiple time points"""
    __tablename__ = "post_metrics"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    upload_id = Column(String(36), ForeignKey("uploads.id"), index=True)
    measured_at = Column(DateTime, default=datetime.utcnow, index=True)
    hours_since_upload = Column(Integer)
    views = Column(Integer, default=0)
    likes = Column(Integer, default=0)
    comments = Column(Integer, default=0)
    shares = Column(Integer, default=0)
    saves = Column(Integer, default=0)
    velocity = Column(Float, default=0.0)  # views/hour
    
    upload = relationship("Upload", back_populates="metrics")
    
    __table_args__ = (Index("idx_upload_measured", "upload_id", "measured_at"),)

class Comment(Base):
    """Top comments for sentiment analysis"""
    __tablename__ = "comments"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    upload_id = Column(String(36), ForeignKey("uploads.id"), index=True)
    platform_comment_id = Column(String(200))
    author = Column(String(200))
    text = Column(Text)
    sentiment = Column(String(50))  # positive, negative, question, spam, neutral
    replied = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Account(Base):
    """Social media account configuration"""
    __tablename__ = "accounts"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    platform = Column(String(50))
    account_name = Column(String(200))
    page_id = Column(String(200), unique=True)
    daily_upload_limit = Column(Integer, default=5)
    daily_uploads_today = Column(Integer, default=0)
    last_reset = Column(DateTime, default=datetime.utcnow)
    circuit_breaker_open = Column(Boolean, default=False)
    circuit_breaker_until = Column(DateTime)
    status = Column(String(50), default="active")  # active, paused, disabled
    auth_token_encrypted = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (Index("idx_platform_page", "platform", "page_id"),)

class FailedJob(Base):
    """Dead letter queue for failed uploads"""
    __tablename__ = "failed_jobs"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    clip_id = Column(String(36), ForeignKey("clips.id"))
    platform = Column(String(50))
    account_id = Column(String(100))
    error_message = Column(Text)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=5)
    next_retry_at = Column(DateTime)
    failed_at = Column(DateTime, default=datetime.utcnow)
    payload = Column(JSON)

class Schedule(Base):
    """Optimal posting times per niche/platform"""
    __tablename__ = "schedules"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    niche = Column(String(100), index=True)
    platform = Column(String(50), index=True)
    day_of_week = Column(Integer)  # 0=Monday, 6=Sunday
    hour = Column(Integer)  # 0-23
    engagement_score = Column(Float, default=0.0)
    sample_size = Column(Integer, default=0)

# ── Index Hints for PostgreSQL Performance ─────────────────
def create_indexes(engine):
    """Create additional performance indexes"""
    with engine.connect() as conn:
        # Composite indexes for common queries
        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_videos_status_timestamp 
        ON videos(status, upload_timestamp DESC);
        """)
        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_metrics_upload_hours 
        ON post_metrics(upload_id, hours_since_upload);
        """)
        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_uploads_platform_time 
        ON uploads(platform, posted_at DESC);
        """)
        conn.commit()
