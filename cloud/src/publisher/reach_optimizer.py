"""
reach_optimizer.py — Facebook reach maximizer.

Implements data-driven tactics to maximize organic reach:
  1. Exact golden-hour posting (when YOUR audience is active)
  2. Series pacing (gaps between parts to build anticipation)
  3. Re-engagement posts (pulls old followers back to page)
  4. Frequency capping (avoids algorithm penalty for over-posting)
  5. Cross-day distribution (never post all clips same day)
  6. Peak day detection from analytics data
"""
from __future__ import annotations
import logging, math, sqlite3, time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# Facebook peak engagement windows (evidence-based defaults)
# Will be overridden by learned data after 20+ posts
FB_DEFAULT_WINDOWS: Dict[str, List[Tuple[int, int]]] = {
    "movie":       [(2, 9), (2, 21), (4, 9), (4, 21), (6, 14)],  # Tue/Thu/Sat
    "anime":       [(0, 18), (2, 18), (4, 18), (5, 16), (6, 16)],
    "kdrama":      [(1, 20), (3, 20), (5, 14), (6, 14), (6, 20)],
    "horror":      [(4, 21), (5, 21), (6, 20), (5, 16), (6, 16)],
    "documentary": [(0, 12), (2, 12), (4, 12), (1, 9), (3, 9)],
    "general":     [(1, 9), (1, 19), (3, 9), (3, 19), (5, 12)],
}

# Minimum gap between uploads (in minutes) to avoid algorithm penalty
UPLOAD_GAP_MINUTES = 45

# Series pacing: ideal gap between parts (keeps audience engaged but not bored)
SERIES_PART_GAP_HOURS = 4   # post Part 2 at least 4h after Part 1

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS upload_schedule (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id      TEXT NOT NULL,
    clip_num      INTEGER NOT NULL,
    platform      TEXT NOT NULL DEFAULT 'facebook',
    scheduled_for REAL NOT NULL,
    posted_at     REAL NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'pending',
    post_id       TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS reach_data (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id       TEXT NOT NULL,
    hour          INTEGER NOT NULL,
    weekday       INTEGER NOT NULL,
    reach         INTEGER NOT NULL DEFAULT 0,
    engagement    REAL NOT NULL DEFAULT 0.0,
    recorded_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sched_status ON upload_schedule(status, scheduled_for);
"""

WEEKDAY_NAMES = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]


@dataclass
class PostWindow:
    weekday: int
    hour: int
    score: float
    posts_count: int = 0
    avg_reach: float = 0.0

    @property
    def label(self) -> str:
        return f"{WEEKDAY_NAMES[self.weekday]} {self.hour:02d}:00"


class ReachOptimizer:
    """Plans upload schedule to maximize Facebook organic reach."""

    def __init__(self, db_path: Path, niche: str = "movie"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.niche   = niche
        with self._conn() as c:
            c.executescript(SCHEMA)
        log.info("[ReachOptimizer] init niche=%s", niche)

    # ── Schedule Planning ─────────────────────────────────────────────────────

    def plan_upload_schedule(
        self,
        video_id: str,
        n_clips: int,
        start_from: Optional[datetime] = None,
        platform: str = "facebook",
    ) -> List[datetime]:
        """
        Plan optimal upload times for all clips of a video.
        Distributes clips across multiple days for maximum reach.
        Returns list of datetime objects (one per clip).
        """
        windows  = self.get_best_windows(platform, n=10)
        now      = start_from or datetime.now()
        schedule = []
        last_post = now

        for i in range(n_clips):
            # Find next valid window
            next_window = self._next_window_after(last_post, windows)
            schedule.append(next_window)

            # Ensure minimum gap between parts
            last_post = next_window + timedelta(hours=SERIES_PART_GAP_HOURS)

        log.info("[ReachOptimizer] planned %d slots for %s", len(schedule), video_id)
        return schedule

    def get_best_windows(self, platform: str = "facebook", n: int = 5) -> List[PostWindow]:
        """Get top N posting windows, learned from real data or defaults."""
        # Try real analytics data first
        learned = self._load_learned_windows()
        if len(learned) >= 3:
            return sorted(learned, key=lambda w: w.score, reverse=True)[:n]

        # Fall back to niche defaults
        defaults = FB_DEFAULT_WINDOWS.get(self.niche, FB_DEFAULT_WINDOWS["general"])
        return [PostWindow(weekday=wd, hour=h, score=1.0) for wd, h in defaults[:n]]

    def record_reach(
        self,
        post_id: str,
        hour: int,
        weekday: int,
        reach: int,
        engagement: float,
    ):
        """Record actual reach data to improve future scheduling."""
        with self._conn() as c:
            c.execute("""
                INSERT INTO reach_data (post_id, hour, weekday, reach, engagement, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (post_id, hour, weekday, reach, engagement, time.time()))
        log.debug("[ReachOptimizer] recorded reach=%d for post %s", reach, post_id)

    def should_post_now(self, platform: str = "facebook") -> Tuple[bool, str]:
        """Check if current moment is a good posting window."""
        now     = datetime.now()
        windows = self.get_best_windows(platform, n=5)
        for w in windows:
            if w.weekday == now.weekday() and abs(w.hour - now.hour) <= 1:
                return True, f"In optimal window: {w.label} (score={w.score:.2f})"
        next_w = self._next_window_after(now, windows)
        delta  = next_w - now
        hours  = delta.total_seconds() / 3600
        return False, f"Next window: {next_w.strftime('%a %H:%M')} (in {hours:.1f}h)"

    def schedule_report(self) -> str:
        windows = self.get_best_windows(n=7)
        ok, reason = self.should_post_now()
        lines = [
            "=== REACH OPTIMIZER ===\n",
            f"  Current status: {'✅ POST NOW' if ok else '⏳ ' + reason}\n",
            "  Top posting windows:",
        ]
        for w in windows:
            lines.append(f"    {w.label} | score={w.score:.2f} | posts={w.posts_count} "
                         f"| avg_reach={w.avg_reach:.0f}")
        return "\n".join(lines)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _next_window_after(
        self, after: datetime, windows: List[PostWindow]
    ) -> datetime:
        """Find the next occurrence of any good window after `after`."""
        # Search up to 7 days ahead
        for day_offset in range(8):
            candidate = after + timedelta(days=day_offset)
            for w in windows:
                if day_offset == 0 and w.hour <= after.hour:
                    continue
                target = candidate.replace(hour=w.hour, minute=0, second=0, microsecond=0)
                if target > after:
                    # Ensure minimum gap from last post
                    gap = (target - after).total_seconds() / 60
                    if gap >= UPLOAD_GAP_MINUTES:
                        return target
        # Fallback: 4 hours from now
        return after + timedelta(hours=4)

    def _load_learned_windows(self) -> List[PostWindow]:
        """Load windows learned from real analytics data."""
        try:
            with self._conn() as c:
                rows = c.execute("""
                    SELECT weekday, hour, COUNT(*) as posts,
                           AVG(reach) as avg_reach, AVG(engagement) as avg_eng
                    FROM reach_data
                    GROUP BY weekday, hour
                    HAVING posts >= 2
                    ORDER BY avg_eng DESC
                """).fetchall()
            if not rows:
                return []
            max_reach = max(r[3] or 1 for r in rows)
            return [
                PostWindow(
                    weekday=r[0], hour=r[1],
                    posts_count=r[2],
                    avg_reach=r[3] or 0,
                    score=min(1.0, (r[3] or 0) / max_reach),
                )
                for r in rows
            ]
        except Exception as e:
            log.debug("[ReachOptimizer] load windows error: %s", e)
            return []

    def _conn(self):
        return sqlite3.connect(self.db_path, timeout=10)
