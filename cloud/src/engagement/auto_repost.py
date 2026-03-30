"""
auto_repost.py — Auto-repost top-performing clips weekly.
Reads analytics DB, finds top 15% by engagement, re-queues with fresh angle.
Prevents duplicate repost within 7 days.
"""
from __future__ import annotations
import logging, sqlite3, time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

log = logging.getLogger(__name__)

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS repost_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id    TEXT NOT NULL,
    clip_num    INTEGER NOT NULL DEFAULT 1,
    platform    TEXT NOT NULL,
    original_post_id TEXT NOT NULL,
    repost_at   REAL NOT NULL,
    engagement  REAL NOT NULL DEFAULT 0.0,
    UNIQUE(video_id, clip_num, platform)
);
"""

@dataclass
class RepostCandidate:
    video_id: str
    clip_num: int
    platform: str
    post_id: str
    clip_path: str
    title: str
    engagement: float
    original_angle: str

class AutoRepostEngine:
    """Finds top clips and schedules them for re-upload with fresh angles."""

    TOP_PCT         = 0.15   # top 15%
    MIN_ENGAGEMENT  = 2.0    # minimum engagement % to qualify
    REPOST_COOLDOWN = 7 * 24 * 3600   # 7 days

    def __init__(self, analytics_db: Path, repost_db: Path):
        self.analytics_db = Path(analytics_db)
        self.repost_db    = Path(repost_db)
        self.repost_db.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    def find_candidates(self, platform: str = "facebook",
                        max_candidates: int = 5) -> List[RepostCandidate]:
        """Find top-performing clips eligible for repost."""
        if not self.analytics_db.exists():
            return []

        analytics_conn = sqlite3.connect(self.analytics_db, timeout=10)
        try:
            rows = analytics_conn.execute("""
                SELECT u.video_id, u.clip_num, u.platform, u.post_id,
                       u.title, p.engagement
                FROM uploads u
                JOIN performance p ON p.upload_id = u.id
                WHERE u.platform = ? AND p.engagement >= ?
                ORDER BY p.engagement DESC
            """, (platform, self.MIN_ENGAGEMENT)).fetchall()
        except Exception as e:
            log.warning("[Repost] analytics query failed: %s", e)
            return []
        finally:
            analytics_conn.close()

        if not rows:
            return []

        # Top 15%
        top_n = max(1, int(len(rows) * self.TOP_PCT))
        top_rows = rows[:top_n]

        candidates = []
        for row in top_rows[:max_candidates]:
            video_id, clip_num, plat, post_id, title, engagement = row
            if self._recently_reposted(video_id, clip_num, plat):
                continue
            candidates.append(RepostCandidate(
                video_id=video_id, clip_num=clip_num, platform=plat,
                post_id=post_id, clip_path="", title=title or "",
                engagement=engagement, original_angle="mystery",
            ))

        log.info("[Repost] found %d repost candidates", len(candidates))
        return candidates

    def record_repost(self, video_id: str, clip_num: int,
                      platform: str, post_id: str, engagement: float):
        with self._conn() as c:
            c.execute("""
                INSERT OR REPLACE INTO repost_history
                (video_id, clip_num, platform, original_post_id, repost_at, engagement)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (video_id, clip_num, platform, post_id, time.time(), engagement))
        log.info("[Repost] recorded repost %s clip%d on %s", video_id, clip_num, platform)

    def fresh_angle(self, original_angle: str) -> str:
        """Pick a different angle for the repost."""
        angles = ["mystery","shocking","emotional","educational","controversial","motivational"]
        others = [a for a in angles if a != original_angle]
        return others[int(time.time()) % len(others)]

    def _recently_reposted(self, video_id, clip_num, platform) -> bool:
        cutoff = time.time() - self.REPOST_COOLDOWN
        with self._conn() as c:
            row = c.execute("""
                SELECT 1 FROM repost_history
                WHERE video_id=? AND clip_num=? AND platform=? AND repost_at > ?
            """, (video_id, clip_num, platform, cutoff)).fetchone()
        return row is not None

    def _conn(self):
        return sqlite3.connect(self.repost_db, timeout=15)
