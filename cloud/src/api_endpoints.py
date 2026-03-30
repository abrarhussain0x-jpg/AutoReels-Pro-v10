"""AutoReels Pro v10 — FastAPI Production Endpoints"""

from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel
from typing import Generator, Optional, List
from datetime import datetime, timedelta
from enum import Enum
import logging
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

app = FastAPI(
    title="AutoReels Pro v10 API",
    description="Production-grade content automation engine",
    version="10.0.0",
)

app.add_middleware(GZipMiddleware, minimum_size=1000)

# ─── CORS ────────────────────────────────────────────────────────────────────
def _allowed_origins() -> List[str]:
    raw = os.getenv("ALLOWED_ORIGINS", "")
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return ["http://localhost:3000", "http://localhost:5000", "http://localhost:8000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)

logger = logging.getLogger(__name__)

# ─── DATABASE singleton ───────────────────────────────────────────────────────
_db_url = os.getenv("DATABASE_URL", "sqlite:///autoreels.db")
_engine_kwargs: dict = {"pool_pre_ping": True}
if _db_url.startswith("sqlite"):
    # SQLite doesn't support server-side connection pooling args
    from sqlalchemy.pool import StaticPool
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
    _engine_kwargs["poolclass"] = StaticPool
else:
    _engine_kwargs["pool_size"] = int(os.getenv("DB_POOL_SIZE", "10"))
    _engine_kwargs["max_overflow"] = int(os.getenv("DB_MAX_OVERFLOW", "20"))

_engine = create_engine(_db_url, **_engine_kwargs)

# Auto-create tables if they don't exist (safe no-op if already present)
from src.database.schema import Base as _Base
_Base.metadata.create_all(_engine)

_SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


def get_db() -> Generator[Session, None, None]:
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ─── MODELS ──────────────────────────────────────────────────────────────────

class VideoStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    done = "done"
    failed = "failed"


class VideoRequest(BaseModel):
    youtube_url: str
    force_process: bool = False


class VideoResponse(BaseModel):
    id: str
    youtube_id: str
    title: str
    status: VideoStatus
    clips_count: int
    created_at: datetime


class HealthResponse(BaseModel):
    status: str
    timestamp: datetime
    database: str
    redis: str


# ─── HEALTH ──────────────────────────────────────────────────────────────────

@app.get("/api/health", response_model=HealthResponse)
async def health(db: Session = Depends(get_db)):
    try:
        from src.database.schema import Video
        db.query(Video).limit(1).all()
        db_status = "connected"
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"DB error: {e}")

    try:
        import redis
        r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
        r.ping()
        redis_status = "connected"
    except Exception as e:
        redis_status = f"unavailable: {e}"

    return HealthResponse(
        status="healthy",
        timestamp=datetime.utcnow(),
        database=db_status,
        redis=redis_status,
    )


@app.get("/api/ready")
async def readiness():
    return {"status": "ready"}


@app.get("/api/status")
async def status(db: Session = Depends(get_db)):
    try:
        from src.database.schema import Video, Upload
        return {
            "status": "operational",
            "timestamp": datetime.utcnow().isoformat(),
            "videos": {
                "total": db.query(Video).count(),
                "processing": db.query(Video).filter(Video.status == "processing").count(),
                "done": db.query(Video).filter(Video.status == "done").count(),
            },
            "uploads": {
                "total": db.query(Upload).count(),
                "live": db.query(Upload).filter(Upload.status == "live").count(),
            },
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# ─── VIDEOS ───────────────────────────────────────────────────────────────────

@app.post("/api/v1/videos", response_model=VideoResponse)
async def process_video(req: VideoRequest, db: Session = Depends(get_db)):
    from src.database.schema import Video
    try:
        youtube_id = req.youtube_url.split("v=")[-1].split("&")[0] if "v=" in req.youtube_url else req.youtube_url

        # Upsert guard — return existing record instead of crashing on duplicate
        existing = db.query(Video).filter_by(youtube_id=youtube_id).first()
        if existing:
            return VideoResponse(
                id=existing.id,
                youtube_id=existing.youtube_id,
                title=existing.title,
                status=existing.status,
                clips_count=0,
                created_at=existing.upload_timestamp or datetime.utcnow(),
            )

        video = Video(
            youtube_id=youtube_id,
            title="Processing...",
            status="pending",
        )
        db.add(video)
        db.commit()
        db.refresh(video)

        try:
            from src.tasks import fetch_youtube_video
            fetch_youtube_video.delay(req.youtube_url)
        except Exception:
            pass  # Celery optional

        return VideoResponse(
            id=video.id,
            youtube_id=video.youtube_id,
            title=video.title,
            status=video.status,
            clips_count=0,
            created_at=video.upload_timestamp or datetime.utcnow(),
        )
    except Exception as e:
        logger.error("Video processing failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/videos/{video_id}", response_model=VideoResponse)
async def get_video(video_id: str, db: Session = Depends(get_db)):
    from src.database.schema import Video
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    return VideoResponse(
        id=video.id,
        youtube_id=video.youtube_id,
        title=video.title,
        status=video.status,
        clips_count=len(video.clips) if hasattr(video, "clips") else 0,
        created_at=video.upload_timestamp or datetime.utcnow(),
    )


# ─── ANALYTICS ────────────────────────────────────────────────────────────────

@app.get("/api/v1/analytics/daily")
async def analytics_daily(days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)):
    from src.database.schema import Upload
    result = []
    for i in range(days):
        day = (datetime.utcnow() - timedelta(days=i)).date()
        count = db.query(Upload).filter(
            Upload.posted_at >= day,
            Upload.posted_at < day + timedelta(days=1),
        ).count()
        result.append({"date": str(day), "uploads": count})
    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, workers=4)
