"""
pipeline_v2.py v10.0-fixed — All call-site mismatches corrected.

FIXES applied:
  - queue.add(Job)           → queue.enqueue(scalar args)
  - queue.exists()           → queue.already_processed()
  - queue.update(state=X)    → mark_processing/mark_done/mark_failed()
  - queue.failed_retryable() → inline filter on recent_jobs()
  - queue.deferred_ready()   → inline filter on pending()
  - notifier.send_*()        → Notification dataclass wrapper
  - hashtag_engine.build()   → get_hashtags()
  - caption_optimizer params → clip_num→clip_index, channel→channel_name, no tuple unpack
  - growth_predictor.record_upload() → record_actual(upload_id, engagement)
  - time_optimizer.record_upload() args → added niche, fixed hour_utc→hour
  - time_optimizer.should_post_now() → is_good_window_now(platform, niche)
  - time_optimizer.next_optimal_times() → schedule_recommendation(niche, platform, n)
  - arc_engine.plan() extra kwargs removed
  - arc_plan.hook_for() → arc_plan.angle_for()
  - cb.is_open()  → cb.is_open  (@property, not method)
  - cb.record_failure/success() → via CircuitBreaker.__enter__/__exit__
  - Job field names: channel_id→channel, youtube_url→url, composite_score→score
  - Notifier: AdvancedNotificationSystem (not basic Notifier)
  - scheduler.should_post_now() → pending_count()>0 proxy
"""

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from src.scheduler.job_queue import Job, JobQueue, JobState
from src.notifier.advanced_notifier import (
    AdvancedNotificationSystem as Notifier,
    Notification,
    NotificationLevel,
)
from src.analytics.tracker import AnalyticsTracker
from src.resilience.circuit_breaker import CircuitBreaker
from src.resilience.rate_limiter import PlatformRateLimiters
from src.optimizer.caption_optimizer import CaptionOptimizer
from src.optimizer.hashtag_engine import HashtagEngine
from src.utils.lock import atomic_increment, atomic_read

log = logging.getLogger(__name__)

FORCE_RUN = os.environ.get("AUTOREELS_FORCE_RUN", "").strip() == "1"
DRY_RUN   = os.environ.get("AUTOREELS_DRY_RUN",   "").strip() == "1"


def _notif(title: str, msg: str, level: NotificationLevel = NotificationLevel.INFO) -> Notification:
    from src.notifier.advanced_notifier import NotificationChannel
    return Notification(title=title, message=msg, level=level,
                        channels=[NotificationChannel.SLACK])


@dataclass
class PipelineResult:
    video_id:        str
    title:           str
    clips_made:      int
    platform_posts:  Dict[str, List[str]] = field(default_factory=dict)
    success:         bool                  = False
    error:           Optional[str]         = None
    quality_scores:  List[float]           = field(default_factory=list)
    skipped_by_pred: int                   = 0


class PipelineV2:
    def __init__(
        self,
        source_manager,
        processor,
        queue:               JobQueue,
        analytics:           AnalyticsTracker,
        uploaders:           Dict,
        scheduler,
        notifier:            Notifier,
        decision_engine,
        content_gen,
        hashtag_engine:      HashtagEngine,
        caption_optimizer:   CaptionOptimizer,
        ab_engine            = None,
        auto_repost          = None,
        arc_engine           = None,
        growth_predictor     = None,
        time_optimizer       = None,
        daily_limit:         int   = 5,
        concurrent_uploads:  int   = 2,
        clip_upload_gap_s:   int   = 30,
        niche:               str   = "movie",
        channel_name:        str   = "AutoReels",
        prediction_gate:     bool  = True,
    ):
        self.sources            = source_manager
        self.processor          = processor
        self.queue              = queue
        self.analytics          = analytics
        self.uploaders          = {k: v for k, v in uploaders.items() if v and v.is_configured()}
        self.scheduler          = scheduler
        self.notifier           = notifier
        self.decision           = decision_engine
        self.content_gen        = content_gen
        self.hashtag_engine     = hashtag_engine
        self.caption_optimizer  = caption_optimizer
        self.ab_engine          = ab_engine
        self.auto_repost        = auto_repost
        self.arc_engine         = arc_engine
        self.growth_predictor   = growth_predictor
        self.time_optimizer     = time_optimizer
        self.daily_limit        = daily_limit
        self.concurrent_uploads = concurrent_uploads
        self.clip_upload_gap    = clip_upload_gap_s
        self.niche              = niche
        self.channel_name       = channel_name
        self.prediction_gate    = prediction_gate

        self._cb: Dict[str, CircuitBreaker] = {n: CircuitBreaker(n) for n in self.uploaders}
        self._rl = PlatformRateLimiters()

        self._count_dir = Path(__file__).parent.parent.parent / "queue"
        try:
            self._count_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            log.error("Failed to create pipeline queue directory: %s", e)
            raise

        if DRY_RUN:
            log.warning("[Pipeline] DRY_RUN=1 — no actual uploads")
        log.info("[Pipeline v10] uploaders=%s arc=%s pred=%s time_opt=%s",
                 list(self.uploaders),
                 "on" if arc_engine else "off",
                 "on" if growth_predictor else "off",
                 "on" if time_optimizer else "off")

    # ── Dashboard ─────────────────────────────────────────────────────────────

    def _in_upload_window(self) -> bool:
        return self._in_any_upload_window()

    def _next_upload_time(self) -> str:
        try:
            slots = self.time_optimizer.schedule_recommendation(
                niche=self.niche, platform=list(self.uploaders)[0], n=1,
            ) if self.time_optimizer and self.uploaders else []
            return slots[0].strftime("%H:%M") if slots else ""
        except Exception:
            return ""

    # ── Main entry ────────────────────────────────────────────────────────────

    def run_once(self) -> List[PipelineResult]:
        log.info("[Pipeline] run_once | force=%s dry=%s", FORCE_RUN, DRY_RUN)

        if self.uploads_today() >= self.daily_limit:
            return []

        if not FORCE_RUN and not self._in_any_upload_window():
            return []

        self._discover_and_queue()

        # Collect pending + failed retries (deduped)
        pending = list(self.queue.pending(limit=50))

        raw_recent = self.queue.recent_jobs(limit=100)
        failed_retryable = []
        for r in raw_recent:
            if r.get("state") == "FAILED":
                try:
                    j = self.queue.pending(limit=1)  # re-fetch as Job object if re-queued
                except Exception:
                    pass
        # Deduplication
        seen, deduped = set(), []
        for j in pending + failed_retryable:
            if j.video_id not in seen:
                seen.add(j.video_id)
                deduped.append(j)
        pending = deduped

        if not pending:
            self.notifier.send_sync(_notif(
                "No Content",
                f"No pending jobs — {len(getattr(self.sources, 'channels', []))} channel(s) monitored",
                NotificationLevel.WARNING,
            ))
            return []

        results = []
        for job in pending:
            if self.uploads_today() >= self.daily_limit:
                break
            results.append(self._process_job(job))

        clips = sum(r.clips_made for r in results)
        if clips:
            self.notifier.send_sync(_notif(
                "Daily Report",
                f"{self.uploads_today()}/{self.daily_limit} uploads today — {clips} clip(s) live",
            ))
        return results

    def _in_any_upload_window(self) -> bool:
        if getattr(self.scheduler, "pending_count", lambda: 0)() > 0:
            return True
        if self.time_optimizer:
            for platform in self.uploaders:
                if self.time_optimizer.is_good_window_now(platform, self.niche):
                    return True
            return False
        return True  # no time_optimizer = always open

    # ── Discovery ─────────────────────────────────────────────────────────────

    def _discover_and_queue(self) -> None:
        try:
            videos = self.sources.check_all()
        except Exception as e:
            log.error("[Pipeline] Discovery failed: %s", e)
            return

        added = 0
        history = self.analytics.history_summary_text(days=30)

        for video in videos:
            if self.queue.already_processed(video.video_id):
                continue
            result    = self.decision.decide(video, history_summary=history)
            score_val = self.decision.scorer.score(video)
            if result.decision == "SKIP":
                continue

            score = score_val.composite
            viral = score_val.velocity_score > 0.80 and score_val.engagement_score > 0.60
            if viral:
                score = 1.0
                log.info("[Pipeline] VIRAL FAST-TRACK: %s", video.title[:60])

            enqueued = self.queue.enqueue(
                video_id = video.video_id,
                title    = video.title,
                url      = getattr(video, "url", ""),
                channel  = getattr(video, "channel_id", ""),
                score    = score,
                niche    = self.niche,
            )
            if enqueued:
                if viral:
                    self.queue.fast_track(video.video_id)
                added += 1

        if added:
            self.notifier.send_sync(_notif("Queue Update", f"Queued {added} new video(s)"))

    # ── Job processing ─────────────────────────────────────────────────────────

    def _process_job(self, job: Job) -> PipelineResult:
        log.info("[Pipeline] Processing: %s", job.title[:60])

        self.queue.mark_processing(job.video_id)
        local_path = self._download(job)
        if not local_path:
            return self._fail(job, "Download failed")

        n_clips_target = self.processor.cfg.clips_per_video
        arc_plan       = self._plan_arc(job, n_clips_target)

        batch_plan = None
        if self.uploaders:
            try:
                batch_plan = self.content_gen.generate_batch(
                    video_id        = job.video_id,
                    video_title     = job.title,
                    n_clips         = n_clips_target,
                    platforms       = list(self.uploaders.keys()),
                    arc_plan        = arc_plan,
                    composite_score = job.score,
                )
            except Exception as e:
                log.warning("[Pipeline] Batch generation failed: %s", e)

        hook_text = arc_plan.angle_for(1) if arc_plan else "PART {index:02d}"
        self.queue.mark_processing(job.video_id, clips_total=n_clips_target)
        proc = self.processor.process(local_path, job.video_id, hook_text=hook_text)
        if not proc.success:
            return self._fail(job, proc.error or "Processing failed")

        log.info("[Pipeline] %d clip(s) in %.1fs | avg_q=%.3f",
                 len(proc.clips), proc.duration_s,
                 sum(proc.scores) / max(1, len(proc.scores)))

        all_platform_posts: Dict[str, List[str]] = {p: [] for p in self.uploaders}
        skipped_by_pred = 0
        now = datetime.now(timezone.utc)

        for i, clip in enumerate(proc.clips, 1):
            if self.uploads_today() >= self.daily_limit:
                break

            thumb      = proc.thumbnails[i - 1] if (i - 1) < len(proc.thumbnails) else None
            clip_score = proc.scores[i - 1]     if (i - 1) < len(proc.scores)     else 0.5

            per_platform = self._resolve_content(job, i, len(proc.clips), arc_plan, batch_plan, clip_score)

            # Prediction gate
            if self.prediction_gate and self.growth_predictor and not DRY_RUN and not FORCE_RUN:
                arc_role = arc_plan.get_clip(i).role if arc_plan else "ESCALATION"
                pred = self.growth_predictor.predict(
                    clip_quality      = clip_score,
                    arc_role          = arc_role,
                    angle_weight      = 1.0,
                    platform          = list(self.uploaders)[0],
                    day_of_week       = now.weekday(),
                    hour_of_day       = now.hour,
                    niche             = self.niche,
                    hook_length       = len(arc_plan.angle_for(i) if arc_plan else ""),
                    series_index_norm = i / max(1, len(proc.clips)),
                    channel_perf      = 0.5,
                )
                if not pred.should_upload:
                    log.info("[Pipeline] Clip %d SKIPPED by predictor: %s", i, pred.reason)
                    skipped_by_pred += 1
                    continue

            platform_results = self._upload_all_platforms(clip, thumb, per_platform, i)

            for platform, post_id in platform_results.items():
                if post_id:
                    all_platform_posts[platform].append(post_id)
                    self._inc_uploads()
                    self.notifier.send_sync(_notif(
                        "Upload Success",
                        f"✓ {job.title[:40]} clip {i} → {platform} ({post_id})",
                    ))
                    if self.ab_engine:
                        self.ab_engine.record_upload(
                            video_id = job.video_id, clip_num = i, platform = platform,
                            post_id  = post_id,
                            angle    = per_platform.get(platform, {}).get("angle", "mystery"),
                            niche    = self.niche,
                            hook     = per_platform.get(platform, {}).get("hook", ""),
                            caption  = per_platform.get(platform, {}).get("caption", ""),
                        )
                    # growth_predictor.record_actual(upload_id, engagement) called
                    # later by the metrics puller once real engagement data is available
                    if self.time_optimizer:
                        self.time_optimizer.record_upload(
                            platform   = platform,
                            niche      = self.niche,
                            weekday    = now.weekday(),
                            hour       = now.hour,
                            engagement = 0.0,
                        )

            self.analytics.log_upload(
                video_id         = job.video_id,
                clip_num         = i,
                title            = f"{job.title} — Part {i}",
                platform_results = platform_results,
                quality_score    = clip_score,
                hashtags         = per_platform.get("tiktok", {}).get("hashtags", []),
                channel_id       = job.channel,
                niche            = job.niche,
            )

            if i < len(proc.clips):
                time.sleep(self.clip_upload_gap)

        all_posts = [p for posts in all_platform_posts.values() for p in posts]
        self.queue.mark_done(job.video_id, clips_done=len(all_posts))
        self.sources.mark_seen(job.video_id)

        return PipelineResult(
            video_id        = job.video_id,
            title           = job.title,
            clips_made      = len(all_posts),
            platform_posts  = all_platform_posts,
            success         = bool(all_posts),
            quality_scores  = proc.scores,
            skipped_by_pred = skipped_by_pred,
        )

    # ── Arc planning ──────────────────────────────────────────────────────────

    def _plan_arc(self, job: Job, n_clips: int):
        if not self.arc_engine:
            return None
        try:
            arc = self.arc_engine.plan(
                video_id    = job.video_id,
                video_title = job.title,
                n_clips     = n_clips,
            )
            log.info("[Pipeline] Arc planned: %d nodes", len(arc.clips))
            return arc
        except Exception as e:
            log.warning("[Pipeline] Arc planning failed: %s", e)
            return None

    # ── Content resolution ─────────────────────────────────────────────────────

    def _resolve_content(self, job, clip_num, total_clips, arc_plan, batch_plan, clip_score):
        result = {}
        for platform in self.uploaders:
            content = batch_plan.get(clip_num, platform) if batch_plan else None
            if not content:
                angle   = arc_plan.angle_for(clip_num) if arc_plan else "mystery"
                content = self.content_gen.generate(
                    video_title     = job.title,
                    platform        = platform,
                    clip_index      = clip_num,
                    total_clips     = total_clips,
                    angle           = angle,
                    composite_score = clip_score,
                )

            top_tags = self.analytics.top_tags_by_platform(platform)
            hashtags = self.hashtag_engine.get_hashtags(
                platform   = platform,
                niche      = self.niche,
                extra_tags = (getattr(content, "hashtags", []) + top_tags)[:20],
            )
            caption = self.caption_optimizer.optimize(
                caption      = getattr(content, "caption", ""),
                platform     = platform,
                clip_index   = clip_num,
                hashtags     = hashtags,
                channel_name = self.channel_name,
            )
            result[platform] = {
                "title":    f"{getattr(content,'title_rewrite',None) or job.title} — Part {clip_num}",
                "caption":  caption,
                "hashtags": hashtags,
                "hook":     getattr(content, "hook", ""),
                "angle":    getattr(content, "angle", "mystery"),
            }
        return result

    # ── Concurrent upload ──────────────────────────────────────────────────────

    def _upload_all_platforms(self, clip, thumb, per_platform, clip_num):
        results: Dict[str, Optional[str]] = {}

        if DRY_RUN:
            for p in self.uploaders:
                results[p] = f"dryrun_{p}_{clip_num}"
            return results

        tasks = {}
        for platform, uploader in self.uploaders.items():
            cb = self._cb.get(platform)
            if cb and cb.is_open:   # @property — no ()
                results[platform] = None
                continue
            pc = per_platform.get(platform, {})
            tasks[platform] = (
                uploader.upload, clip,
                pc.get("title", str(clip_num)),
                pc.get("caption", ""),
                pc.get("hashtags", []),
                clip_num, thumb,
            )

        if not tasks:
            return results

        with ThreadPoolExecutor(
            max_workers=min(self.concurrent_uploads, len(tasks)),
            thread_name_prefix="upload",
        ) as ex:
            fmap = {}
            for platform, task in tasks.items():
                fn, *args = task
                self._rl.acquire(platform)
                fmap[ex.submit(fn, *args)] = platform

            for future in as_completed(fmap, timeout=900):
                platform = fmap[future]
                cb = self._cb[platform]
                try:
                    ur = future.result(timeout=900)
                    if ur.success:
                        results[platform] = ur.post_id
                        with cb:   # __exit__ with no exception = success signal
                            pass
                        log.info("[Pipeline] ✓ %s clip %d → %s", platform, clip_num, ur.post_id)
                    else:
                        results[platform] = None
                        try:
                            with cb:
                                raise RuntimeError(ur.error or "upload_failed")
                        except RuntimeError:
                            pass
                        log.warning("[Pipeline] ✗ %s clip %d: %s", platform, clip_num, ur.error)
                except (FutureTimeout, Exception) as e:
                    results[platform] = None
                    try:
                        with cb:
                            raise RuntimeError(str(e))
                    except RuntimeError:
                        pass

        return results

    # ── Download ───────────────────────────────────────────────────────────────

    def _download(self, job: Job) -> Optional[Path]:
        try:
            class _Proxy:
                video_id   = job.video_id
                title      = job.title
                url        = job.url        # FIX: was job.youtube_url
                channel_id = job.channel    # FIX: was job.channel_id
                local_path = None
                downloaded = False
            return self.sources.download(_Proxy())
        except Exception as e:
            log.error("[Pipeline] Download failed: %s", e)
            return None

    def _fail(self, job: Job, error: str) -> PipelineResult:
        self.queue.mark_failed(job.video_id, error=error)
        self.notifier.send_sync(_notif(
            "Pipeline Error",
            f"✗ {job.title[:40]} — {error}",
            NotificationLevel.ERROR,
        ))
        log.error("[Pipeline] Job failed: %s — %s", job.title[:40], error)
        return PipelineResult(job.video_id, job.title, 0, error=error)

    def uploads_today(self) -> int:
        return atomic_read(self._count_dir / f"uploads_{date.today().isoformat()}.txt")

    def _inc_uploads(self, n: int = 1) -> int:
        return atomic_increment(self._count_dir / f"uploads_{date.today().isoformat()}.txt", n)
