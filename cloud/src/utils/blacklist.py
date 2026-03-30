"""
blacklist.py — Permanent blacklist for channels, videos, and keywords.
Prevents any blacklisted content from ever being processed again.
Useful for removing channels that get copyright strikes or low performance.
"""
from __future__ import annotations
import json, logging, sqlite3, time
from pathlib import Path
from typing import List

log = logging.getLogger(__name__)

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS blacklist (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    type        TEXT NOT NULL,      -- channel | video | keyword
    value       TEXT NOT NULL,
    reason      TEXT NOT NULL DEFAULT '',
    added_at    REAL NOT NULL,
    UNIQUE(type, value)
);
"""


class Blacklist:
    """Blocks channels, videos, or keywords from being processed."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)
        self._cache = self._load_cache()

    def block_channel(self, channel_id: str, reason: str = ""):
        self._add("channel", channel_id.lower(), reason)
        log.warning("[Blacklist] blocked channel: %s (%s)", channel_id, reason)

    def block_video(self, video_id: str, reason: str = ""):
        self._add("video", video_id, reason)

    def block_keyword(self, keyword: str, reason: str = ""):
        self._add("keyword", keyword.lower(), reason)

    def is_blocked(self, video) -> tuple[bool, str]:
        """Check if a VideoMeta is blacklisted. Returns (blocked, reason)."""
        vid_id  = (getattr(video, "video_id",  "") or "").lower()
        channel = (getattr(video, "channel",   "") or "").lower()
        title   = (getattr(video, "title",     "") or "").lower()

        if vid_id in self._cache["video"]:
            return True, f"video {vid_id} blacklisted"
        if channel and channel in self._cache["channel"]:
            return True, f"channel {channel} blacklisted"
        for kw in self._cache["keyword"]:
            if kw in title:
                return True, f"keyword '{kw}' in title"
        return False, ""

    def list_all(self) -> List[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT type, value, reason, added_at FROM blacklist ORDER BY type, added_at DESC"
            ).fetchall()
        return [{"type": r[0], "value": r[1], "reason": r[2], "added_at": r[3]} for r in rows]

    def remove(self, type_: str, value: str) -> bool:
        with self._conn() as c:
            c.execute("DELETE FROM blacklist WHERE type=? AND value=?", (type_, value))
        self._cache = self._load_cache()
        return True

    def report(self) -> str:
        items = self.list_all()
        lines = [f"=== BLACKLIST ({len(items)} entries) ===\n"]
        for item in items:
            lines.append(f"  [{item['type']:<8}] {item['value'][:50]:<50} — {item['reason']}")
        return "\n".join(lines) if lines else "Blacklist is empty."

    def _add(self, type_: str, value: str, reason: str):
        with self._conn() as c:
            c.execute("""
                INSERT OR IGNORE INTO blacklist (type, value, reason, added_at)
                VALUES (?, ?, ?, ?)
            """, (type_, value, reason, time.time()))
        self._cache = self._load_cache()

    def _load_cache(self) -> dict:
        cache = {"channel": set(), "video": set(), "keyword": set()}
        with self._conn() as c:
            rows = c.execute("SELECT type, value FROM blacklist").fetchall()
        for type_, value in rows:
            if type_ in cache:
                cache[type_].add(value.lower())
        return cache

    def _conn(self):
        return sqlite3.connect(self.db_path, timeout=10)
