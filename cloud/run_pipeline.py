"""
run_pipeline.py — Complete end-to-end pipeline runner.

This is the REAL orchestrator that connects every engine:
  YouTube Monitor → Decision Engine → Video Processor
  → Content Generator → Facebook/TikTok Uploader
  → Analytics Tracker → Velocity Tracker → Job Queue

Usage:
    python run_pipeline.py                  # one run
    python run_pipeline.py --daemon         # continuous loop
    python run_pipeline.py --dry-run        # no uploads
    python run_pipeline.py --queue-status   # show queue
"""
from __future__ import annotations

import argparse, logging, os, sys, time
from pathlib import Path
from src.utils.progress import PipelineProgress

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.DEBUG if os.environ.get("AUTOREELS_DEBUG") else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pipeline")

DRY_RUN   = os.environ.get("AUTOREELS_DRY_RUN", "").strip() == "1"
FORCE_RUN = os.environ.get("AUTOREELS_FORCE_RUN","").strip() == "1"


def load_all(cfg: dict, queue_dir: Path):
    """Boot all engines. Returns dict of engine instances."""
    from src.config_manager import ConfigManager
    from src.fetch.youtube_monitor       import YouTubeMonitor
    from src.processor.video_processor   import VideoProcessor
    from src.brain.content_gen_free      import ContentGeneratorFree
    from src.brain.decision_engine_free  import DecisionEngineFree
    from src.brain.scorer                import VideoScorer
    from src.publisher.facebook_uploader import FacebookUploader
    from src.publisher.account_rotator   import AccountRotator
    from src.analytics.tracker           import AnalyticsTracker
    from src.analytics.velocity_tracker  import VelocityTracker
    from src.scheduler.job_queue         import JobQueue
    from src.resilience.retry_engine     import RetryEngine
    from src.intelligence.narrative_arc_free import NarrativeArcEngine
    from src.intelligence.hook_optimizer_free import HookOptimizerFree
    from src.engagement.auto_repost      import AutoRepostEngine
    from src.notifier.notifier           import Notifier
    from src.optimizer.time_optimizer_v2 import TimeOptimizerV2
    from src.processor.thumbnail_generator import ThumbnailGenerator
    from src.processor.dedup_engine       import DedupEngine
    from src.publisher.upload_dispatcher  import UploadDispatcher
    from src.publisher.facebook_uploader  import FacebookUploader
    from src.publisher.tiktok_uploader    import TikTokUploader
    from src.optimizer.caption_optimizer  import CaptionOptimizer
    from src.brain.scorer_v10            import VideoScorerV10
    from src.brain.trend_detector_v10    import TrendDetectorV10
    from src.health.system_monitor       import SystemMonitor
    from src.utils.cleanup               import AutoCleanup
    from src.utils.progress              import PipelineProgress
    from src.resilience.token_refresher  import TokenRefresher
    from src.publisher.fb_algorithm      import FacebookAlgorithmOptimizer
    from src.publisher.first_comment     import FirstCommentPoster
    from src.publisher.reach_optimizer   import ReachOptimizer
    from src.publisher.page_health       import PageHealthMonitor
    from src.analytics.engagement_tracker import EngagementTracker
    from src.analytics.monetization      import MonetizationTracker
    from src.analytics.audience_analyzer import AudienceAnalyzer
    from src.processor.end_card          import EndCardBurner
    from src.publisher.caption_ab_tester import CaptionABTester
    from src.engagement.auto_reply       import AutoReplyBot
    from src.scheduler.multiday_scheduler import MultiDayScheduler

    niche   = cfg.get("niche", "movie")
    channel = cfg.get("branding", {}).get("channel_name", "AutoReels")
    api_key = cfg.get("anthropic_api_key", "")
    has_key = bool(api_key and not api_key.startswith("${") and len(api_key) > 10)

    # Core
    # Build VideoScorer using configured scoring weights (do NOT pass the whole cfg as feedback DB)
    scorer_weights = cfg.get("scoring_weights", None)
    scorer = VideoScorer(
        feedback_db=None,
        trend_topics=None,
        weights=scorer_weights,
        process_threshold=float(cfg.get("process_threshold", 0.35)),
        defer_threshold=float(cfg.get("defer_threshold", 0.20)),
    )
    decision = DecisionEngineFree(
        scorer=scorer,
        ai_threshold_low=float(cfg.get("ai_threshold_low", 0.01)),
        max_duration_s=int(cfg.get("max_duration_global", 7200)),
        min_duration_s=int(cfg.get("min_duration_global", 60)),
    )
    content_gen = ContentGeneratorFree(niche=niche, channel_name=channel)

    # YouTube
    yt_cfg      = cfg.get("youtube", {})
    yt_monitor  = YouTubeMonitor(cfg, cookies_file=yt_cfg.get("cookies_file", "config/cookies.txt"))

    # Processor
    processor   = VideoProcessor(cfg)

    # Publishers
    fb_cfg      = cfg.get("facebook", {})
    fb_accounts = fb_cfg.get("accounts", [])
    fb_uploader = None
    if fb_accounts and not fb_cfg.get("disabled", False):
        acc = fb_accounts[0]
        fb_uploader = FacebookUploader(
            page_id=acc.get("page_id",""),
            access_token=acc.get("access_token",""),
            published=fb_cfg.get("published", True),
            upload_as_reel=fb_cfg.get("upload_as_reel", True),
        )

    # Analytics + Queue
    analytics  = AnalyticsTracker(db_path=queue_dir / "analytics.db")
    velocity   = VelocityTracker(db_path=queue_dir / "velocity.db")
    job_queue  = JobQueue(db_path=queue_dir / "jobs.db")
    retry_eng  = RetryEngine(db_path=queue_dir / "failed.db")
    arc_engine = NarrativeArcEngine(niche=niche)
    hook_opt   = HookOptimizerFree(db_path=queue_dir / "hooks.db", niche=niche)
    notifier   = Notifier(cfg)
    time_opt   = TimeOptimizerV2(db_path=queue_dir / "time_windows.db",
                                  audience_timezone=cfg.get("audience_timezone","UTC"))
    repost_eng = AutoRepostEngine(
        analytics_db=queue_dir / "analytics.db",
        repost_db=queue_dir / "repost_history.db",
    )

    log.info("Engines: fb=%s key=%s niche=%s",
             "✓" if fb_uploader and fb_uploader.is_configured() else "✗",
             "✓" if has_key else "free-mode",
             niche)

    # New engines
    thumb_gen    = ThumbnailGenerator(channel_name=channel,
                                      theme=cfg.get("branding",{}).get("theme","classic"))
    # Dedup threshold: accept integer (hamming) or fractional config (0-1) -> scale
    raw_thresh = cfg.get("dedup_threshold", 8)
    thresh_val = 8
    # Handle numeric types directly
    if isinstance(raw_thresh, int):
        thresh_val = raw_thresh
    elif isinstance(raw_thresh, float):
        if 0 < raw_thresh <= 1:
            thresh_val = max(1, int(round((1.0 - raw_thresh) * 64)))
        else:
            thresh_val = int(round(raw_thresh))
    else:
        # Try parsing from string
        try:
            ival = int(str(raw_thresh))
            thresh_val = ival
        except Exception:
            try:
                f = float(str(raw_thresh))
                if 0 < f <= 1:
                    thresh_val = max(1, int(round((1.0 - f) * 64)))
                else:
                    thresh_val = int(round(f))
            except Exception:
                thresh_val = 8

    dedup        = DedupEngine(db_path=queue_dir / "dedup.db",
                               threshold=int(thresh_val))
    cap_opt      = CaptionOptimizer()
    scorer_v10   = VideoScorerV10(cfg)
    trend_det    = TrendDetectorV10(niche=niche,
                                    cookies_file=yt_cfg.get("cookies_file",""),
                                    cache_path=queue_dir / "trend_cache.json")
    sys_mon      = SystemMonitor(db_path=queue_dir / "system_health.db",
                                 notifier=notifier)
    cleanup_eng  = AutoCleanup(base_dir=ROOT,
                               cleanup_after_hours=int(cfg.get("cleanup_after_hours",72)))
    tok_refresh  = TokenRefresher(db_path=queue_dir / "token_state.db",
                                  cfg=cfg, notifier=notifier)

    # Build uploaders dict for dispatcher
    uploaders = {}
    if fb_uploader and fb_uploader.is_configured():
        uploaders["facebook"] = fb_uploader
    tt_cfg = cfg.get("tiktok", {})
    if not tt_cfg.get("disabled", True):
        tt_accs = tt_cfg.get("accounts", [])
        tt_tok  = tt_accs[0].get("access_token","") if tt_accs else tt_cfg.get("access_token","")
        if tt_tok and not tt_tok.startswith("${"):
            uploaders["tiktok"] = TikTokUploader(
                access_token=tt_tok,
                privacy_level=tt_cfg.get("privacy_level","PUBLIC_TO_EVERYONE"),
            )
    account_rotator = AccountRotator(db_path=queue_dir / "account_rotation.db", config=cfg)

    # FB Algorithm engines
    fb_algo      = FacebookAlgorithmOptimizer(channel_name=channel, niche=niche)
    fb_accounts  = cfg.get("facebook", {}).get("accounts", [])
    fb_token     = fb_accounts[0].get("access_token","") if fb_accounts else ""
    fb_pid       = fb_accounts[0].get("page_id","") if fb_accounts else ""
    first_cmnt   = FirstCommentPoster(page_id=fb_pid, access_token=fb_token)
    reach_opt    = ReachOptimizer(db_path=queue_dir / "reach_optimizer.db", niche=niche)
    page_health  = PageHealthMonitor(page_id=fb_pid, access_token=fb_token,
                                     db_path=queue_dir / "page_health.db",
                                     notifier=notifier)
    eng_tracker  = EngagementTracker(db_path=queue_dir / "engagement.db",
                                     access_token=fb_token)
    monetize     = MonetizationTracker(db_path=queue_dir / "monetization.db",
                                       access_token=fb_token, page_id=fb_pid,
                                       audience_country="US")
    audience     = AudienceAnalyzer(analytics_db=queue_dir / "analytics.db",
                                    engagement_db=queue_dir / "engagement.db")
    end_carder   = EndCardBurner(style="minimal", duration=2.5)
    cap_ab       = CaptionABTester(db_path=queue_dir / "caption_ab.db")
    auto_reply   = AutoReplyBot(page_id=fb_pid, access_token=fb_token,
                                channel_name=channel, enabled=True)
    multiday     = MultiDayScheduler(db_path=queue_dir / "multiday.db", niche=niche)
    dispatcher = UploadDispatcher(uploaders, retry_engine=retry_eng,
                                   account_rotator=account_rotator)

    return {
        "scorer": scorer_v10, "decision": decision, "content_gen": content_gen,
        "yt_monitor": yt_monitor, "processor": processor,
        "fb_uploader": fb_uploader, "analytics": analytics,
        "velocity": velocity, "job_queue": job_queue,
        "retry_eng": retry_eng, "arc_engine": arc_engine,
        "hook_opt": hook_opt, "notifier": notifier,
        "time_opt": time_opt, "repost_eng": repost_eng,
        "thumb_gen": thumb_gen, "dedup": dedup, "cap_opt": cap_opt,
        "trend_det": trend_det, "sys_mon": sys_mon, "cleanup_eng": cleanup_eng,
        "tok_refresh": tok_refresh, "dispatcher": dispatcher,
        "fb_algo": fb_algo, "first_cmnt": first_cmnt, "reach_opt": reach_opt,
        "cap_ab": cap_ab, "auto_reply": auto_reply, "multiday": multiday,
        "page_health": page_health, "eng_tracker": eng_tracker,
        "monetize": monetize, "audience": audience, "end_carder": end_carder,
    }


def run_once(cfg: dict, queue_dir: Path, engines: dict) -> int:
    """
    Full pipeline: scan → decide → download → clip → caption → upload.
    Returns number of clips uploaded.
    """
    daily_limit = int(cfg.get("daily_upload_limit", 5))
    clips_per   = int(cfg.get("clips_per_video", 10))
    clip_length = int(cfg.get("clip_length_seconds", 55))
    niche       = cfg.get("niche", "movie")
    channel     = cfg.get("branding", {}).get("channel_name", "AutoReels")

    yt   = engines["yt_monitor"]
    dec  = engines["decision"]
    pro  = engines["processor"]
    gen  = engines["content_gen"]
    fb   = engines["fb_uploader"]
    aq   = engines["job_queue"]
    vel  = engines["velocity"]
    arc  = engines["arc_engine"]
    ho   = engines["hook_opt"]
    re   = engines["retry_eng"]
    disp      = engines.get("dispatcher")
    dedup     = engines.get("dedup")
    tgen      = engines.get("thumb_gen")
    capo      = engines.get("cap_opt")
    trend     = engines.get("trend_det")
    smon      = engines.get("sys_mon")
    cln       = engines.get("cleanup_eng")
    fb_algo   = engines.get("fb_algo")
    first_cmt = engines.get("first_cmnt")
    reach_opt = engines.get("reach_opt")
    end_card  = engines.get("end_carder")
    eng_track  = engines.get("eng_tracker")
    cap_ab     = engines.get("cap_ab")
    auto_rply  = engines.get("auto_reply")
    multiday   = engines.get("multiday")

    # System health gate
    if smon and not smon.check().ok:
        log.warning("System resources low — waiting...")
        smon.wait_until_ok(max_wait=300)

    # Get trending keywords for caption injection
    trending_kws = trend.get_trending_keywords(10) if trend else []
    if trending_kws:
        log.info("Trending keywords: %s", trending_kws[:5])

    prog = PipelineProgress(len(engines["yt_monitor"].channels), clips_per)

    tmp_dir = queue_dir / "tmp"
    tmp_dir.mkdir(exist_ok=True)

    # Check daily limit
    today_uploads = _count_today_uploads(queue_dir)
    if today_uploads >= daily_limit:
        log.info("Daily limit reached (%d/%d)", today_uploads, daily_limit)
        return 0

    log.info("=== PIPELINE RUN | daily=%d/%d ===", today_uploads, daily_limit)

    # 1. Scan YouTube channels
    log.info("Scanning YouTube channels...")
    videos = yt.scan_all()
    if not videos:
        log.info("No new videos found — checking existing pending jobs")
        # If discovery found nothing, attempt to process any manually-enqueued jobs
        pending = aq.pending(limit=5)
        pending_videos = []
        for job in pending:
            # Fetch fresh metadata for the queued URL
            meta = yt._get_metadata(job.url)
            if not meta:
                # Try again without cookies (some cookies can cause geo/restricted behaviors)
                orig_cookies = getattr(yt, "cookies", None)
                try:
                    yt.cookies = ""
                    meta = yt._get_metadata(job.url)
                finally:
                    if orig_cookies is not None:
                        yt.cookies = orig_cookies
            if not meta:
                log.warning("Failed to fetch metadata for queued job %s — marking failed", job.video_id)
                aq.mark_failed(job.video_id, "metadata fetch failed")
                continue
            pending_videos.append(meta)
        if not pending_videos:
            log.info("No pending jobs usable either")
            return 0
        videos = pending_videos
        log.info("Processing %d queued jobs", len(videos))
    log.info("Found %d candidate videos", len(videos))

    total_uploaded = 0

    for video in videos:
        if today_uploads + total_uploaded >= daily_limit:
            log.info("Daily limit reached — stopping")
            break

        if aq.already_processed(video.video_id):
            log.debug("Skip %s — already processed", video.video_id)
            continue

        # 2. Decision
        result = dec.decide(video)
        if result.decision != "PROCESS":
            log.info("Skip %s: %s", video.video_id, result.reason)
            aq.mark_skipped(video.video_id, result.reason)
            continue

        log.info("PROCESS: %s (score=%.3f angle=%s)", video.title[:50], result.score, result.angle)
        aq.enqueue(video.video_id, video.title, video.url, video.channel,
                   score=result.score, niche=niche)
        aq.mark_processing(video.video_id, clips_per)

        # 3. Download
        src_path = yt.download(video, tmp_dir / video.video_id)
        if not src_path:
            aq.mark_failed(video.video_id, "download failed")
            continue

        # 4. Get duration + build clip times
        duration = pro.get_duration(src_path)
        if duration < 60:
            aq.mark_failed(video.video_id, f"too short: {duration:.0f}s")
            src_path.unlink(missing_ok=True)
            continue

        actual_clips = min(clips_per, int(duration // clip_length))
        clip_times   = pro.smart_clip_times(duration, actual_clips,
                                            clip_length=clip_length)

        # 5. Plan narrative arc
        arc_plan = arc.plan(video.video_id, video.title, len(clip_times))

        # 6. Generate content for all clips
        batch = gen.generate_batch(
            video_id=video.video_id,
            video_title=video.title,
            n_clips=len(clip_times),
            platforms=["facebook"],
            arc_plan=arc_plan,
        )

        # 7. Process + upload clips
        clips_done = 0
        out_dir = tmp_dir / video.video_id / "clips"
        out_dir.mkdir(parents=True, exist_ok=True)

        for i, clip_time in enumerate(clip_times, 1):
            if today_uploads + total_uploaded + clips_done >= daily_limit:
                break

            content = batch.get(i, "facebook")
            hook    = ho.get_best_hook("facebook", niche, result.angle).phrase
            clip_time["hook_text"] = hook

            # Process clip
            proc_results = pro.process_all_clips(src_path, video.video_id, out_dir, [clip_time])
            if not proc_results or not proc_results[0].success:
                log.warning("Clip %d processing failed", i)
                continue

            clip_path = proc_results[0].clip_path

            # Dedup check
            if dedup and dedup.is_duplicate(clip_path):
                log.info("[Dedup] clip %d is duplicate — skip", i)
                clip_path.unlink(missing_ok=True)
                continue

            # FB Algorithm optimized caption + first comment
            base_caption = content.caption if content else f"Part {i} 🎬 Follow {channel}!"
            tags = content.hashtags if content else ["movierecap", "viral"]

            hook_phrase = ho.get_best_hook("facebook", niche, result.angle).phrase

            # Use Caption A/B tester for best-performing formula
            if cap_ab:
                ab_sel = cap_ab.select_caption(
                    video.title, i, len(clip_times), channel, niche, "facebook", result.angle
                )
                caption_body = ab_sel.caption_text
                cap_type     = ab_sel.caption_type
            else:
                caption_body = base_caption
                cap_type     = "story"

            if fb_algo:
                optimized = fb_algo.optimize(
                    base_caption=caption_body,
                    video_title=video.title,
                    clip_index=i,
                    total_clips=len(clip_times),
                    hook_text=hook_phrase,
                    angle=result.angle,
                    hashtags=tags,
                )
                caption            = optimized.caption
                first_comment_text = optimized.first_comment
                hook_text_overlay  = optimized.hook_overlay
                log.info("[FBAlgo] type=%s reach_mult=%.1fx", cap_type, optimized.predicted_reach_multiplier)
            else:
                caption = capo.optimize(base_caption, "facebook", i, tags,
                                        trending_kws, channel) if capo else base_caption
                first_comment_text = f"🔥 Part {i+1} is already up! Follow {channel}!"
                hook_text_overlay  = ho.get_best_hook("facebook", niche, result.angle).phrase

            # Generate thumbnail
            thumb_path = None
            if tgen:
                frame_path = out_dir / f"{video.video_id}_clip{i:02d}_frame.jpg"
                pro.extract_thumbnail(clip_path, 5.0, frame_path)
                thumb_path = out_dir / f"{video.video_id}_clip{i:02d}_thumb.jpg"
                tgen.generate(frame_path, ho.get_best_hook("facebook", niche,
                              result.angle).phrase, video.title, i, thumb_path)

            if DRY_RUN:
                log.info("[DRY-RUN] would upload clip %d: %s", i, clip_path.name)
                clips_done += 1
                if dedup:
                    dedup.register(clip_path, video.video_id, i)
                continue

            # Upload to ALL configured platforms via dispatcher
            if disp and disp.uploaders:
                summary = disp.upload(
                    clip_path=clip_path, caption=caption,
                    video_id=video.video_id, clip_num=i,
                    thumbnail_path=thumb_path,
                    gap_seconds=int(cfg.get("clip_upload_gap_seconds", 45)),
                )
                if summary.any_success:
                    # Register in velocity tracker for each platform
                    for pres in summary.results:
                        if pres.success:
                            uid = f"{video.video_id}_{i}_{pres.platform}"
                            vel.register_upload(uid, video.video_id,
                                                pres.platform, pres.post_id, i, niche)
                            # Post first comment (boosts FB algorithm velocity)
                            if first_cmt and pres.platform == "facebook" and pres.post_id:
                                import threading
                                t = threading.Thread(
                                    target=first_cmt.post_and_pin,
                                    args=(pres.post_id, first_comment_text, 30),
                                    daemon=True
                                )
                                t.start()
                            # Track engagement for learning
                            if eng_track and pres.post_id:
                                log.debug("[Pipeline] registered %s for engagement tracking", pres.post_id)

                            # Auto-reply bot (starts 2 hours after posting)
                            if auto_rply and pres.platform == "facebook" and pres.post_id:
                                import threading
                                def delayed_reply(pid=pres.post_id, nxt=i+1):
                                    import time as _t
                                    _t.sleep(7200)   # wait 2h for comments to accumulate
                                    count = auto_rply.reply_to_post(pid, nxt)
                                    log.info("[AutoReply] replied to %d comments on %s", count, pid[:15])
                                threading.Thread(target=delayed_reply, daemon=True).start()

                            # Register in caption AB tester
                            if cap_ab and pres.post_id:
                                cap_ab.register_upload(
                                    pres.post_id, cap_type, niche, pres.platform,
                                    caption[:80]
                                )
                    if dedup:
                        dedup.register(clip_path, video.video_id, i)
                    clips_done += 1
                    log.info("✅ clip %d → %s (predicted reach=%.1fx)",
                             i, summary.success_platforms,
                             optimized.predicted_reach_multiplier if fb_algo else 1.0)
                    if prog:
                        prog.upload_done(i, ",".join(summary.success_platforms))
                else:
                    log.warning("❌ clip %d failed on all platforms", i)
                    if prog:
                        prog.upload_failed(i)
            else:
                log.warning("No uploaders configured — add FB_PAGE_ID + FB_PAGE_ACCESS_TOKEN to .env")
                break

        # 8. Cleanup
        try:
            src_path.unlink(missing_ok=True)
        except Exception:
            pass

        aq.mark_done(video.video_id, clips_done)
        total_uploaded += clips_done
        log.info("Video done: %s | %d clips uploaded", video.video_id, clips_done)

        # Auto-cleanup tmp files for this video
        if cln:
            cln.run()

    log.info("=== RUN COMPLETE | uploaded=%d ===", total_uploaded)
    return total_uploaded


def _count_today_uploads(queue_dir: Path) -> int:
    """Count uploads done today from job queue."""
    try:
        import sqlite3, time
        from datetime import datetime
        db = queue_dir / "jobs.db"
        if not db.exists():
            return 0
        today_start = datetime.now().replace(hour=0, minute=0, second=0).timestamp()
        with sqlite3.connect(db, timeout=5) as c:
            row = c.execute(
                "SELECT COUNT(*) FROM jobs WHERE state='DONE' AND finished_at >= ?",
                (today_start,)
            ).fetchone()
        return row[0] if row else 0
    except Exception:
        return 0


def main():
    parser = argparse.ArgumentParser(description="AUTO-REELS v10 Pipeline Runner")
    parser.add_argument("--daemon",        action="store_true")
    parser.add_argument("--dry-run",       action="store_true")
    parser.add_argument("--queue-status",  action="store_true")
    parser.add_argument("--repost-check",  action="store_true")
    parser.add_argument("--config", default="config/config.yaml")
    args = parser.parse_args()

    if args.dry_run:
        os.environ["AUTOREELS_DRY_RUN"] = "1"

    from src.config_manager import ConfigManager
    cfg       = ConfigManager(ROOT / args.config).config
    queue_dir = ROOT / "queue"
    queue_dir.mkdir(exist_ok=True)

    if args.queue_status:
        from src.scheduler.job_queue import JobQueue
        q = JobQueue(queue_dir / "jobs.db")
        print(q.queue_report())
        return

    if args.repost_check:
        from src.engagement.auto_repost import AutoRepostEngine
        re = AutoRepostEngine(queue_dir / "analytics.db", queue_dir / "repost_history.db")
        candidates = re.find_candidates()
        print(f"Repost candidates: {len(candidates)}")
        for c in candidates:
            print(f"  {c.video_id} clip{c.clip_num} eng={c.engagement:.1f}%")
        return

    engines = load_all(cfg, queue_dir)

    if args.daemon:
        interval = cfg.get("schedule", {}).get("check_interval_minutes", 15)
        log.info("Daemon mode — interval=%dmin", interval)
        while True:
            try:
                run_once(cfg, queue_dir, engines)
            except KeyboardInterrupt:
                break
            except Exception as e:
                log.error("Pipeline error: %s", e)
            log.info("Sleeping %dm...", interval)
            time.sleep(interval * 60)
    else:
        run_once(cfg, queue_dir, engines)


if __name__ == "__main__":
    main()
