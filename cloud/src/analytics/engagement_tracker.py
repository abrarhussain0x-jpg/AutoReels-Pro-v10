"""
engagement_tracker.py — Per-post engagement rate tracker.

Pulls and stores real engagement metrics from Facebook Graph API:
  - Likes, reactions, comments, shares, saves, reach, plays
  - Tracks at 1h, 6h, 24h, 72h for full engagement curve
  - Computes engagement rate = (likes+comments+shares) / reach × 100
  - Identifies top-performing content patterns
  - Feeds data back into hook optimizer and time optimizer
"""
from __future__ import annotations
import json, logging, sqlite3, time, urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger(__name__)
GRAPH = "https://graph.facebook.com/v19.0"

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS post_metrics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id         TEXT NOT NULL,
    platform        TEXT NOT NULL DEFAULT 'facebook',
    video_id        TEXT NOT NULL DEFAULT '',
    clip_num        INTEGER NOT NULL DEFAULT 1,
    niche           TEXT NOT NULL DEFAULT 'movie',
    angle           TEXT NOT NULL DEFAULT 'mystery',
    hook_text       TEXT NOT NULL DEFAULT '',
    caption_length  INTEGER NOT NULL DEFAULT 0,
    hashtag_count   INTEGER NOT NULL DEFAULT 0,
    posted_at       REAL NOT NULL,
    hours_since     REAL NOT NULL DEFAULT 0,
    reach           INTEGER NOT NULL DEFAULT 0,
    plays           INTEGER NOT NULL DEFAULT 0,
    likes           INTEGER NOT NULL DEFAULT 0,
    comments        INTEGER NOT NULL DEFAULT 0,
    shares          INTEGER NOT NULL DEFAULT 0,
    saves           INTEGER NOT NULL DEFAULT 0,
    engagement_rate REAL NOT NULL DEFAULT 0.0,
    pulled_at       REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pm_post   ON post_metrics(post_id);
CREATE INDEX IF NOT EXISTS idx_pm_niche  ON post_metrics(niche, angle);
CREATE INDEX IF NOT EXISTS idx_pm_eng    ON post_metrics(engagement_rate DESC);
"""

PULL_AT_HOURS = [1, 6, 24, 72]


@dataclass
class PostEngagement:
    post_id: str
    reach: int = 0
    plays: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0
    engagement_rate: float = 0.0

    @property
    def total_interactions(self) -> int:
        return self.likes + self.comments + self.shares + self.saves

    @property
    def is_viral(self) -> bool:
        return self.engagement_rate >= 4.0 or self.shares >= 50


class EngagementTracker:
    """Pulls and tracks per-post engagement from Facebook."""

    def __init__(self, db_path: Path, access_token: str = ""):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.token   = access_token
        with self._conn() as c:
            c.executescript(SCHEMA)
        log.info("[EngagementTracker] init db=%s", self.db_path)

    def pull(self, post_id: str, posted_at: float,
             video_id: str = "", clip_num: int = 1,
             niche: str = "movie", angle: str = "mystery",
             hook_text: str = "", caption_len: int = 0,
             hashtag_count: int = 0) -> Optional[PostEngagement]:
        """Pull current metrics for a post and store them."""
        if not self.token or self.token.startswith("${"):
            log.debug("[Tracker] no token — skip pull")
            return None

        metrics = self._fetch_fb_metrics(post_id)
        if not metrics:
            return None

        hours_since = (time.time() - posted_at) / 3600

        with self._conn() as c:
            c.execute("""
                INSERT INTO post_metrics
                (post_id, platform, video_id, clip_num, niche, angle,
                 hook_text, caption_length, hashtag_count, posted_at,
                 hours_since, reach, plays, likes, comments, shares,
                 saves, engagement_rate, pulled_at)
                VALUES (?, 'facebook', ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                post_id, video_id, clip_num, niche, angle,
                hook_text[:50], caption_len, hashtag_count,
                posted_at, hours_since,
                metrics.reach, metrics.plays, metrics.likes,
                metrics.comments, metrics.shares, metrics.saves,
                metrics.engagement_rate, time.time(),
            ))

        log.info("[Tracker] %s %.0fh: reach=%d eng=%.2f%% shares=%d %s",
                 post_id[:15], hours_since, metrics.reach,
                 metrics.engagement_rate, metrics.shares,
                 "🚀VIRAL" if metrics.is_viral else "")
        return metrics

    def top_performers(self, niche: str = "", limit: int = 10) -> List[dict]:
        """Return top posts by engagement rate."""
        where = "WHERE niche=?" if niche else ""
        params = (niche, limit) if niche else (limit,)
        with self._conn() as c:
            rows = c.execute(f"""
                SELECT post_id, niche, angle, hook_text,
                       MAX(reach) as peak_reach,
                       MAX(engagement_rate) as peak_eng,
                       MAX(shares) as peak_shares,
                       posted_at
                FROM post_metrics {where}
                GROUP BY post_id
                ORDER BY peak_eng DESC LIMIT ?
            """, params).fetchall()
        return [
            {"post_id": r[0], "niche": r[1], "angle": r[2],
             "hook": r[3], "reach": r[4], "engagement_rate": r[5],
             "shares": r[6], "posted_at": r[7]}
            for r in rows
        ]

    def best_angles(self, niche: str) -> Dict[str, float]:
        """Return avg engagement per angle for a niche."""
        with self._conn() as c:
            rows = c.execute("""
                SELECT angle, AVG(engagement_rate), COUNT(*)
                FROM post_metrics WHERE niche=? AND hours_since >= 24
                GROUP BY angle ORDER BY AVG(engagement_rate) DESC
            """, (niche,)).fetchall()
        return {r[0]: r[1] for r in rows if r[2] >= 3}

    def engagement_report(self) -> str:
        with self._conn() as c:
            total = c.execute("SELECT COUNT(DISTINCT post_id) FROM post_metrics").fetchone()[0]
            avg_eng = c.execute("SELECT AVG(engagement_rate) FROM post_metrics WHERE hours_since >= 24").fetchone()[0] or 0
            viral = c.execute("SELECT COUNT(DISTINCT post_id) FROM post_metrics WHERE engagement_rate >= 4").fetchone()[0]
            best_angle = c.execute("""
                SELECT angle, AVG(engagement_rate) as avg_eng
                FROM post_metrics WHERE hours_since >= 24
                GROUP BY angle ORDER BY avg_eng DESC LIMIT 1
            """).fetchone()

        lines = [
            "=== ENGAGEMENT REPORT ===\n",
            f"  Posts tracked:    {total}",
            f"  Avg engagement:   {avg_eng:.2f}%",
            f"  Viral posts (≥4%): {viral}",
            f"  Best angle:       {best_angle[0] if best_angle else 'N/A'} "
            f"({best_angle[1]:.2f}% avg)" if best_angle else "",
        ]
        top = self.top_performers(limit=5)
        if top:
            lines.append("\n  🏆 Top 5 Posts:")
            for p in top:
                lines.append(f"    [{p['angle']:<14}] eng={p['engagement_rate']:.1f}% "
                             f"reach={p['reach']:,} hook='{p['hook'][:20]}'")
        return "\n".join(lines)

    def _fetch_fb_metrics(self, post_id: str) -> Optional[PostEngagement]:
        """Fetch engagement metrics from Facebook Graph API."""
        url = (f"{GRAPH}/{post_id}"
               f"?fields=likes.summary(true),comments.summary(true),"
               f"shares,reactions.summary(true)"
               f"&access_token={self.token}")
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                data = json.loads(resp.read())

            likes    = data.get("likes",     {}).get("summary", {}).get("total_count", 0)
            comments = data.get("comments",  {}).get("summary", {}).get("total_count", 0)
            shares   = data.get("shares",    {}).get("count", 0)

            # Try to get reach from insights (requires page_read_engagement)
            reach = self._fetch_reach(post_id)

            eng_rate = 0.0
            if reach > 0:
                eng_rate = ((likes + comments + shares) / reach) * 100

            return PostEngagement(
                post_id=post_id,
                reach=reach,
                likes=likes,
                comments=comments,
                shares=shares,
                engagement_rate=round(eng_rate, 3),
            )
        except Exception as e:
            log.debug("[Tracker] fetch error %s: %s", post_id[:15], e)
            return None

    def _fetch_reach(self, post_id: str) -> int:
        url = (f"{GRAPH}/{post_id}/insights/post_impressions_unique"
               f"?access_token={self.token}")
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
            vals = data.get("data", [{}])[0].get("values", [{}])
            return int(vals[-1].get("value", 0)) if vals else 0
        except Exception:
            return 0

    def _conn(self):
        return sqlite3.connect(self.db_path, timeout=10)
