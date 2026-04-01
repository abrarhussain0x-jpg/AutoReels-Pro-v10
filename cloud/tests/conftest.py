"""AutoReels Pro v10 — Pytest Configuration & Fixtures"""

import pytest
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import redis

@pytest.fixture(scope="session")
def test_db():
    """Create in-memory SQLite database for tests"""
    from src.database.schema import Base
    
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()

@pytest.fixture
def db_session(test_db):
    """Get database session for test"""
    Session = sessionmaker(bind=test_db)
    session = Session()
    yield session
    session.rollback()
    session.close()

@pytest.fixture
def redis_client():
    """Get Redis client for tests"""
    r = redis.Redis(host='localhost', port=6379, db=1, decode_responses=True)
    r.flushdb()
    yield r
    r.flushdb()

@pytest.fixture
def mock_env(monkeypatch):
    """Set mock environment variables"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-sk-ant-v1-test")
    monkeypatch.setenv("FB_PAGE_ID", "123456789")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/1")
    monkeypatch.setenv("ENVIRONMENT", "testing")
    return monkeypatch

# ── TEST COLLECTION ────────────────────────────────────────

def pytest_configure(config):
    """Register custom markers"""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )
    config.addinivalue_line(
        "markers", "smoke: marks tests as smoke tests"
    )

# ── CONFTEST EXAMPLES ──────────────────────────────────────

@pytest.fixture
def sample_video(db_session):
    """Create sample video for tests"""
    import uuid
    from src.database.schema import Video
    
    video = Video(
        youtube_id=f"test_{uuid.uuid4().hex[:8]}",
        title="Test Video",
        channel_id="test_channel",
        duration_seconds=600,
        status="done",
    )
    db_session.add(video)
    db_session.commit()
    return video

@pytest.fixture
def sample_clip(db_session, sample_video):
    """Create sample clip for tests"""
    from src.database.schema import Clip
    
    clip = Clip(
        video_id=sample_video.id,
        start_sec=0.0,
        end_sec=30.0,
        duration_sec=30.0,
        clip_type="scene",
        scene_score=0.8,
        motion_score=0.7,
        audio_energy=0.6,
    )
    db_session.add(clip)
    db_session.commit()
    return clip

@pytest.fixture
def sample_upload(db_session, sample_clip):
    """Create sample upload for tests"""
    from src.database.schema import Upload
    
    upload = Upload(
        clip_id=sample_clip.id,
        platform="facebook",
        platform_post_id="post_123",
        account_id="acc_123",
        status="live",
        caption="Test caption",
        hook_used="This is wild...",
        thumbnail_variant="a",
    )
    db_session.add(upload)
    db_session.commit()
    return upload
