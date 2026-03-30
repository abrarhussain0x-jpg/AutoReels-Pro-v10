"""AutoReels Pro v10 — Celery Async Tasks"""

from celery import Celery, group, chain, chord
from celery.exceptions import MaxRetriesExceededError
from datetime import datetime, timedelta
import logging
import os

app = Celery('autoreels')

# Load config from environment
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

logger = logging.getLogger(__name__)

# ── PIPELINE ORCHESTRATION ──────────────────────────

@app.task(bind=True, max_retries=3, default_retry_delay=60)
def fetch_youtube_video(self, video_url: str):
    """Download and extract video metadata"""
    from src.fetch.youtube_monitor import YouTubeMonitor
    try:
        monitor = YouTubeMonitor()
        result = monitor.fetch_and_extract(video_url)
        return {'video_id': result['id'], 'status': 'downloaded'}
    except Exception as exc:
        logger.error(f"fetch_youtube_video failed: {exc}")
        raise self.retry(exc=exc, countdown=30)

@app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_video(self, video_id: str, video_path: str):
    """Scene detection + subtitle burn"""
    from src.processor.scene_clipper import SceneClipper
    from src.processor.subtitle_engine_v2 import SubtitleEngine
    try:
        clipper = SceneClipper()
        scenes = clipper.detect_scenes(video_path)
        
        subtitle_engine = SubtitleEngine()
        subtitle_engine.generate_captions(video_path)
        
        return {'video_id': video_id, 'scenes': len(scenes), 'status': 'processed'}
    except Exception as exc:
        logger.error(f"process_video failed: {exc}")
        raise self.retry(exc=exc, countdown=60)

@app.task(bind=True, max_retries=5, default_retry_delay=120)
def score_clips(self, video_id: str):
    """ML scoring for all clips"""
    from src.brain.scorer_v10 import ScorerV10
    from src.intelligence.growth_predictor import GrowthPredictor
    try:
        scorer = ScorerV10()
        predictor = GrowthPredictor()
        
        clips = scorer.score_all_clips(video_id)
        predictions = predictor.predict_engagement(clips)
        
        return {'video_id': video_id, 'clips_scored': len(clips)}
    except Exception as exc:
        logger.error(f"score_clips failed: {exc}")
        raise self.retry(exc=exc, countdown=120)

@app.task(bind=True, max_retries=2, default_retry_delay=30)
def generate_captions_with_ai(self, clip_ids: list):
    """Batch generate captions with Claude Haiku"""
    from src.brain.content_gen import ContentGenerator
    try:
        gen = ContentGenerator()
        captions = gen.batch_generate_captions(clip_ids)
        return {'captions_generated': len(captions)}
    except Exception as exc:
        logger.error(f"generate_captions_with_ai failed: {exc}")
        raise self.retry(exc=exc, countdown=30)

@app.task(bind=True, max_retries=10, default_retry_delay=45)
def upload_to_platform(self, upload_id: str, platform: str, account_id: str):
    """Upload clip to social platform"""
    from src.publisher.upload_dispatcher import UploadDispatcher
    from src.resilience.retry_engine import RetryEngine
    try:
        dispatcher = UploadDispatcher()
        retry_engine = RetryEngine()
        
        result = dispatcher.upload(upload_id, platform, account_id)
        
        if result['status'] == 'failed':
            retry_engine.enqueue_retry(upload_id, platform, account_id, result['error'])
            raise Exception(f"Upload failed: {result['error']}")
        
        return {'upload_id': upload_id, 'platform_post_id': result.get('post_id')}
    except Exception as exc:
        logger.error(f"upload_to_platform failed: {exc}")
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=min(2**self.request.retries * 60, 600))
        else:
            raise

@app.task(bind=True, max_retries=2)
def pull_engagement_metrics(self, upload_id: str, hours_since: int = 0):
    """Pull views, likes, comments at time point"""
    from src.analytics.velocity_tracker import VelocityTracker
    from src.engagement.comment_bot import CommentBot
    try:
        tracker = VelocityTracker()
        comment_bot = CommentBot()
        
        metrics = tracker.pull_metrics_for_upload(upload_id, hours_since)
        
        if hours_since in [24, 48]:  # Sample comments at 24h, 48h
            comment_bot.fetch_and_classify_comments(upload_id)
        
        return {'upload_id': upload_id, 'metrics': metrics}
    except Exception as exc:
        logger.error(f"pull_engagement_metrics failed: {exc}")
        raise self.retry(exc=exc, countdown=60)

@app.task(bind=True, max_retries=1)
def learn_from_metrics(self, upload_id: str):
    """Update hook library + growth predictor from real data"""
    from src.intelligence.hook_optimizer import HookOptimizer
    from src.intelligence.growth_predictor import GrowthPredictor
    try:
        optimizer = HookOptimizer()
        predictor = GrowthPredictor()
        
        optimizer.update_from_upload(upload_id)
        predictor.retrain_mini_batch(upload_id)
        
        return {'upload_id': upload_id, 'learned': True}
    except Exception as exc:
        logger.error(f"learn_from_metrics failed: {exc}")
        raise self.retry(exc=exc, countdown=120)

# ── ORCHESTRATED WORKFLOWS ──────────────────────────

@app.task
def full_pipeline(video_url: str):
    """Complete end-to-end: fetch → process → score → generate → upload"""
    workflow = chain(
        fetch_youtube_video.s(video_url),
        process_video.s(video_url),
        score_clips.s(),
        generate_captions_with_ai.s([]),  # IDs from score_clips
    )
    return workflow.apply_async()

@app.task
def engagement_monitor_workflow(upload_ids: list):
    """Pull metrics at 1h, 6h, 24h, 72h; learn from each"""
    callbacks = []
    for hours in [1, 6, 24, 72]:
        callback = chain(
            pull_engagement_metrics.s(upload_ids[0], hours),
            learn_from_metrics.s(upload_ids[0])
        )
        callbacks.append(callback)
    
    return group(callbacks).apply_async()

# ── SCHEDULED TASKS ──────────────────────────────

@app.task
def hourly_retry_failed_uploads():
    """Retry dead letter queue every hour"""
    from src.resilience.retry_engine import RetryEngine
    retry_engine = RetryEngine()
    retry_engine.retry_failed_jobs(max_retries=5)
    logger.info("Hourly retry_failed_uploads completed")

@app.task
def daily_reset_account_limits():
    """Reset daily upload counters at midnight UTC"""
    from src.publisher.account_rotator import AccountRotator
    rotator = AccountRotator()
    rotator.reset_daily_limits()
    logger.info("Daily account limits reset")

@app.task
def daily_optimize_schedules():
    """Learn optimal posting times per niche"""
    from src.optimizer.time_optimizer_v2 import TimeOptimizer
    optimizer = TimeOptimizer()
    optimizer.optimize_from_historical_data()
    logger.info("Daily schedule optimization completed")

@app.task
def daily_generate_weekly_report():
    """Send weekly performance report"""
    from src.analytics.weekly_reporter import WeeklyReporter
    from src.notifier.notifier import Notifier
    reporter = WeeklyReporter()
    report = reporter.generate_report()
    notifier = Notifier()
    notifier.send_report(report)
    logger.info("Weekly report sent")

# ── BEAT SCHEDULE ───────────────────────────────

from celery.schedules import crontab

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
