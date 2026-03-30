"""
tracker.py v8.0 — SQLite analytics engine.

New in v8:
  • channel_performance() — feeds VideoScorer channel weight
  • top_tags_by_platform() — feeds HashtagEngine
  • history_summary_text() — feeds DecisionEngine context
  • weekly_report_text()   — CLI --report + Telegram weekly
  • Niche column on uploads for per-niche analytics
  • Index on platform + uploaded_at for fast aggregates
"""

import logging
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS uploads (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id        TEXT    NOT NULL,
    clip_num        INTEGER NOT NULL DEFAULT 1,
    title           TEXT    NOT NULL DEFAULT '',
    platform        TEXT    NOT NULL,
    post_id         TEXT    NOT NULL DEFAULT '',
    channel_id      TEXT    NOT NULL DEFAULT '',
    niche           TEXT    NOT NULL DEFAULT 'general',
    quality_score   REAL    NOT NULL DEFAULT 0.0,
    uploaded_at     REAL    NOT NULL,
    engagement_rate REAL    NOT NULL DEFAULT 0.0,
    UNIQUE(video_id, clip_num, platform)
);

CREATE TABLE IF NOT EXISTS performance (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    upload_id       INTEGER NOT NULL REFERENCES uploads(id),
    views           INTEGER NOT NULL DEFAULT 0,
    likes           INTEGER NOT NULL DEFAULT 0,
    shares          INTEGER NOT NULL DEFAULT 0,
    saves           INTEGER NOT NULL DEFAULT 0,
    comments        INTEGER NOT NULL DEFAULT 0,
    engagement      REAL    NOT NULL DEFAULT 0.0,
    pulled_at       REAL    NOT NULL DEFAULT 0,
    pull_attempt    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS daily_stats (
    date            TEXT    NOT NULL,
    platform        TEXT    NOT NULL DEFAULT 'all',
    uploads         INTEGER NOT NULL DEFAULT 0,
    total_views     INTEGER NOT NULL DEFAULT 0,
    total_likes     INTEGER NOT NULL DEFAULT 0,
    avg_engagement  REAL    NOT NULL DEFAULT 0.0,
    PRIMARY KEY (date, platform)
);

CREATE TABLE IF NOT EXISTS hashtag_performance (
    tag             TEXT    NOT NULL,
    platform        TEXT    NOT NULL,
    uses            INTEGER NOT NULL DEFAULT 0,
    total_views     INTEGER NOT NULL DEFAULT 0,
    total_likes     INTEGER NOT NULL DEFAULT 0,
    avg_engagement  REAL    NOT NULL DEFAULT 0.0,
    last_used       REAL    NOT NULL DEFAULT 0,
    PRIMARY KEY (tag, platform)
);

CREATE TABLE IF NOT EXISTS channel_stats (
    channel_id      TEXT    NOT NULL,
    videos_used     INTEGER NOT NULL DEFAULT 0,
    total_views     INTEGER NOT NULL DEFAULT 0,
    avg_engagement  REAL    NOT NULL DEFAULT 0.0,
    performance     REAL    NOT NULL DEFAULT 0.5,
    updated_at      REAL    NOT NULL DEFAULT 0,
    PRIMARY KEY (channel_id)
);

CREATE INDEX IF NOT EXISTS idx_uploads_platform   ON uploads(platform, uploaded_at);
CREATE INDEX IF NOT EXISTS idx_uploads_channel    ON uploads(channel_id);
CREATE INDEX IF NOT EXISTS idx_uploads_video      ON uploads(video_id);
CREATE INDEX IF NOT EXISTS idx_perf_upload        ON performance(upload_id);
"""


class AnalyticsTracker:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)
            # Backfill older DBs that lack engagement_rate column.
            cols = [r[1] for r in c.execute("PRAGMA table_info(uploads)").fetchall()]
            if "engagement_rate" not in cols:
                log.info("[AnalyticsTracker] Adding missing column engagement_rate to uploads")
                c.execute("ALTER TABLE uploads ADD COLUMN engagement_rate REAL NOT NULL DEFAULT 0.0")

    # ── Upload logging ──────────────────────────────────────────────────────

    def log_upload(
        self,
        video_id:         str,
        clip_num:         int,
        title:            str,
        platform_results: Dict[str, Optional[str]],
        quality_score:    float       = 0.0,
        hashtags:         List[str]   = None,
        channel_id:       str         = "",
        niche:            str         = "general",
    ) -> None:
        now = time.time()
        with self._conn() as c:
            for platform, post_id in platform_results.items():
                if not post_id:
                    continue
                c.execute(
                    """INSERT OR REPLACE INTO uploads
                       (video_id, clip_num, title, platform, post_id,
                        channel_id, niche, quality_score, uploaded_at)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (video_id, clip_num, title, platform, post_id,
                     channel_id, niche, quality_score, now),
                )
                uid = c.execute(
                    "SELECT id FROM uploads WHERE video_id=? AND clip_num=? AND platform=?",
                    (video_id, clip_num, platform)
                ).fetchone()
                if uid:
                    c.execute(
                        "INSERT OR IGNORE INTO performance (upload_id, pulled_at) VALUES (?,0)",
                        (uid[0],)
                    )

                # Update daily stats
                day = datetime.now(timezone.utc).date().isoformat()
                c.execute(
                    """INSERT INTO daily_stats (date, platform, uploads)
                       VALUES (?,?,1)
                       ON CONFLICT(date, platform) DO UPDATE SET uploads=uploads+1""",
                    (day, platform)
                )

            # Track hashtag uses
            if hashtags:
                for tag in hashtags:
                    for platform in platform_results:
                        if platform_results.get(platform):
                            c.execute(
                                """INSERT INTO hashtag_performance (tag, platform, uses, last_used)
                                   VALUES (?,?,1,?)
                                   ON CONFLICT(tag,platform) DO UPDATE
                                   SET uses=uses+1, last_used=?""",
                                (tag, platform, now, now)
                            )

    def record_metrics(
        self,
        post_id:  str,
        platform: str,
        metrics:  Dict,
        attempt:  int = 1,
    ) -> None:
        views    = int(metrics.get("views",    0))
        likes    = int(metrics.get("likes",    0))
        shares   = int(metrics.get("shares",   0))
        saves    = int(metrics.get("saves",    0))
        comments = int(metrics.get("comments", 0))
        eng      = round(
            (likes + shares * 2 + saves * 3 + comments * 2) / max(1, views) * 100, 4
        )
        with self._conn() as c:
            row = c.execute(
                "SELECT id FROM uploads WHERE post_id=? AND platform=?",
                (post_id, platform)
            ).fetchone()
            if not row:
                return
            uid = row[0]
            c.execute(
                """UPDATE performance
                   SET views=?, likes=?, shares=?, saves=?, comments=?,
                       engagement=?, pulled_at=?, pull_attempt=?
                   WHERE upload_id=?""",
                (views, likes, shares, saves, comments,
                 eng, time.time(), attempt, uid)
            )
            # Keep a quick lookup of engagement rate in uploads for time optimizer sync.
            c.execute(
                "UPDATE uploads SET engagement_rate=? WHERE id=?",
                (eng, uid)
            )
            # Update daily stats
            day = datetime.now(timezone.utc).date().isoformat()
            c.execute(
                """INSERT INTO daily_stats (date, platform, total_views, total_likes)
                   VALUES (?,?,?,?)
                   ON CONFLICT(date, platform) DO UPDATE
                   SET total_views=total_views+?, total_likes=total_likes+?""",
                (day, platform, views, likes, views, likes)
            )
            # Update hashtag performance
            c.execute(
                """UPDATE hashtag_performance
                   SET total_views=total_views+?, total_likes=total_likes+?,
                       avg_engagement=(avg_engagement*(uses-1)+?) / uses
                   WHERE platform=?""",
                (views, likes, eng, platform)
            )
            # Update channel performance
            urow = c.execute(
                "SELECT channel_id FROM uploads WHERE id=?", (uid,)
            ).fetchone()
            if urow and urow[0]:
                self._update_channel_perf(c, urow[0], eng)

    def _update_channel_perf(self, c, channel_id: str, engagement: float) -> None:
        c.execute(
            """INSERT INTO channel_stats (channel_id, videos_used, avg_engagement, performance, updated_at)
               VALUES (?,1,?,MIN(1.0,?/5.0),?)
               ON CONFLICT(channel_id) DO UPDATE
               SET videos_used=videos_used+1,
                   avg_engagement=(avg_engagement*(videos_used-1)+?) / videos_used,
                   performance=MIN(1.0, (performance*0.7 + ?*0.3)),
                   updated_at=?""",
            (channel_id, engagement, engagement / 5.0, time.time(),
             engagement, engagement / 5.0, time.time())
        )

    # ── Query helpers (used by pipeline/scorer) ─────────────────────────────

    def channel_performance(self, channel_id: str) -> float:
        """Return 0-1 performance score for a source channel (for VideoScorer)."""
        with self._conn() as c:
            row = c.execute(
                "SELECT performance FROM channel_stats WHERE channel_id=?",
                (channel_id,)
            ).fetchone()
        return float(row[0]) if row else 0.5

    def top_tags_by_platform(self, platform: str, limit: int = 20) -> List[str]:
        """Return best-performing hashtags on a platform (for HashtagEngine)."""
        with self._conn() as c:
            rows = c.execute(
                """SELECT tag FROM hashtag_performance
                   WHERE platform=? AND uses >= 2
                   ORDER BY avg_engagement DESC, total_views DESC
                   LIMIT ?""",
                (platform, limit)
            ).fetchall()
        return [r[0] for r in rows]

    def pending_metric_pulls(self, min_hours: float = 24, max_hours: float = 72) -> List[Dict]:
        """Return upload records ready for engagement pull."""
        now = time.time()
        low = now - max_hours * 3600
        high = now - min_hours * 3600
        with self._conn() as c:
            rows = c.execute(
                """SELECT u.post_id, u.platform
                   FROM uploads u
                   JOIN performance p ON p.upload_id=u.id
                   WHERE u.uploaded_at BETWEEN ? AND ?
                   AND (p.pulled_at=0 OR p.pull_attempt < 3)""",
                (low, high)
            ).fetchall()
        return [{"post_id": r[0], "platform": r[1]} for r in rows]

    def best_upload_times(self, platform: str, n: int = 3) -> List[str]:
        """Return top N upload times (HH:MM) by avg engagement for a platform."""
        with self._conn() as c:
            rows = c.execute(
                """SELECT strftime('%H', datetime(u.uploaded_at,'unixepoch')) as hr,
                          AVG(p.engagement) as avg_eng, COUNT(*) as cnt
                   FROM uploads u
                   JOIN performance p ON p.upload_id=u.id
                   WHERE u.platform=? AND p.engagement > 0
                   GROUP BY hr HAVING cnt >= 2
                   ORDER BY avg_eng DESC
                   LIMIT ?""",
                (platform, n)
            ).fetchall()
        return [f"{int(r[0]):02d}:00" for r in rows]

    def uploads_today_count(self) -> int:
        today = datetime.now(timezone.utc).date().isoformat()
        with self._conn() as c:
            row = c.execute(
                "SELECT SUM(uploads) FROM daily_stats WHERE date=?", (today,)
            ).fetchone()
        return int(row[0] or 0)

    def history_summary_text(self, days: int = 30) -> str:
        """Return a brief text summary of recent uploads for DecisionEngine context."""
        since = time.time() - days * 86400
        with self._conn() as c:
            total = c.execute(
                "SELECT COUNT(*) FROM uploads WHERE uploaded_at > ?", (since,)
            ).fetchone()[0]
            best_platform = c.execute(
                """SELECT u.platform, AVG(p.engagement) as eng
                   FROM uploads u JOIN performance p ON p.upload_id=u.id
                   WHERE u.uploaded_at > ? GROUP BY u.platform
                   ORDER BY eng DESC LIMIT 1""",
                (since,)
            ).fetchone()
            best_tag = c.execute(
                """SELECT tag, avg_engagement
                   FROM hashtag_performance
                   ORDER BY avg_engagement DESC LIMIT 1"""
            ).fetchone()

        parts = [f"Last {days}d: {total} clips uploaded."]
        if best_platform:
            parts.append(f"Best platform: {best_platform[0]} (avg {best_platform[1]:.1f}% ER).")
        if best_tag:
            parts.append(f"Top hashtag: #{best_tag[0]} ({best_tag[1]:.1f}% ER).")
        return " ".join(parts)

    def weekly_report_text(self) -> str:
        """Full weekly analytics report as plain text."""
        since = time.time() - 7 * 86400
        with self._conn() as c:
            total_uploads = c.execute(
                "SELECT COUNT(*) FROM uploads WHERE uploaded_at>?", (since,)
            ).fetchone()[0]
            per_platform = c.execute(
                """SELECT u.platform, COUNT(*) as cnt,
                          COALESCE(SUM(p.views),0) as views,
                          COALESCE(AVG(p.engagement),0) as eng
                   FROM uploads u LEFT JOIN performance p ON p.upload_id=u.id
                   WHERE u.uploaded_at>? GROUP BY u.platform ORDER BY views DESC""",
                (since,)
            ).fetchall()
            top_clips = c.execute(
                """SELECT u.title, u.platform, p.views, p.engagement
                   FROM uploads u JOIN performance p ON p.upload_id=u.id
                   WHERE u.uploaded_at>? AND p.views>0
                   ORDER BY p.views DESC LIMIT 5""",
                (since,)
            ).fetchall()

        lines = [
            "=" * 60,
            "  AUTO-REELS PRO v8  ·  WEEKLY ANALYTICS",
            "=" * 60,
            f"  Period : last 7 days",
            f"  Total clips uploaded : {total_uploads}",
            "",
            "  By Platform:",
        ]
        for row in per_platform:
            lines.append(f"    {row[0]:12} {row[1]:4} clips | {row[2]:>8,} views | {row[3]:.1f}% ER")

        if top_clips:
            lines += ["", "  Top Clips This Week:"]
            for i, row in enumerate(top_clips, 1):
                lines.append(f"    {i}. [{row[1]}] {row[0][:45]} — {row[2]:,} views ({row[3]:.1f}%)")

        lines += ["", "=" * 60]
        return "\n".join(lines)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
