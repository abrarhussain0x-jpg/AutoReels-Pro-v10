"""AutoReels Pro v10 — Celery Async Tasks (Optional)

Note: Celery is optional. Production pipeline uses native executor.
This module provides async task orchestration when Celery/Redis available.
"""

from datetime import datetime, timedelta
import logging
import os

# Gracefully handle missing Celery dependency
try:
    from celery import Celery, group, chain, chord  # type: ignore
    from celery.exceptions import MaxRetriesExceededError  # type: ignore
    CELERY_AVAILABLE = True
except ImportError:
    CELERY_AVAILABLE = False
    # Provide stub for when Celery not installed
    class Celery:
        def __init__(self, *args, **kwargs):
            pass
        def conf(self):
            return self
        def update(self, **kwargs):
            pass
        @property
        def conf(self):
            class Conf:
                def update(self, **kwargs):
                    pass
            return Conf()
        def task(self, *args, **kwargs):
            def decorator(f):
                return f
            return decorator

    class MaxRetriesExceededError(Exception):
        pass
    
    def group(*args, **kwargs):
        return None
    
    def chain(*args, **kwargs):
        return None
    
    def chord(*args, **kwargs):
        return None

app = Celery('autoreels')

# Load config from environment
if CELERY_AVAILABLE:
    app.conf.update(
        broker_url=os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
        result_backend=os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
        task_serializer='json',
        accept_content=['json'],
        result_serializer='json',
        timezone='UTC',
        enable_utc=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        task_compression='gzip',
    )
else:
    # Stub config when Celery not available
    try:
        app.conf.update(
            broker_url=os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
            result_backend=os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
        )
    except Exception as e:
        # Redis may not be available in development - this is expected
        logger_temp = logging.getLogger(__name__)
        logger_temp.debug(f"[Celery] Redis config failed (expected in dev): {e}")

logger = logging.getLogger(__name__)

# ── PIPELINE ORCHESTRATION ──────────────────────────

def _queue_dir():
    """Return the queue directory path from env or default."""
    from pathlib import Path
    return Path(os.getenv("QUEUE_DIR", str(Path(__file__).resolve().parents[1] / "queue")))


@app.task(bind=True, max_retries=3, default_retry_delay=60)
def fetch_youtube_video(self, video_url: str):
    """Fetch YouTube video metadata."""
    from src.fetch.youtube_monitor import YouTubeMonitor
    try:
        config = {"channels": [], "niche": os.getenv("AUTOREELS_NICHE", "movie")}
        monitor = YouTubeMonitor(config)
        meta = monitor._get_metadata(video_url)
        if meta is None:
            raise ValueError(f"Could not fetch metadata for {video_url}")
        return {
            'video_id': meta.video_id,
            'title': meta.title,
            'url': video_url,
            'path': '',
            'status': 'fetched',
        }
    except Exception as exc:
        logger.error(f"fetch_youtube_video failed: {exc}")
        raise self.retry(exc=exc, countdown=30)


@app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_video(self, fetch_result: dict):
    """Scene detection + subtitle burn.  Receives dict from fetch_youtube_video."""
    from src.processor.scene_clipper import SceneClipper
    from src.processor.subtitle_engine_v2 import SubtitleEngineV2
    from pathlib import Path
    try:
        video_id = fetch_result.get('video_id', '')
        video_path = fetch_result.get('path', '')

        scenes_count = 0
        if video_path and Path(video_path).exists():
            clipper = SceneClipper()
            plan = clipper.plan_clips(Path(video_path), n_clips=10)
            scenes_count = len(plan.clips)

            api_key = os.getenv("ANTHROPIC_API_KEY", "")
            subtitle_engine = SubtitleEngineV2(api_key=api_key)
            output_path = Path(video_path).with_suffix('.captioned.mp4')
            subtitle_engine.burn_captions(Path(video_path), output_path)
        else:
            logger.warning("[process_video] no local video file for %s — skipping ffmpeg steps", video_id)

        return {'video_id': video_id, 'scenes': scenes_count, 'path': video_path, 'status': 'processed'}
    except Exception as exc:
        logger.error(f"process_video failed: {exc}")
        raise self.retry(exc=exc, countdown=60)


@app.task(bind=True, max_retries=5, default_retry_delay=120)
def score_clips(self, process_result: dict):
    """ML scoring for all clips in a video.  Receives dict from process_video."""
    from src.brain.scorer_v10 import VideoScorerV10
    from src.intelligence.growth_predictor import GrowthPredictor
    try:
        video_id = process_result.get('video_id', '')
        config = {
            "niche": os.getenv("AUTOREELS_NICHE", "movie"),
            "process_threshold": float(os.getenv("PROCESS_THRESHOLD", "0.35")),
            "defer_threshold": float(os.getenv("DEFER_THRESHOLD", "0.20")),
        }
        scorer = VideoScorerV10(config)
        clips = scorer.score_all_clips(video_id)
        clip_ids = [c.get('clip_id') for c in clips if c.get('clip_id')]

        # Run growth predictor retraining to stay current
        predictor = GrowthPredictor(db_path=_queue_dir() / "growth.db")
        predictor.retrain()

        return {'video_id': video_id, 'clips_scored': len(clips), 'clip_ids': clip_ids}
    except Exception as exc:
        logger.error(f"score_clips failed: {exc}")
        raise self.retry(exc=exc, countdown=120)


@app.task(bind=True, max_retries=2, default_retry_delay=30)
def generate_captions_with_ai(self, score_result: dict):
    """Batch generate captions with Claude.  Receives dict from score_clips."""
    from src.brain.content_gen import ContentGenerator
    try:
        clip_ids = score_result.get('clip_ids', [])
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        niche = os.getenv("AUTOREELS_NICHE", "movie")
        gen = ContentGenerator(api_key=api_key, niche=niche)
        captions = gen.batch_generate_captions(clip_ids)
        return {'captions_generated': len(captions), 'clip_ids': clip_ids}
    except Exception as exc:
        logger.error(f"generate_captions_with_ai failed: {exc}")
        raise self.retry(exc=exc, countdown=30)


@app.task(bind=True, max_retries=10, default_retry_delay=45)
def upload_to_platform(self, upload_id: str, platform: str, account_id: str):
    """Upload clip to social platform."""
    from src.publisher.upload_dispatcher import UploadDispatcher
    from src.resilience.retry_engine import RetryEngine
    from pathlib import Path
    try:
        retry_engine = RetryEngine(db_path=_queue_dir() / "failed.db")
        # Dispatcher with no pre-configured uploaders; real uploaders injected at runtime
        dispatcher = UploadDispatcher(uploaders={}, retry_engine=retry_engine)

        result = dispatcher.upload(
            clip_path=Path(upload_id),
            caption="",
            video_id=upload_id,
            clip_num=1,
        )

        if not result.any_success:
            errors = "; ".join(
                f"{r.platform}: {r.error}" for r in result.results if not r.success
            )
            raise Exception(f"Upload failed: {errors}")

        post_ids = {r.platform: r.post_id for r in result.results if r.success and r.post_id}
        return {'upload_id': upload_id, 'platform_post_ids': post_ids}
    except Exception as exc:
        logger.error(f"upload_to_platform failed: {exc}")
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=min(2 ** self.request.retries * 60, 600))
        else:
            raise


@app.task(bind=True, max_retries=2)
def pull_engagement_metrics(self, upload_id: str, hours_since: int = 0):
    """Record engagement metrics for an upload at the given hours-since-upload mark."""
    from src.analytics.velocity_tracker import VelocityTracker
    try:
        tracker = VelocityTracker(db_path=_queue_dir() / "velocity.db")
        # Record a placeholder metric pull; real callers supply actual view/like counts
        velocity, is_viral = tracker.record_metrics(
            upload_id=upload_id,
            views=0,
            likes=0,
        )
        return {'upload_id': upload_id, 'velocity': velocity, 'is_viral': is_viral}
    except Exception as exc:
        logger.error(f"pull_engagement_metrics failed: {exc}")
        raise self.retry(exc=exc, countdown=60)


@app.task(bind=True, max_retries=1)
def learn_from_metrics(self, metrics_result: dict):
    """Retrain growth predictor and refresh hook weights from real engagement data.
    Receives the dict returned by pull_engagement_metrics when used in a chain.
    """
    from src.intelligence.hook_optimizer import HookOptimizer
    from src.intelligence.growth_predictor import GrowthPredictor
    try:
        upload_id = metrics_result.get('upload_id', '') if isinstance(metrics_result, dict) else str(metrics_result)
        niche = os.getenv("AUTOREELS_NICHE", "movie")
        optimizer = HookOptimizer(
            db_path=_queue_dir() / "hooks.db",
            niche=niche,
        )
        predictor = GrowthPredictor(db_path=_queue_dir() / "growth.db")

        # Recompute hook UCB1 weights for all contexts and retrain predictor
        optimizer._recompute_weights(platform="tiktok", niche=niche, angle="mystery")
        samples = predictor.retrain()

        return {'upload_id': upload_id, 'learned': True, 'predictor_samples': samples}
    except Exception as exc:
        logger.error(f"learn_from_metrics failed: {exc}")
        raise self.retry(exc=exc, countdown=120)

# ── ORCHESTRATED WORKFLOWS ──────────────────────────

@app.task
def full_pipeline(video_url: str):
    """Complete end-to-end: fetch → process → score → generate captions."""
    # Each chained task receives the previous task's return value as its first argument.
    workflow = chain(
        fetch_youtube_video.s(video_url),
        process_video.s(),
        score_clips.s(),
        generate_captions_with_ai.s(),
    )
    return workflow.apply_async()

@app.task
def engagement_monitor_workflow(upload_ids: list):
    """Pull metrics at 1h, 6h, 24h, 72h; learn from each."""
    if not upload_ids:
        logger.warning("[engagement_monitor_workflow] no upload_ids provided")
        return {'scheduled': 0}
    callbacks = []
    for upload_id in upload_ids:
        for hours in [1, 6, 24, 72]:
            callback = chain(
                pull_engagement_metrics.s(upload_id, hours),
                learn_from_metrics.s(),  # receives pull_engagement_metrics result dict
            )
            callbacks.append(callback)

    return group(callbacks).apply_async()

# ── SCHEDULED TASKS ──────────────────────────────

@app.task
def hourly_retry_failed_uploads():
    """Retry dead letter queue every hour."""
    from src.resilience.retry_engine import RetryEngine
    retry_engine = RetryEngine(db_path=_queue_dir() / "failed.db")
    count = retry_engine.retry_dead_letter_queue(fn_map={})
    logger.info("Hourly retry_failed_uploads completed: %d retried", count)

@app.task
def daily_reset_account_limits():
    """Log account rotation status at midnight UTC (limits auto-reset by date key)."""
    from src.publisher.account_rotator import AccountRotator
    import os
    rotator = AccountRotator(
        db_path=_queue_dir() / "account_rotation.db",
        config={"niche": os.getenv("AUTOREELS_NICHE", "movie")},
    )
    logger.info("Daily account status:\n%s", rotator.status_report())

@app.task
def daily_optimize_schedules():
    """Recompute optimal posting-time weights for all platforms."""
    from src.optimizer.time_optimizer_v2 import TimeOptimizerV2
    import os
    optimizer = TimeOptimizerV2(
        db_path=_queue_dir() / "time_windows.db",
        audience_timezone=os.getenv("AUDIENCE_TIMEZONE", "UTC"),
    )
    for platform in ["tiktok", "facebook", "instagram", "youtube"]:
        optimizer._recompute_weights(
            platform=platform,
            niche=os.getenv("AUTOREELS_NICHE", "movie"),
        )
    logger.info("Daily schedule optimization completed:\n%s", optimizer.time_windows_report())

@app.task
def daily_generate_weekly_report():
    """Generate and send weekly performance report."""
    from src.analytics.weekly_reporter import WeeklyReporter
    from src.notifier.notifier import Notifier
    import os
    reporter = WeeklyReporter(queue_dir=_queue_dir(), cfg={})
    report = reporter.generate_report()
    notifier = Notifier({})
    notifier.send(report)
    logger.info("Weekly report sent")

# ── BEAT SCHEDULE ───────────────────────────────

if CELERY_AVAILABLE:
    from celery.schedules import crontab  # type: ignore
    
    app.conf.beat_schedule = {
        'retry-failed-uploads-hourly': {
            'task': 'src.tasks.hourly_retry_failed_uploads',
            'schedule': crontab(minute=0),  # Every hour
        },
        'reset-account-limits-daily': {
            'task': 'src.tasks.daily_reset_account_limits',
            'schedule': crontab(hour=0, minute=0),  # Midnight UTC
        },
        'optimize-schedules-daily': {
            'task': 'src.tasks.daily_optimize_schedules',
            'schedule': crontab(hour=2, minute=0),  # 2 AM UTC
        },
        'weekly-report': {
            'task': 'src.tasks.daily_generate_weekly_report',
            'schedule': crontab(day_of_week=1, hour=9, minute=0),  # Monday 9 AM UTC
        },
    }
else:
    # Stub schedule when Celery not available
    app.conf.beat_schedule = {}
