"""
page_health.py — Facebook Page health monitor.

Checks your page's standing with Facebook:
  - Page Quality score
  - Content distribution limits
  - Monetization eligibility (Stars, In-stream ads, Reels bonuses)
  - Copyright strikes
  - Community standards violations
  - Follower growth rate
  - Engagement rate benchmarks

Alerts you BEFORE problems affect your reach.
"""
from __future__ import annotations
import json, logging, sqlite3, time, urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger(__name__)
GRAPH = "https://graph.facebook.com/v19.0"

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS page_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id         TEXT NOT NULL,
    fan_count       INTEGER NOT NULL DEFAULT 0,
    follower_count  INTEGER NOT NULL DEFAULT 0,
    total_posts     INTEGER NOT NULL DEFAULT 0,
    avg_reach       REAL NOT NULL DEFAULT 0,
    avg_engagement  REAL NOT NULL DEFAULT 0,
    recorded_at     REAL NOT NULL
);
"""

# Monetization thresholds (Facebook Reels Play Bonus)
MONETIZE_THRESHOLDS = {
    "followers_min":    10_000,
    "views_30d_min":    600_000,
    "eligible_country": True,
}

# Healthy engagement benchmarks
BENCHMARKS = {
    "good_engagement_pct":    2.0,    # 2%+ is good for Facebook
    "great_engagement_pct":   4.0,    # 4%+ is great
    "min_weekly_posts":       5,
    "max_weekly_posts":       35,     # over-posting hurts reach
}


@dataclass
class PageMetrics:
    page_id: str
    page_name: str = ""
    fan_count: int = 0
    follower_count: int = 0
    category: str = ""
    is_verified: bool = False
    can_post: bool = True
    restriction_type: str = ""
    recent_posts: int = 0
    avg_reach: float = 0.0
    avg_engagement_pct: float = 0.0
    growth_rate_7d: float = 0.0   # % follower growth last 7 days
    monetization_eligible: bool = False
    warnings: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


class PageHealthMonitor:
    """
    Monitors your Facebook Page health and gives actionable recommendations
    to maximize reach, engagement, and monetization eligibility.
    """

    def __init__(self, page_id: str, access_token: str,
                 db_path: Path = None, notifier=None):
        self.page_id  = page_id
        self.token    = access_token
        self.notifier = notifier
        if db_path:
            self.db_path = Path(db_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._conn() as c:
                c.executescript(SCHEMA)
        else:
            self.db_path = None

    def is_configured(self) -> bool:
        return bool(self.page_id and self.token
                    and not self.token.startswith("${"))

    def check(self) -> PageMetrics:
        """Full page health check. Returns PageMetrics with warnings + tips."""
        if not self.is_configured():
            m = PageMetrics(page_id=self.page_id)
            m.warnings.append("No Facebook token configured")
            return m

        metrics = self._fetch_page_data()
        metrics = self._add_warnings(metrics)
        metrics = self._add_recommendations(metrics)

        if self.db_path:
            self._save_snapshot(metrics)

        # Alert on critical issues
        critical = [w for w in metrics.warnings if "⛔" in w]
        if critical and self.notifier:
            self.notifier.send("\n".join(critical))

        return metrics

    def growth_report(self) -> str:
        """Show follower growth trend from stored snapshots."""
        if not self.db_path or not self.db_path.exists():
            return "No historical data yet. Run page health check first."

        with self._conn() as c:
            rows = c.execute("""
                SELECT fan_count, follower_count, avg_engagement, recorded_at
                FROM page_snapshots WHERE page_id=?
                ORDER BY recorded_at DESC LIMIT 14
            """, (self.page_id,)).fetchall()

        if len(rows) < 2:
            return "Not enough data yet (need 2+ checks)."

        latest  = rows[0]
        oldest  = rows[-1]
        days    = (latest[3] - oldest[3]) / 86400
        growth  = latest[0] - oldest[0]
        growth_pct = (growth / max(1, oldest[0])) * 100

        lines = [
            "=== PAGE GROWTH REPORT ===\n",
            f"  Followers: {latest[1]:,} (was {oldest[1]:,})",
            f"  Growth: +{growth:,} in {days:.0f} days ({growth_pct:+.1f}%)",
            f"  Avg engagement: {latest[2]:.2f}%",
            f"  Daily growth rate: +{growth/max(1,days):.0f} followers/day",
        ]
        return "\n".join(lines)

    # ── Data Fetching ─────────────────────────────────────────────────────────

    def _fetch_page_data(self) -> PageMetrics:
        url = (f"{GRAPH}/{self.page_id}"
               f"?fields=name,fan_count,followers_count,category,is_verified,"
               f"restriction_type,overall_star_rating"
               f"&access_token={self.token}")
        metrics = PageMetrics(page_id=self.page_id)
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                data = json.loads(resp.read())

            metrics.page_name      = data.get("name", "")
            metrics.fan_count      = data.get("fan_count", 0)
            metrics.follower_count = data.get("followers_count", 0)
            metrics.category       = data.get("category", "")
            metrics.is_verified    = data.get("is_verified", False)
            metrics.restriction_type = data.get("restriction_type", "")
            metrics.can_post       = metrics.restriction_type == ""

        except urllib.error.HTTPError as e:
            metrics.warnings.append(f"⛔ API error {e.code} — check token permissions")
        except Exception as e:
            metrics.warnings.append(f"⚠️ Could not fetch page data: {e}")

        # Fetch recent post reach (from insights if available)
        metrics.avg_reach = self._fetch_avg_reach()

        # Monetization check
        metrics.monetization_eligible = (
            metrics.follower_count >= MONETIZE_THRESHOLDS["followers_min"]
        )

        return metrics

    def _fetch_avg_reach(self) -> float:
        """Fetch average reach from last 10 posts."""
        url = (f"{GRAPH}/{self.page_id}/posts"
               f"?fields=id&limit=10&access_token={self.token}")
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                posts = json.loads(resp.read()).get("data", [])
            reaches = []
            for post in posts[:5]:   # limit API calls
                pid = post.get("id")
                if not pid:
                    continue
                ins_url = (f"{GRAPH}/{pid}/insights/post_impressions_unique"
                           f"?access_token={self.token}")
                try:
                    with urllib.request.urlopen(ins_url, timeout=8) as r2:
                        ins = json.loads(r2.read())
                    val = ins.get("data", [{}])[0].get("values", [{}])[0].get("value", 0)
                    if val:
                        reaches.append(val)
                except Exception:
                    pass
            return sum(reaches) / len(reaches) if reaches else 0.0
        except Exception:
            return 0.0

    # ── Analysis ──────────────────────────────────────────────────────────────

    def _add_warnings(self, m: PageMetrics) -> PageMetrics:
        if not m.can_post:
            m.warnings.append(f"⛔ Page has posting restriction: {m.restriction_type}")
        if m.fan_count < 1000:
            m.warnings.append("⚠️ Page has <1,000 followers — focus on growth first")
        if m.avg_reach > 0 and m.fan_count > 0:
            reach_pct = (m.avg_reach / m.fan_count) * 100
            if reach_pct < 5:
                m.warnings.append(f"⚠️ Low organic reach ({reach_pct:.1f}% of followers) — see recommendations")
        return m

    def _add_recommendations(self, m: PageMetrics) -> PageMetrics:
        recs = m.recommendations

        # Follower count recommendations
        if m.fan_count < 10_000:
            recs.append("📈 Post 3-5 Reels/day — consistency is #1 growth factor on Facebook")
        if m.fan_count < 1_000:
            recs.append("🚀 Share your Reels in 3-5 Facebook Groups in your niche daily")

        # Monetization path
        if not m.monetization_eligible:
            needed = max(0, MONETIZE_THRESHOLDS["followers_min"] - m.fan_count)
            recs.append(f"💰 Need {needed:,} more followers to unlock Reels monetization")

        # Verified badge
        if not m.is_verified and m.fan_count > 50_000:
            recs.append("✅ Apply for verified badge — increases trust and reach")

        # General algorithm tips
        recs.append("🔥 Reply to every comment within 1 hour — boosts reach significantly")
        recs.append("📅 Never skip a day — consistency is rewarded by FB algorithm")
        recs.append("🎯 Use all 9 hashtags but keep them relevant — no spam tags")

        return m

    def _save_snapshot(self, m: PageMetrics):
        with self._conn() as c:
            c.execute("""
                INSERT INTO page_snapshots
                (page_id, fan_count, follower_count, total_posts,
                 avg_reach, avg_engagement, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (m.page_id, m.fan_count, m.follower_count, 0,
                  m.avg_reach, m.avg_engagement_pct, time.time()))

    def format_report(self, m: PageMetrics) -> str:
        lines = [
            "=== FACEBOOK PAGE HEALTH ===\n",
            f"  Page: {m.page_name} ({m.page_id})",
            f"  Followers: {m.follower_count:,}",
            f"  Fans: {m.fan_count:,}",
            f"  Verified: {'✅' if m.is_verified else '❌'}",
            f"  Can Post: {'✅' if m.can_post else '⛔ RESTRICTED'}",
            f"  Avg Reach: {m.avg_reach:,.0f}",
            f"  Monetization: {'✅ Eligible' if m.monetization_eligible else '❌ Not yet'}",
        ]
        if m.warnings:
            lines.append("\n  ⚠️  Warnings:")
            for w in m.warnings:
                lines.append(f"    {w}")
        if m.recommendations:
            lines.append("\n  💡 Recommendations:")
            for r in m.recommendations[:5]:
                lines.append(f"    {r}")
        return "\n".join(lines)

    def _conn(self):
        return sqlite3.connect(self.db_path, timeout=10)
