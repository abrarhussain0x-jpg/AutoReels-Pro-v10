"""AutoReels Pro v10 — Database Tests"""

import pytest
from datetime import datetime, timedelta

def test_video_creation(db_session):
    """Test creating a video record"""
    from src.database.schema import Video
    
    video = Video(
        youtube_id="test123",
        title="Test Video",
        channel_id="channel123",
        duration_seconds=600,
        status="pending"
    )
    db_session.add(video)
    db_session.commit()
    
    retrieved = db_session.query(Video).filter_by(youtube_id="test123").first()
    assert retrieved is not None
    assert retrieved.title == "Test Video"
    assert retrieved.status == "pending"

def test_clip_creation(db_session, sample_video):
    """Test creating a clip"""
    from src.database.schema import Clip
    
    clip = Clip(
        video_id=sample_video.id,
        start_sec=10.0,
        end_sec=40.0,
        duration_sec=30.0,
        clip_type="highlight",
        scene_score=0.9,
        motion_score=0.8,
        audio_energy=0.7,
    )
    db_session.add(clip)
    db_session.commit()
    
    retrieved = db_session.query(Clip).filter_by(video_id=sample_video.id).first()
    assert retrieved is not None
    assert retrieved.duration_sec == 30.0
    assert retrieved.clip_type == "highlight"

def test_upload_creation(db_session, sample_clip):
    """Test creating an upload record"""
    from src.database.schema import Upload
    
    upload = Upload(
        clip_id=sample_clip.id,
        platform="tiktok",
        platform_post_id="post_123",
        account_id="acc_123",
        status="live",
        caption="TikTok test",
        hook_used="Watch this...",
        thumbnail_variant="b",
    )
    db_session.add(upload)
    db_session.commit()
    
    retrieved = db_session.query(Upload).filter_by(platform="tiktok").first()
    assert retrieved is not None
    assert retrieved.status == "live"
    assert retrieved.platform == "tiktok"

def test_metrics_creation(db_session, sample_upload):
    """Test creating engagement metrics"""
    from src.database.schema import PostMetric
    
    metric = PostMetric(
        upload_id=sample_upload.id,
        hours_since_upload=1,
        views=100,
        likes=10,
        comments=5,
        shares=2,
        velocity=100.0,
    )
    db_session.add(metric)
    db_session.commit()
    
    retrieved = db_session.query(PostMetric).filter_by(upload_id=sample_upload.id).first()
    assert retrieved is not None
    assert retrieved.views == 100
    assert retrieved.velocity == 100.0

def test_account_creation(db_session):
    """Test creating a social account"""
    from src.database.schema import Account
    
    account = Account(
        platform="facebook",
        account_name="test_page",
        page_id="123456789",
        daily_upload_limit=5,
        status="active",
        auth_token_encrypted="encrypted_token_here",
    )
    db_session.add(account)
    db_session.commit()
    
    retrieved = db_session.query(Account).filter_by(page_id="123456789").first()
    assert retrieved is not None
    assert retrieved.status == "active"
    assert retrieved.daily_upload_limit == 5

def test_hook_creation(db_session):
    """Test creating a hook phrase"""
    from src.database.schema import Hook
    
    hook = Hook(
        niche="anime",
        angle="emotional_moment",
        platform="tiktok",
        phrase="This scene hits different...",
        impressions=1000,
        clicks=100,
        retention_3s=0.75,
        engagement_rate=0.10,
    )
    db_session.add(hook)
    db_session.commit()
    
    retrieved = db_session.query(Hook).filter_by(niche="anime").first()
    assert retrieved is not None
    assert retrieved.retention_3s == 0.75

def test_failed_job_creation(db_session, sample_clip):
    """Test creating a failed job record"""
    from src.database.schema import FailedJob
    
    failed = FailedJob(
        clip_id=sample_clip.id,
        platform="facebook",
        account_id="acc_123",
        error_message="Rate limit exceeded",
        retry_count=0,
        max_retries=5,
        next_retry_at=datetime.utcnow() + timedelta(minutes=30),
        payload={"test": "data"},
    )
    db_session.add(failed)
    db_session.commit()
    
    retrieved = db_session.query(FailedJob).filter_by(platform="facebook").first()
    assert retrieved is not None
    assert retrieved.error_message == "Rate limit exceeded"
    assert retrieved.retry_count == 0

@pytest.mark.slow
def test_query_performance(db_session, sample_video):
    """Test query performance with indexes"""
    from src.database.schema import Clip
    
    # Create multiple clips
    for i in range(100):
        clip = Clip(
            video_id=sample_video.id,
            start_sec=float(i * 30),
            end_sec=float((i + 1) * 30),
            duration_sec=30.0,
            clip_type="scene",
        )
        db_session.add(clip)
    
    db_session.commit()
    
    # Query should be fast
    clips = db_session.query(Clip).filter_by(video_id=sample_video.id).all()
    assert len(clips) == 100

def test_relationship_cascades(db_session, sample_video):
    """Test cascade deletes work correctly"""
    from src.database.schema import Clip, Video
    
    initial_count = db_session.query(Clip).count()
    
    # Create clip linked to video
    clip = Clip(
        video_id=sample_video.id,
        start_sec=0.0,
        end_sec=30.0,
        duration_sec=30.0,
        clip_type="scene",
    )
    db_session.add(clip)
    db_session.commit()
    
    assert db_session.query(Clip).count() == initial_count + 1
    
    # Delete video - should cascade to clips
    db_session.delete(sample_video)
    db_session.commit()
    
    assert db_session.query(Clip).filter_by(video_id=sample_video.id).count() == 0
