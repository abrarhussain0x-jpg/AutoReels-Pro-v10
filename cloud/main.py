#!/usr/bin/env python3
"""
main.py v10.0 — AUTO-REELS PRO CLI Entrypoint.

Commands:
  --check           Validate all platform tokens
  --preflight       Validate runtime config/env before real runs
  --score           Score videos without processing
  --dry-run         Full pipeline, no actual uploads
  --once            One real pipeline run
  --daemon          Continuous mode (15-min loop)
  --scan            List new candidates (no processing)
  --pull-metrics    Pull engagement metrics + retrain models

  # v9
  --time-windows    Show ML-predicted optimal posting windows
  --retrain         Force retrain growth predictor
  --refresh-tokens  Force token refresh for all platforms
  --arc-report      Show narrative arc plan for a video
  --report          Weekly engagement report

  # v10 NEW
  --hook-report     Hook phrase leaderboard per platform/niche
  --velocity-report Engagement velocity for last 20 uploads
  --rotate-accounts Current account rotation status
  --retry-failed    Manually retry dead letter queue
  --comment-sweep   Run comment pull + reply bot
  --thumbnail-report Thumbnail A/B variant results
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

# ── Environment / logging ────────────────────────────────────────────────────
DEBUG = os.environ.get("AUTOREELS_DEBUG", "").strip() == "1"
logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")

# ── Path setup ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from src.config_manager import ConfigManager

# ── Lazy v10 imports ──────────────────────────────────────────────────────────


def _has_api_key(cfg: dict) -> bool:
    key = cfg.get("anthropic_api_key", "")
    return bool(key and not key.startswith("${") and len(key) > 10)


def _load_hook_optimizer(cfg, queue_dir):
    from src.intelligence.hook_optimizer_free import HookOptimizerFree
    ho_cfg = cfg.get("hook_optimizer", {})
    return HookOptimizerFree(
        db_path=queue_dir / "hooks.db",
        niche=cfg.get("niche", "movie"),
        enabled=ho_cfg.get("enabled", True),
        exploration_factor=ho_cfg.get("exploration_factor", 1.5),
        min_trials=ho_cfg.get("min_trials_for_confidence", 10),
    )


def _load_account_rotator(cfg, queue_dir):
    from src.publisher.account_rotator import AccountRotator
    return AccountRotator(db_path=queue_dir / "account_rotation.db", config=cfg)


def _load_velocity_tracker(cfg, queue_dir):
    from src.analytics.velocity_tracker import VelocityTracker
    vc_cfg = cfg.get("velocity_tracker", {})
    return VelocityTracker(
        db_path=queue_dir / "velocity.db",
        pull_schedule_hours=vc_cfg.get("pull_schedule_hours", [1, 6, 24, 72]),
        viral_threshold_vph=vc_cfg.get("viral_threshold_views_per_hour", 500),
    )


def _load_comment_bot(cfg, queue_dir):
    from src.engagement.comment_bot import CommentBot
    cb_cfg = cfg.get("comment_bot", {})
    return CommentBot(
        db_path=queue_dir / "comments.db",
        api_key=cfg.get("anthropic_api_key", ""),
        enabled=cb_cfg.get("enabled", False),
        reply_to_questions=cb_cfg.get("reply_to_questions", True),
        max_replies_per_post=cb_cfg.get("max_replies_per_post", 5),
        pull_at_hours=cb_cfg.get("pull_at_hours", [24, 48]),
        negative_alert_threshold=cb_cfg.get("negative_sentiment_alert_threshold", 0.30),
    )


def _load_retry_engine(cfg, queue_dir, notifier=None):
    from src.resilience.retry_engine import RetryEngine
    re_cfg = cfg.get("retry_engine", {})
    return RetryEngine(
        db_path=queue_dir / "failed.db",
        notifier=notifier,
        max_retries=re_cfg.get("max_retries", 5),
        base_delay_s=float(re_cfg.get("base_delay_seconds", 1)),
        circuit_threshold=re_cfg.get("circuit_breaker_threshold", 3),
        circuit_reset_minutes=re_cfg.get("circuit_reset_minutes", 30),
    )


def _load_time_optimizer_v2(cfg, queue_dir):
    from src.optimizer.time_optimizer_v2 import TimeOptimizerV2
    return TimeOptimizerV2(
        db_path=queue_dir / "time_windows.db",
        audience_timezone=cfg.get("audience_timezone", "America/New_York"),
    )


def _load_thumbnail_ab(cfg, queue_dir):
    from src.processor.thumbnail_ab import ThumbnailABEngine
    tab_cfg = cfg.get("thumbnail_ab", {})
    return ThumbnailABEngine(
        db_path=queue_dir / "thumbnail_ab.db",
        enabled=tab_cfg.get("enabled", True),
        n_variants=tab_cfg.get("variants", 3),
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="AUTO-REELS PRO v10 — Autonomous AI Content Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Pipeline modes
    parser.add_argument("--once",          action="store_true", help="Run pipeline once")
    parser.add_argument("--daemon",        action="store_true", help="Run continuously")
    parser.add_argument("--dry-run",       action="store_true", help="No actual uploads")
    parser.add_argument("--scan",          action="store_true", help="Scan only, no processing")
    parser.add_argument("--check",         action="store_true", help="Validate tokens")
    parser.add_argument("--preflight",     action="store_true", help="Validate runtime readiness")
    parser.add_argument("--score",         action="store_true", help="Score without uploading")
    parser.add_argument("--pull-metrics",  action="store_true", help="Pull engagement metrics")

    # v9
    parser.add_argument("--time-windows",  action="store_true", help="Show posting windows")
    parser.add_argument("--retrain",       action="store_true", help="Force retrain predictor")
    parser.add_argument("--refresh-tokens",action="store_true", help="Force token refresh")
    parser.add_argument("--arc-report",    action="store_true", help="Show narrative arc plan")
    parser.add_argument("--report",        action="store_true", help="Weekly report")

    # v10 NEW
    parser.add_argument("--hook-report",       action="store_true", help="Hook phrase leaderboard")
    parser.add_argument("--velocity-report",   action="store_true", help="Velocity report")
    parser.add_argument("--rotate-accounts",   action="store_true", help="Account rotation status")
    parser.add_argument("--retry-failed",      action="store_true", help="Retry dead letter queue")
    parser.add_argument("--comment-sweep",     action="store_true", help="Run comment bot sweep")
    parser.add_argument("--thumbnail-report",  action="store_true", help="Thumbnail A/B results")

    # v10.1 NEW
    parser.add_argument("--weekly-report",    action="store_true", help="Generate + send weekly report")
    parser.add_argument("--system-status",    action="store_true", help="Show CPU/RAM/Disk health")
    parser.add_argument("--cookie-status",    action="store_true", help="Check yt-dlp cookie health")
    parser.add_argument("--cleanup",          action="store_true", help="Clean old tmp files now")
    parser.add_argument("--queue-status",     action="store_true", help="Show job queue status")
    parser.add_argument("--run",              action="store_true", help="Run full real pipeline")
    parser.add_argument("--page-health",      action="store_true", help="Check Facebook page health")
    parser.add_argument("--monetization",     action="store_true", help="Show monetization earnings estimate")
    parser.add_argument("--audience",         action="store_true", help="Audience behavior analysis")
    parser.add_argument("--reach-windows",    action="store_true", help="Best posting windows for reach")
    parser.add_argument("--engagement-report",action="store_true", help="Per-post engagement report")

    # Dashboard
    parser.add_argument("--dashboard",     action="store_true", help="Start dashboard server")
    parser.add_argument("--config",        default="config/config.yaml", help="Config path")

    args = parser.parse_args()

    # ── Load config ───────────────────────────────────────────────────────────
    config_path = ROOT / args.config
    if not config_path.exists():
        log.error("Config not found: %s", config_path)
        sys.exit(1)

    cm = ConfigManager(config_path)
    cfg = cm.config
    queue_dir = ROOT / "queue"
    try:
        queue_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        log.error("Failed to create queue directory %s: %s", queue_dir, e)
        sys.exit(1)

    log.info("AUTO-REELS PRO v10.0 | niche=%s", cfg.get("niche", "movie"))

    # ── DRY RUN flag ──────────────────────────────────────────────────────────
    if args.dry_run:
        os.environ["AUTOREELS_DRY_RUN"] = "1"
        log.warning("DRY-RUN MODE — no actual uploads will be made")

    # ── v10 Quick Commands ────────────────────────────────────────────────────

    if args.hook_report:
        ho = _load_hook_optimizer(cfg, queue_dir)
        print(ho.report())
        return

    if args.velocity_report:
        vt = _load_velocity_tracker(cfg, queue_dir)
        print(vt.velocity_report())
        return

    if args.rotate_accounts:
        ar = _load_account_rotator(cfg, queue_dir)
        print(ar.status_report())
        return

    if args.retry_failed:
        re = _load_retry_engine(cfg, queue_dir)
        retried = re.retry_dead_letter_queue({})
        print(f"Retried {retried} items from dead letter queue.")
        return

    if args.thumbnail_report:
        tab = _load_thumbnail_ab(cfg, queue_dir)
        print(tab.report())
        return

    if args.weekly_report:
        from src.analytics.weekly_reporter import WeeklyReporter
        reporter = WeeklyReporter(queue_dir, cfg)
        reporter.print_report()
        sent = reporter.send()
        if sent:
            print("\n✅ Report sent to Telegram/Discord!")
        return

    if args.system_status:
        from src.health.system_monitor import SystemMonitor
        mon = SystemMonitor(queue_dir / "system_health.db")
        print(mon.status())
        return

    if args.cookie_status:
        from src.utils.cookie_manager import CookieManager
        yt_cfg = cfg.get("youtube", {})
        cm = CookieManager(ROOT / yt_cfg.get("cookies_file", "config/cookies.txt"))
        print(cm.status())
        return

    if args.cleanup:
        from src.utils.cleanup import AutoCleanup
        ac = AutoCleanup(ROOT, cleanup_after_hours=0)
        stats = ac.run(force=True)
        print(f"Cleaned {stats['files_deleted']} files, freed {stats['bytes_freed']/1e6:.1f} MB")
        return

    if args.queue_status:
        from src.scheduler.job_queue import JobQueue
        jq = JobQueue(queue_dir / "jobs.db")
        print(jq.queue_report())
        return

    if args.run:
        import subprocess
        subprocess.run([sys.executable, str(ROOT / "run_pipeline.py")] + sys.argv[2:])
        return

    if getattr(args, "page_health", False):
        from src.publisher.page_health import PageHealthMonitor
        fb_cfg   = cfg.get("facebook", {})
        accounts = fb_cfg.get("accounts", [])
        if not accounts:
            print("No Facebook accounts configured.")
            return
        acc = accounts[0]
        mon = PageHealthMonitor(acc.get("page_id",""), acc.get("access_token",""),
                                db_path=queue_dir/"page_health.db")
        metrics = mon.check()
        print(mon.format_report(metrics))
        return

    if getattr(args, "monetization", False):
        from src.analytics.monetization import MonetizationTracker
        fb_cfg   = cfg.get("facebook", {})
        accounts = fb_cfg.get("accounts", [])
        acc      = accounts[0] if accounts else {}
        m = MonetizationTracker(db_path=queue_dir/"monetization.db",
                                access_token=acc.get("access_token",""),
                                page_id=acc.get("page_id",""))
        print(m.earnings_report(monthly_plays=0, follower_count=0))
        return

    if getattr(args, "audience", False):
        from src.analytics.audience_analyzer import AudienceAnalyzer
        a = AudienceAnalyzer(analytics_db=queue_dir/"analytics.db",
                             engagement_db=queue_dir/"engagement.db")
        print(a.report())
        return

    if getattr(args, "reach_windows", False):
        from src.publisher.reach_optimizer import ReachOptimizer
        ro = ReachOptimizer(db_path=queue_dir/"reach_optimizer.db",
                            niche=cfg.get("niche","movie"))
        print(ro.schedule_report())
        return

    if getattr(args, "engagement_report", False):
        from src.analytics.engagement_tracker import EngagementTracker
        et = EngagementTracker(db_path=queue_dir/"engagement.db")
        print(et.engagement_report())
        return

    if args.comment_sweep:
        cb = _load_comment_bot(cfg, queue_dir)
        if not cb.enabled:
            print("Comment bot is disabled. Set comment_bot.enabled: true in config.yaml")
            return
        # Sweep recent posts
        fb_cfg = cfg.get("facebook", {})
        accounts = fb_cfg.get("accounts", [])
        if not accounts:
            print("No Facebook accounts configured for comment sweep.")
            return
        print("Comment sweep requires post IDs from analytics DB. "
              "Run --pull-metrics first to populate post IDs.")
        return

    if args.time_windows:
        to = _load_time_optimizer_v2(cfg, queue_dir)
        print(to.time_windows_report())
        return

    if args.check:
        _run_token_check(cfg)
        return

    if args.preflight:
        ok = _run_preflight(cfg, strict=True)
        sys.exit(0 if ok else 2)

    if args.dashboard:
        _start_dashboard(cfg, queue_dir)
        return

    if args.once or args.dry_run:
        import subprocess
        if not args.dry_run and not _run_preflight(cfg, strict=True):
            log.error("Preflight checks failed. Fix config/env and retry.")
            sys.exit(2)
        log.info("Starting single pipeline run (delegating to run_pipeline.py)...")
        cmd = [sys.executable, str(ROOT / "run_pipeline.py")]
        if args.dry_run:
            cmd.append("--dry-run")
        # Forward only arguments supported by run_pipeline.py.
        if args.config != "config/config.yaml":
            cmd.extend(["--config", args.config])
        subprocess.run(cmd)
        return

    if args.daemon:
        log.info("Starting daemon mode (interval=%dmin)...",
                 cfg.get("schedule", {}).get("check_interval_minutes", 15))
        _run_daemon(cfg, queue_dir, args)
        return

    if args.pull_metrics:
        log.info("Pulling engagement metrics...")
        _pull_metrics(cfg, queue_dir)
        return

    if args.scan:
        log.info("Scan mode — listing candidates...")
        _run_scan(cfg, queue_dir)
        return

    if args.report:
        _print_report(cfg, queue_dir)
        return

    # No command → print help
    parser.print_help()


# ── Pipeline Runners ──────────────────────────────────────────────────────────

def _run_pipeline_once(cfg: dict, queue_dir: Path, args) -> None:
    """Bootstrap all v10 engines and run one pipeline cycle."""
    # Auto-select free or paid content generator based on API key
    if _has_api_key(cfg):
        from src.brain.content_gen import ContentGenerator
    else:
        from src.brain.content_gen_free import ContentGeneratorFree as ContentGenerator
        log.info("No API key — using FREE content generator (no AI costs)")
    if _has_api_key(cfg):
        from src.brain.decision_engine import DecisionEngine
    else:
        from src.brain.decision_engine_free import DecisionEngineFree as DecisionEngine
    from src.brain.scorer import VideoScorer
    from src.ab_testing.ab_engine import ABEngine
    from src.analytics.tracker import AnalyticsTracker
    from src.intelligence.hook_optimizer import HookOptimizer
    from src.publisher.account_rotator import AccountRotator
    from src.analytics.velocity_tracker import VelocityTracker
    from src.resilience.retry_engine import RetryEngine
    from src.optimizer.time_optimizer_v2 import TimeOptimizerV2
    from src.processor.thumbnail_ab import ThumbnailABEngine

    api_key = cfg.get("anthropic_api_key", "")
    niche = cfg.get("niche", "movie")
    channel = cfg.get("branding", {}).get("channel_name", "AutoReels")

    # Core engines
    content_gen = ContentGenerator(api_key=api_key, niche=niche, channel_name=channel)
    scorer = VideoScorer(cfg)
    decision = DecisionEngine(
        scorer=scorer,
        content_gen=content_gen,
        ai_threshold_low=cfg.get("ai_threshold_low", 0.01),
        ai_threshold_high=cfg.get("ai_threshold_high", 0.10),
        min_duration_s=cfg.get("min_duration_global", 60),
        max_duration_s=cfg.get("max_duration_global", 7200),
    )
    analytics = AnalyticsTracker(db_path=queue_dir / "analytics.db")
    ab_engine = ABEngine(db_path=queue_dir / "ab_tests.db")

    # v10 engines
    hook_optimizer = _load_hook_optimizer(cfg, queue_dir)
    account_rotator = _load_account_rotator(cfg, queue_dir)
    velocity_tracker = _load_velocity_tracker(cfg, queue_dir)
    retry_engine = _load_retry_engine(cfg, queue_dir)
    time_optimizer = _load_time_optimizer_v2(cfg, queue_dir)
    thumbnail_ab = _load_thumbnail_ab(cfg, queue_dir)

    log.info(
        "Pipeline v10 ready | api=%s hook=%s accounts=%s velocity=%s",
        "✓" if api_key else "✗",
        "✓" if hook_optimizer.enabled else "✗",
        sum(len(v) for v in account_rotator._accounts.values()),
        "✓",
    )

    # Check upload window
    if time_optimizer.is_good_window_now(
        platform=_primary_platform(cfg),
        niche=niche,
    ) or os.environ.get("AUTOREELS_FORCE_RUN") == "1":
        log.info("In optimal upload window — proceeding")
    else:
        log.info("Outside optimal window. Use AUTOREELS_FORCE_RUN=1 to override.")
        if not args.dry_run:
            return

    log.info("Pipeline v10 complete. All engines initialized.")
    log.info("To process real videos, integrate with YouTube monitor and FFmpeg processor.")
    log.info("See src/core/pipeline_v2.py for full orchestration.")


def _run_daemon(cfg: dict, queue_dir: Path, args) -> None:
    """Run pipeline in daemon mode."""
    interval = cfg.get("schedule", {}).get("check_interval_minutes", 15)
    log.info("Daemon started. Interval: %dmin", interval)
    while True:
        try:
            _run_pipeline_once(cfg, queue_dir, args)
        except KeyboardInterrupt:
            log.info("Daemon stopped.")
            break
        except Exception as exc:
            log.error("Pipeline error: %s", exc)
        log.info("Sleeping %dm until next run...", interval)
        time.sleep(interval * 60)


def _run_token_check(cfg: dict) -> None:
    """Validate platform tokens."""
    print("=== TOKEN CHECK ===\n")
    api_key = cfg.get("anthropic_api_key", "")
    print(f"  Anthropic API Key: {'✓ set' if api_key and not api_key.startswith('${') else '✗ missing'}")

    fb_cfg = cfg.get("facebook", {})
    accounts = fb_cfg.get("accounts", [])
    for acc in accounts:
        pid = acc.get("page_id", "")
        tok = acc.get("access_token", "")
        valid = pid and not pid.startswith("${") and tok and not tok.startswith("${")
        print(f"  Facebook Page {pid}: {'✓' if valid else '✗ missing token'}")

    for platform in ["tiktok", "instagram", "youtube_shorts", "threads"]:
        plat_cfg = cfg.get(platform, {})
        disabled = plat_cfg.get("disabled", True)
        print(f"  {platform.capitalize()}: {'⊘ disabled' if disabled else '✓ enabled'}")


def _run_preflight(cfg: dict, strict: bool = False) -> bool:
    """Validate config and environment readiness for execution."""
    print("=== PREFLIGHT CHECK ===")

    failures = []
    warnings = []

    channels = cfg.get("channels", [])
    if not channels:
        failures.append("No channels configured")

    yt_cfg = cfg.get("youtube", {})
    if not yt_cfg.get("cookies_file"):
        warnings.append("youtube.cookies_file not set")

    api_key = cfg.get("anthropic_api_key", "")
    if not (api_key and not str(api_key).startswith("${") and len(str(api_key)) > 10):
        warnings.append("ANTHROPIC_API_KEY missing (free-mode fallback will be used)")

    fb_cfg = cfg.get("facebook", {})
    fb_disabled = fb_cfg.get("disabled", False)
    fb_accounts = fb_cfg.get("accounts", [])
    if not fb_disabled:
        if not fb_accounts:
            failures.append("facebook.accounts missing while facebook is enabled")
        else:
            acc = fb_accounts[0]
            page_id = str(acc.get("page_id", "")).strip()
            token = str(acc.get("access_token", "")).strip()
            if not page_id:
                failures.append("FB_PAGE_ID is empty")
            if not token:
                failures.append("FB_PAGE_ACCESS_TOKEN is empty")

    if strict:
        if failures:
            print("Result: FAIL")
            for item in failures:
                print(f"  - {item}")
            if warnings:
                print("Warnings:")
                for item in warnings:
                    print(f"  - {item}")
            return False
        print("Result: OK")
        if warnings:
            print("Warnings:")
            for item in warnings:
                print(f"  - {item}")
        return True

    if failures:
        print("Result: FAIL")
        for item in failures:
            print(f"  - {item}")
        return False

    print("Result: OK")
    if warnings:
        print("Warnings:")
        for item in warnings:
            print(f"  - {item}")
    return True


def _run_scan(cfg: dict, queue_dir: Path) -> None:
    """Scan YouTube channels and list candidates without processing."""
    channels = cfg.get("channels", [])
    print(f"=== SCAN MODE ===\nMonitoring {len(channels)} channels:\n")
    for ch in channels:
        print(f"  {ch.get('url', 'unknown')}")
    print("\nScan complete. Integrate yt-dlp for real video discovery.")


def _pull_metrics(cfg: dict, queue_dir: Path) -> None:
    """Pull engagement metrics and trigger retraining."""
    vt = _load_velocity_tracker(cfg, queue_dir)
    pending = vt.pending_pulls()
    print(f"=== METRICS PULL ===\n{len(pending)} uploads need metric pulls.")
    for item in pending:
        print(f"  {item['platform']} | {item['upload_id'][:12]} | "
              f"target={item['target_hours']}h | elapsed={item['hours_elapsed']:.1f}h")
    if not pending:
        print("  All caught up! 🎉")


def _print_report(cfg: dict, queue_dir: Path) -> None:
    print("=== WEEKLY REPORT ===")
    vt = _load_velocity_tracker(cfg, queue_dir)
    print(vt.velocity_report())
    ho = _load_hook_optimizer(cfg, queue_dir)
    print(ho.report())


def _start_dashboard(cfg: dict, queue_dir: Path) -> None:
    from src.dashboard.app_v2 import create_dashboard_app
    from src.analytics.velocity_tracker import VelocityTracker
    from src.intelligence.hook_optimizer import HookOptimizer

    vt = _load_velocity_tracker(cfg, queue_dir)
    ho = _load_hook_optimizer(cfg, queue_dir)
    ar = _load_account_rotator(cfg, queue_dir)
    re = _load_retry_engine(cfg, queue_dir)
    to = _load_time_optimizer_v2(cfg, queue_dir)

    app = create_dashboard_app(
        hook_optimizer=ho,
        account_rotator=ar,
        velocity_tracker=vt,
        retry_engine=re,
        time_optimizer=to,
        config=cfg,
    )
    if not app:
        log.error("Flask not available. pip install flask")
        return

    port = cfg.get("dashboard_port", 8888)
    log.info("Starting dashboard on http://localhost:%d", port)
    app.run(host="0.0.0.0", port=port, debug=False)


def _primary_platform(cfg: dict) -> str:
    for p in ["facebook", "tiktok", "instagram", "youtube_shorts"]:
        if not cfg.get(p, {}).get("disabled", True):
            return p
    return "facebook"


if __name__ == "__main__":
    main()

