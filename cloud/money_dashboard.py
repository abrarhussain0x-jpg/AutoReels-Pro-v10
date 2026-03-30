"""
money_dashboard.py — Terminal money & growth dashboard.

Shows everything on one screen:
  💰 Estimated earnings this month
  📈 Follower growth rate
  🔥 Best performing clip this week
  📊 Engagement rate trend
  🎯 Progress to monetization
  ⏰ Next optimal posting time
  🚀 Viral clips count

Run anytime with: python3 money_dashboard.py
"""
from __future__ import annotations
import json, os, sqlite3, sys, time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))


def load_config():
    from src.config_manager import ConfigManager
    try:
        return ConfigManager(ROOT / "config/config.yaml").config
    except Exception:
        return {}


def safe_query(db_path: Path, query: str, params=()) -> list:
    if not db_path.exists():
        return []
    try:
        with sqlite3.connect(db_path, timeout=5) as c:
            return c.execute(query, params).fetchall()
    except Exception:
        return []


def bar(value: float, max_val: float, width: int = 20, char: str = "█") -> str:
    filled = int(width * min(1.0, value / max(1, max_val)))
    return char * filled + "░" * (width - filled)


def color(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m"


def main():
    cfg       = load_config()
    queue_dir = ROOT / "queue"
    channel   = cfg.get("branding", {}).get("channel_name", "AutoReels")
    niche     = cfg.get("niche", "movie")

    # ── Gather data ────────────────────────────────────────────────────────────
    now      = time.time()
    day_ago  = now - 86400
    week_ago = now - 7 * 86400
    month_ago= now - 30 * 86400

    # Uploads today
    uploads_today = safe_query(
        queue_dir / "jobs.db",
        "SELECT COUNT(*) FROM jobs WHERE state='DONE' AND finished_at >= ?",
        (datetime.now().replace(hour=0,minute=0,second=0).timestamp(),)
    )
    uploads_today = uploads_today[0][0] if uploads_today else 0
    daily_limit   = cfg.get("daily_upload_limit", 5)

    # Total uploads
    total_uploads = safe_query(queue_dir / "analytics.db",
                               "SELECT COUNT(*) FROM uploads")
    total_uploads = total_uploads[0][0] if total_uploads else 0

    # Engagement this week
    week_eng = safe_query(
        queue_dir / "engagement.db",
        "SELECT AVG(engagement_rate), SUM(reach), SUM(shares) FROM post_metrics WHERE posted_at >= ?",
        (week_ago,)
    )
    avg_eng  = week_eng[0][0] or 0.0 if week_eng else 0.0
    total_reach = week_eng[0][1] or 0 if week_eng else 0
    total_shares= week_eng[0][2] or 0 if week_eng else 0

    # Monthly plays (estimate from reach)
    month_plays = safe_query(
        queue_dir / "engagement.db",
        "SELECT SUM(plays), SUM(reach) FROM post_metrics WHERE posted_at >= ?",
        (month_ago,)
    )
    monthly_plays = month_plays[0][0] or 0 if month_plays else 0
    monthly_reach = month_plays[0][1] or 0 if month_plays else 0

    # Viral clips
    viral_count = safe_query(
        queue_dir / "velocity.db",
        "SELECT COUNT(*) FROM velocity_uploads WHERE viral_triggered=1"
    )
    viral_count = viral_count[0][0] if viral_count else 0

    # Best clip this week
    best_clip = safe_query(
        queue_dir / "engagement.db",
        "SELECT hook_text, engagement_rate, shares, reach FROM post_metrics "
        "WHERE posted_at >= ? ORDER BY engagement_rate DESC LIMIT 1",
        (week_ago,)
    )

    # Earnings estimate
    country  = "US"
    cpm_rate = 3.00   # conservative estimate
    est_monthly_usd = (monthly_plays / 1000) * cpm_rate
    est_daily_usd   = est_monthly_usd / 30

    # Next posting window
    from src.publisher.reach_optimizer import ReachOptimizer
    try:
        ro = ReachOptimizer(db_path=queue_dir/"reach_optimizer.db", niche=niche)
        should_post, reason = ro.should_post_now()
    except Exception:
        should_post = True
        reason = "Unknown"

    # ── Render dashboard ───────────────────────────────────────────────────────
    W = 60
    print()
    print(color("╔" + "═" * W + "╗", "36"))
    print(color(f"║{'AUTO-REELS PRO v10 — MONEY DASHBOARD':^{W}}║", "36"))
    ts = datetime.now().strftime("%d %b %Y %H:%M")
    hdr2 = f"@{channel} • {niche.upper()} • {ts}"
    print(color(f"║{hdr2:^{W}}║", "36"))
    print(color("╠" + "═" * W + "╣", "36"))

    def row(label: str, value: str, color_code: str = "0"):
        lbl = f"  {label:<22}"
        val = color(f"{value}", color_code)
        padding = W - len(label) - len(value) - 4
        print(color("║", "36") + lbl + val + " " * max(0, padding) + color("║", "36"))

    def section(title: str):
        print(color("╠" + "═" * W + "╣", "36"))
        print(color(f"║  {title:<{W-2}}║", "33"))

    section("💰 EARNINGS")
    row("Est. Monthly",   f"${est_monthly_usd:>8.2f}  {bar(est_monthly_usd, 500)}", "32")
    row("Est. Daily",     f"${est_daily_usd:>8.2f}/day", "32")
    row("Monthly Plays",  f"{monthly_plays:>10,}", "33")
    row("Monthly Reach",  f"{monthly_reach:>10,}", "33")

    section("📈 GROWTH & PERFORMANCE")
    row("Uploads Today",  f"{uploads_today}/{daily_limit}  {bar(uploads_today, daily_limit)}", "36")
    row("Total Uploads",  f"{total_uploads:>10,}", "36")
    row("Avg Engagement", f"{avg_eng:>9.2f}%  {bar(avg_eng, 5.0)}", "32" if avg_eng >= 2 else "31")
    row("Week Reach",     f"{total_reach:>10,}", "36")
    row("Week Shares",    f"{total_shares:>10,}", "35")
    row("Viral Clips",    f"{viral_count:>10}  🚀", "32" if viral_count > 0 else "0")

    section("🏆 BEST CLIP THIS WEEK")
    if best_clip:
        bc = best_clip[0]
        row("Hook",       f"'{bc[0][:30]}'", "33")
        row("Engagement", f"{bc[1]:.2f}%", "32" if bc[1] >= 2 else "31")
        row("Shares",     f"{bc[2]:,}", "35")
        row("Reach",      f"{bc[3]:,}", "36")
    else:
        row("Status",     "No data yet — post your first clip!", "33")

    section("🎯 MONETIZATION PROGRESS")
    followers_needed = max(0, 10000 - 0)  # replace 0 with real count
    plays_needed     = max(0, 600000 - monthly_plays)
    row("Followers Goal",  f"10,000 needed  {bar(0, 10000)}", "33")
    row("Monthly Plays",   f"600K needed    {bar(monthly_plays, 600000)}", "33")
    if monthly_plays >= 600000:
        row("Status",      "✅ ELIGIBLE — Apply now!", "32")
    else:
        row("Plays Needed", f"{plays_needed:,} more this month", "31")

    section("⏰ POSTING STATUS")
    post_status = color("✅ POST NOW!", "32") if should_post else color(f"⏳ {reason[:35]}", "33")
    print(color("║", "36") + f"  {post_status:<{W-2}}" + color("║", "36"))

    print(color("╠" + "═" * W + "╣", "36"))
    section("💡 QUICK ACTIONS")
    actions = [
        "python3 run_pipeline.py          → Run pipeline now",
        "python3 run_pipeline.py --daemon → Run 24/7",
        "python3 main.py --page-health    → Check FB page",
        "python3 main.py --weekly-report  → Send report",
    ]
    for a in actions:
        print(color("║", "36") + f"  {color(a, '2'):<{W-2}}" + color("║", "36"))

    print(color("╚" + "═" * W + "╝", "36"))
    print()


if __name__ == "__main__":
    main()
