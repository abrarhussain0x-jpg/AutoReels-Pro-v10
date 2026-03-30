"""trend_detector.py v8.0"""
import logging
import sqlite3
import time
from pathlib import Path
from typing import List

log = logging.getLogger(__name__)

try:
    import feedparser
    _HAS_FEEDPARSER = True
except ImportError:
    _HAS_FEEDPARSER = False


class TrendDetector:
    FEEDS = {
        "movie":       ["https://www.youtube.com/feeds/videos.xml?channel_id=UCi9TgtQ-U7MWMtEYDvDKmgA"],
        "general":     ["https://trends.google.com/trends/trendingsearches/daily/rss?geo=US"],
    }

    def __init__(self, db_path: Path, niche: str = "movie"):
        self.db_path = Path(db_path)
        self.niche   = niche

    def get_current_trends(self, limit: int = 20) -> List[str]:
        """Return trending topics (from DB cache or RSS)."""
        cached = self._load_cached()
        if cached:
            return cached[:limit]
        return self.detect_and_store()[:limit]

    def detect_and_store(self) -> List[str]:
        topics: List[str] = []
        if _HAS_FEEDPARSER:
            feeds = self.FEEDS.get(self.niche, []) + self.FEEDS.get("general", [])
            for url in feeds[:3]:
                try:
                    import requests
                    resp = requests.get(url, timeout=8)
                    resp.raise_for_status()
                    feed = feedparser.parse(resp.content)
                    for entry in getattr(feed, "entries", [])[:10]:
                        title = entry.get("title", "").strip()
                        if title:
                            for word in title.split():
                                w = word.strip(".,!?#@").lower()
                                if len(w) > 3 and w not in topics:
                                    topics.append(w)
                except Exception as exc:
                    log.debug("[Trends] Feed failed: %s", exc)
        if topics:
            self._save(topics)
        return topics[:30]

    def _load_cached(self) -> List[str]:
        try:
            conn = sqlite3.connect(str(self.db_path), timeout=5)
            rows = conn.execute(
                "SELECT keyword FROM trends WHERE niche=? AND fetched_at > ? ORDER BY score DESC LIMIT 30",
                (self.niche, time.time() - 3600)
            ).fetchall()
            conn.close()
            return [r[0] for r in rows]
        except Exception:
            return []

    def _save(self, topics: List[str]) -> None:
        try:
            conn = sqlite3.connect(str(self.db_path), timeout=5)
            conn.execute("""CREATE TABLE IF NOT EXISTS trends (
                keyword TEXT, niche TEXT, score REAL DEFAULT 1.0,
                fetched_at REAL, PRIMARY KEY(keyword, niche))""")
            now = time.time()
            for i, t in enumerate(topics):
                score = 1.0 - (i / max(1, len(topics)))
                conn.execute(
                    "INSERT OR REPLACE INTO trends VALUES (?,?,?,?)",
                    (t, self.niche, score, now)
                )
            conn.commit()
            conn.close()
        except Exception as exc:
            log.debug("[Trends] Save failed: %s", exc)
