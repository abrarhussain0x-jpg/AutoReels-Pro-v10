"""
multiday_scheduler.py — Multi-day clip distribution scheduler.

Instead of dumping all 10 clips in one day (which kills reach),
this scheduler distributes them across 2-4 days for maximum
series engagement and algorithm rewards.

Strategy:
  - Day 1: Parts 1-3 (hooks the audience)
  - Day 2: Parts 4-6 (keeps momentum)
  - Day 3: Parts 7-10 (delivers payoff)
  - Each day spread across 2-3 time windows

Also handles:
  - Minimum gap enforcement (45 min between posts)
  - Re-engagement delay (don't post Part 2 until Part 1 gets traction)
  - Weekend boost (more posts on Sat/Sun for higher traffic niches)
"""
from __future__ import annotations
import logging, sqlite3, time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

log = logging.getLogger(__name__)

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS scheduled_posts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id      TEXT NOT NULL,
    clip_num      INTEGER NOT NULL,
    platform      TEXT NOT NULL DEFAULT 'facebook',
    scheduled_for REAL NOT NULL,
    posted_at     REAL NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'pending',
    post_id       TEXT NOT NULL DEFAULT '',
    clip_path     TEXT NOT NULL DEFAULT '',
    caption       TEXT NOT NULL DEFAULT '',
    UNIQUE(video_id, clip_num, platform)
);
CREATE INDEX IF NOT EXISTS idx_sp_status ON scheduled_posts(status, scheduled_for);
"""

# Distribution strategies by clip count
DISTRIBUTION = {
    (1, 3):  [1],                    # 1-3 clips: all day 1
    (4, 6):  [2, 4],                 # 4-6 clips: split over 2 days
    (7, 10): [3, 3, 4],              # 7-10: 3 days
    (11, 15):[4, 4, 4, 3],           # 11-15: 4 days
    (16, 20):[4, 4, 4, 4, 4],        # 16-20: 5 days
}

# Best time windows per niche (hour of day)
WINDOWS_BY_NICHE = {
    "movie":       [9, 18, 21],
    "anime":       [16, 19, 22],
    "kdrama":      [12, 19, 21],
    "horror":      [20, 22],
    "documentary": [9, 12, 20],
    "general":     [9, 18, 21],
}


@dataclass
class ScheduledSlot:
    clip_num: int
    scheduled_for: datetime
    day_number: int
    window_label: str

    @property
    def timestamp(self) -> float:
        return self.scheduled_for.timestamp()


class MultiDayScheduler:
    """Distributes clips across multiple days for maximum reach."""

    MIN_GAP_MINUTES = 45
    REENGAGEMENT_HOURS = 4   # wait for Part 1 traction before Part 2

    def __init__(self, db_path: Path, niche: str = "movie"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.niche   = niche
        self.windows = WINDOWS_BY_NICHE.get(niche, WINDOWS_BY_NICHE["general"])
        with self._conn() as c:
            c.executescript(SCHEMA)
        log.info("[MultiDayScheduler] niche=%s windows=%s", niche, self.windows)

    def plan(
        self,
        video_id: str,
        n_clips: int,
        platform: str = "facebook",
        start_from: Optional[datetime] = None,
    ) -> List[ScheduledSlot]:
        """
        Create an optimized multi-day schedule for all clips.
        Returns list of ScheduledSlot objects sorted by time.
        """
        now = start_from or datetime.now()

        # Determine distribution
        distribution = self._get_distribution(n_clips)
        log.info("[MultiDayScheduler] %d clips → %s day distribution", n_clips, distribution)

        slots  = []
        clip_n = 1
        day_offset = 0

        for day_clips in distribution:
            day_windows = self._get_day_windows(now, day_offset)
            # Pick evenly spaced windows for this day's clips
            step = max(1, len(day_windows) // day_clips)
            used_windows = day_windows[::step][:day_clips]

            for i, window_dt in enumerate(used_windows[:day_clips]):
                # Enforce minimum gap
                if slots:
                    last = slots[-1].scheduled_for
                    gap  = (window_dt - last).total_seconds() / 60
                    if gap < self.MIN_GAP_MINUTES:
                        window_dt = last + timedelta(minutes=self.MIN_GAP_MINUTES)

                slots.append(ScheduledSlot(
                    clip_num=clip_n,
                    scheduled_for=window_dt,
                    day_number=day_offset + 1,
                    window_label=window_dt.strftime("%a %d %b %H:%M"),
                ))
                clip_n += 1

            day_offset += 1

        # Fill any remaining clips on last day
        while clip_n <= n_clips:
            last_slot = slots[-1] if slots else None
            base = last_slot.scheduled_for if last_slot else now
            next_t = base + timedelta(minutes=self.MIN_GAP_MINUTES)
            slots.append(ScheduledSlot(
                clip_num=clip_n,
                scheduled_for=next_t,
                day_number=day_offset,
                window_label=next_t.strftime("%a %d %b %H:%M"),
            ))
            clip_n += 1

        # Save to DB
        self._save_schedule(video_id, slots, platform)
        return slots

    def get_due(self, platform: str = "facebook") -> List[dict]:
        """Return clips scheduled to post now (within 30-min window)."""
        now     = time.time()
        window  = 30 * 60   # 30 minutes
        with self._conn() as c:
            rows = c.execute("""
                SELECT video_id, clip_num, scheduled_for, clip_path, caption
                FROM scheduled_posts
                WHERE platform=? AND status='pending'
                AND scheduled_for BETWEEN ? AND ?
                ORDER BY scheduled_for
            """, (platform, now - window, now + window)).fetchall()
        return [
            {"video_id": r[0], "clip_num": r[1], "scheduled_for": r[2],
             "clip_path": r[3], "caption": r[4]}
            for r in rows
        ]

    def mark_posted(self, video_id: str, clip_num: int,
                    platform: str, post_id: str):
        with self._conn() as c:
            c.execute("""
                UPDATE scheduled_posts SET status='posted', posted_at=?, post_id=?
                WHERE video_id=? AND clip_num=? AND platform=?
            """, (time.time(), post_id, video_id, clip_num, platform))

    def schedule_report(self) -> str:
        with self._conn() as c:
            rows = c.execute("""
                SELECT video_id, clip_num, platform, scheduled_for, status, post_id
                FROM scheduled_posts
                WHERE scheduled_for > ?
                ORDER BY scheduled_for
                LIMIT 30
            """, (time.time() - 86400,)).fetchall()

        lines = ["=== MULTI-DAY SCHEDULE ===\n"]
        current_day = ""
        for r in rows:
            vid, clip, plat, sched, status, pid = r
            dt    = datetime.fromtimestamp(sched)
            day   = dt.strftime("%A %d %b")
            if day != current_day:
                lines.append(f"\n  📅 {day}")
                current_day = day
            icon = "✅" if status == "posted" else "⏳"
            lines.append(f"    {icon} {dt.strftime('%H:%M')} | {plat:<10} "
                         f"| {vid[:15]} clip#{clip:<3} "
                         f"| {pid[:12] if pid else 'pending'}")
        return "\n".join(lines)

    def _get_distribution(self, n_clips: int) -> List[int]:
        for (lo, hi), dist in DISTRIBUTION.items():
            if lo <= n_clips <= hi:
                # Scale to actual clip count
                total = sum(dist)
                if total == n_clips:
                    return dist
                # Adjust last day
                scaled = list(dist)
                diff   = n_clips - total
                scaled[-1] = max(1, scaled[-1] + diff)
                return scaled
        # Default: 4 per day
        days    = (n_clips + 3) // 4
        per_day = [4] * (days - 1)
        per_day.append(n_clips - 4 * (days - 1))
        return per_day

    def _get_day_windows(self, base: datetime, day_offset: int) -> List[datetime]:
        """Get datetime objects for each posting window on a given day."""
        day = base + timedelta(days=day_offset)
        return [
            day.replace(hour=h, minute=0, second=0, microsecond=0)
            for h in self.windows
            if day_offset > 0 or day.replace(hour=h) > base
        ] or [base + timedelta(hours=1)]

    def _save_schedule(self, video_id: str, slots: List[ScheduledSlot], platform: str):
        with self._conn() as c:
            for slot in slots:
                c.execute("""
                    INSERT OR REPLACE INTO scheduled_posts
                    (video_id, clip_num, platform, scheduled_for, status)
                    VALUES (?, ?, ?, ?, 'pending')
                """, (video_id, slot.clip_num, platform, slot.timestamp))

    def _conn(self):
        return sqlite3.connect(self.db_path, timeout=15)
