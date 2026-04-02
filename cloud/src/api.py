"""AutoReels Pro v10 — FastAPI Real-Time API"""

from fastapi import FastAPI, HTTPException, WebSocket, Depends, BackgroundTasks, Header, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Generator, List, Optional
import json
import logging
import asyncio
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

logger = logging.getLogger(__name__)

# ─── DATABASE singleton ───────────────────────────────────────────────────────
_db_url = os.getenv("DATABASE_URL", "sqlite:///autoreels.db")
_engine = create_engine(
    _db_url,
    pool_pre_ping=True,
    pool_size=int(os.getenv("DB_POOL_SIZE", "10")),
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "20")),
)
_SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


def get_db() -> Generator[Session, None, None]:
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ─── CORS ────────────────────────────────────────────────────────────────────
def _get_allowed_origins() -> List[str]:
    raw = os.getenv("ALLOWED_ORIGINS", "")
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    if os.getenv("ENVIRONMENT", "development") == "production":
        logger.warning("ALLOWED_ORIGINS not set in production — defaulting to localhost only.")
        return ["http://localhost:5000", "http://localhost:8000"]
    return ["http://localhost:3000", "http://localhost:5000", "http://localhost:8000"]


# ─── ADMIN AUTH ───────────────────────────────────────────────────────────────
_ADMIN_KEY = os.getenv("ADMIN_API_KEY", "")
if not _ADMIN_KEY:
    logger.warning(
        "ADMIN_API_KEY not set — admin endpoints disabled. "
        "Set in .env: python -c \"import secrets; print(secrets.token_hex(32))\""
    )


def require_admin(x_api_key: Optional[str] = Header(None)) -> None:
    if not _ADMIN_KEY:
        raise HTTPException(status_code=503, detail="Admin API disabled: ADMIN_API_KEY not configured")
    if not x_api_key or x_api_key != _ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Unauthorized")


# ─── APP ─────────────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    async def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        dead = []
        for conn in self.active_connections:
            try:
                await conn.send_json(message)
            except Exception:
                dead.append(conn)
        for conn in dead:
            await self.disconnect(conn)


manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("AutoReels API v10 starting...")
    try:
        from .database.schema import Base
        Base.metadata.create_all(bind=_engine)
        logger.info("Database schema ready")
    except Exception as e:
        logger.warning("DB schema init skipped: %s", e)
    yield
    logger.info("AutoReels API shutting down...")


app = FastAPI(
    title="AutoReels Pro v10 API",
    version="10.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request, exc):
    return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})


app.state.limiter = limiter

# ─── HEALTH ──────────────────────────────────────────────────────────────────

@app.get("/health")
@limiter.limit("1000/minute")
async def health(request: Request):
    return {"status": "alive", "timestamp": datetime.utcnow().isoformat()}


@app.get("/ready")
async def readiness(db: Session = Depends(get_db)):
    try:
        from .database.schema import Video
        db.query(Video).limit(1).all()
        return {"status": "ready", "database": "connected"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/status")
@limiter.limit("60/minute")
async def status(request: Request, db: Session = Depends(get_db)):
    try:
        from .database.schema import Video, Upload
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


# ─── METRICS & OBSERVABILITY ─────────────────────────────────────────────────

@app.get("/metrics")
@limiter.limit("100/minute")
async def get_metrics(request: Request):
    """Get aggregated performance and pipeline metrics."""
    try:
        from .dashboard.metrics_api import MetricsAPI
        return MetricsAPI.get_metrics_endpoint()
    except Exception as e:
        logger.error(f"Metrics endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch metrics")


@app.get("/metrics/performance")
@limiter.limit("60/minute")
async def get_performance_metrics(request: Request):
    """Get detailed performance metrics."""
    try:
        from .dashboard.metrics_api import MetricsAPI
        return MetricsAPI.get_performance_endpoint()
    except Exception as e:
        logger.error(f"Performance metrics error: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch performance metrics")


@app.get("/health/detailed")
@limiter.limit("60/minute")
async def get_detailed_health(request: Request):
    """Get detailed health check status."""
    try:
        from .health.observability import get_health_check
        health = get_health_check()
        return health.status()
    except Exception as e:
        logger.error(f"Health check error: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch health status")


@app.get("/dashboard.html")
async def get_dashboard_html(request: Request):
    """Get HTML dashboard."""
    try:
        from .dashboard.metrics_api import DashboardHTML
        html = DashboardHTML.generate_dashboard_html()
        from fastapi.responses import HTMLResponse
        return HTMLResponse(content=html)
    except Exception as e:
        logger.error(f"Dashboard html error: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate dashboard")


# ─── WEBSOCKET ────────────────────────────────────────────────────────────────

@app.websocket("/ws/pipeline")
async def websocket_pipeline(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except Exception:
        await manager.disconnect(websocket)


# ─── ANALYTICS ────────────────────────────────────────────────────────────────

@app.get("/api/v1/analytics/daily")
@limiter.limit("30/minute")
async def analytics_daily(request: Request, days: int = 30, db: Session = Depends(get_db)):
    from .database.schema import Upload
    result = []
    for i in range(min(days, 365)):
        day = (datetime.utcnow() - timedelta(days=i)).date()
        count = db.query(Upload).filter(
            Upload.posted_at >= day,
            Upload.posted_at < day + timedelta(days=1),
        ).count()
        result.append({"date": str(day), "uploads": count})
    return result


# ─── VIDEOS ───────────────────────────────────────────────────────────────────

@app.get("/api/v1/videos")
@limiter.limit("60/minute")
async def list_videos(request: Request, limit: int = 20, offset: int = 0, db: Session = Depends(get_db)):
    from .database.schema import Video
    videos = db.query(Video).order_by(Video.upload_timestamp.desc()).offset(offset).limit(limit).all()
    return [
        {
            "id": v.id,
            "youtube_id": v.youtube_id,
            "title": v.title,
            "status": v.status,
            "created_at": v.upload_timestamp.isoformat() if v.upload_timestamp else None,
        }
        for v in videos
    ]


@app.get("/api/v1/videos/{video_id}")
@limiter.limit("120/minute")
async def get_video(request: Request, video_id: str, db: Session = Depends(get_db)):
    from .database.schema import Video
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    return {
        "id": video.id,
        "youtube_id": video.youtube_id,
        "title": video.title,
        "status": video.status,
        "clips_count": len(video.clips) if hasattr(video, "clips") else 0,
        "created_at": video.upload_timestamp.isoformat() if video.upload_timestamp else None,
    }


# ─── ADMIN ────────────────────────────────────────────────────────────────────

@app.post("/api/v1/admin/reprocess-video/{video_id}")
async def reprocess_video(
    video_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    from .database.schema import Video
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    video.status = "pending"
    db.commit()
    try:
        from .tasks import process_video
        background_tasks.add_task(process_video, video_id)
    except ImportError:
        pass
    return {"status": "requeued", "video_id": video_id}


@app.get("/api/v1/admin/queue")
async def admin_queue(db: Session = Depends(get_db), _: None = Depends(require_admin)):
    from .database.schema import Video
    pending = db.query(Video).filter(Video.status.in_(["pending", "processing"])).all()
    return [{"id": v.id, "title": v.title, "status": v.status} for v in pending]


@app.delete("/api/v1/admin/cache")
async def clear_cache(_: None = Depends(require_admin)):
    try:
        import redis as redis_lib
        r = redis_lib.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
        r.flushdb()
        return {"status": "cache_cleared"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
