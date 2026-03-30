"""
series_tracker.py — Persistent series/part number tracker.
Ensures Part 01, Part 02... are never duplicated or skipped
across runs, restarts, and multiple channels.
Tracks series per (channel_id, niche) combination.
"""
from __future__ import annotations
import logging, sqlite3, time
from pathlib import Path

log = logging.getLogger(__name__)

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS series (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id      TEXT NOT NULL,
    video_id        TEXT NOT NULL,
    niche           TEXT NOT NULL DEFAULT 'movie',
    series_name     TEXT NOT NULL DEFAULT '',
    part_start      INTEGER NOT NULL DEFAULT 1,
    part_end        INTEGER NOT NULL DEFAULT 1,
    total_clips     INTEGER NOT NULL DEFAULT 1,
    platform        TEXT NOT NULL DEFAULT 'facebook',
    created_at      REAL NOT NULL,
    UNIQUE(channel_id, video_id, platform)
);
CREATE TABLE IF NOT EXISTS global_counters (
    channel_id  TEXT NOT NULL,
    platform    TEXT NOT NULL,
    niche       TEXT NOT NULL,
    next_part   INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY(channel_id, platform, niche)
);
"""


class SeriesTracker:
    """Assigns globally unique, sequential part numbers per channel."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)
        log.info("[SeriesTracker] init db=%s", self.db_path)

    def claim_parts(
        self,
        channel_id: str,
        video_id: str,
        n_clips: int,
        platform: str = "facebook",
        niche: str = "movie",
        series_name: str = "",
    ) -> range:
        """
        Reserve n_clips sequential part numbers for this video.
        Returns a range like range(5, 15) meaning parts 5-14.
        Thread-safe via SQLite.
        """
        with self._conn() as c:
            # Get or init the global counter
            row = c.execute("""
                SELECT next_part FROM global_counters
                WHERE channel_id=? AND platform=? AND niche=?
            """, (channel_id, platform, niche)).fetchone()

            start = row[0] if row else 1
            end   = start + n_clips

            # Upsert counter
            c.execute("""
                INSERT INTO global_counters (channel_id, platform, niche, next_part)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(channel_id, platform, niche) DO UPDATE SET next_part=?
            """, (channel_id, platform, niche, end, end))

            # Record the series entry
            c.execute("""
                INSERT OR REPLACE INTO series
                (channel_id, video_id, niche, series_name, part_start, part_end,
                 total_clips, platform, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (channel_id, video_id, niche, series_name,
                  start, end - 1, n_clips, platform, time.time()))

        log.info("[SeriesTracker] %s/%s claimed parts %d-%d on %s",
                 channel_id[:20], video_id[:12], start, end - 1, platform)
        return range(start, end)

    def get_next_part(self, channel_id: str, platform: str = "facebook",
                      niche: str = "movie") -> int:
        """Peek at what the next part number will be (without claiming)."""
        with self._conn() as c:
            row = c.execute("""
                SELECT next_part FROM global_counters
                WHERE channel_id=? AND platform=? AND niche=?
            """, (channel_id, platform, niche)).fetchone()
        return row[0] if row else 1

    def series_report(self) -> str:
        with self._conn() as c:
            rows = c.execute("""
                SELECT channel_id, platform, niche, next_part
                FROM global_counters ORDER BY channel_id, platform
            """).fetchall()
        lines = ["=== SERIES TRACKER ===\n"]
        if not rows:
            lines.append("  No series data yet.")
        for ch, plat, niche, nxt in rows:
            lines.append(f"  {ch[:25]:<25} | {plat:<12} | {niche:<12} | next_part={nxt}")
        return "\n".join(lines)

    def _conn(self):
        return sqlite3.connect(self.db_path, timeout=15)
