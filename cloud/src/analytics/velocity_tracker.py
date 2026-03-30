"""
velocity_tracker.py v10.0 — Real Engagement Velocity Tracker.

Pulls metrics at 1h, 6h, 24h, 72h after upload and stores time-series
engagement curves. Computes velocity (views/hour) and triggers auto-repost
when viral threshold is crossed.

New in v10:
  - Multi-point metric pulls (1h/6h/24h/72h) instead of single pull
  - Engagement time-series stored per upload
  - Velocity = (views_6h - views_1h) / 5 hours
  - Viral threshold: >500 views/hour at 6h → trigger auto-repost
  - Feeds velocity features (slope_1h, slope_6h) into GrowthPredictor
  - Dashboard: exposes sparkline data for live charts
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS velocity_uploads (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    upload_id       TEXT    NOT NULL UNIQUE,
    video_id        TEXT    NOT NULL,
    platform        TEXT    NOT NULL,
    post_id         TEXT    NOT NULL,
    clip_num        INTEGER NOT NULL DEFAULT 1,
    uploaded_at     REAL    NOT NULL,
    niche           TEXT    NOT NULL DEFAULT 'movie',
    viral_triggered INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS engagement_timeseries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    upload_id       TEXT    NOT NULL,
    pulled_at       REAL    NOT NULL,
    hours_since     REAL    NOT NULL,
    views           INTEGER NOT NULL DEFAULT 0,
    likes           INTEGER NOT NULL DEFAULT 0,
    shares          INTEGER NOT NULL DEFAULT 0,
    comments        INTEGER NOT NULL DEFAULT 0,
    velocity_vph    REAL    NOT NULL DEFAULT 0.0,
    FOREIGN KEY(upload_id) REFERENCES velocity_uploads(upload_id)
);

CREATE INDEX IF NOT EXISTS idx_ts_upload ON engagement_timeseries(upload_id);
CREATE INDEX IF NOT EXISTS idx_ts_time   ON engagement_timeseries(pulled_at);
CREATE INDEX IF NOT EXISTS idx_vu_time   ON velocity_uploads(uploaded_at);
"""

PULL_SCHEDULE_HOURS = [1, 6, 24, 72]
VIRAL_THRESHOLD_VPH = 500  # views per hour at 6h mark


@dataclass
class VelocityPoint:
    hours_since: float
    views: int
    likes: int
    shares: int
    comments: int
    velocity_vph: float


@dataclass
class UploadVelocity:
    upload_id: str
    video_id: str
    platform: str
    post_id: str
    clip_num: int
    uploaded_at: float
    niche: str
    points: List[VelocityPoint] = field(default_factory=list)
    is_viral: bool = False

    @property
    def latest_views(self) -> int:
        return self.points[-1].views if self.points else 0

    @property
    def peak_velocity(self) -> float:
        return max((p.velocity_vph for p in self.points), default=0.0)

    @property
    def velocity_slope(self) -> float:
        """Trend: positive = accelerating, negative = decelerating."""
        if len(self.points) < 2:
            return 0.0
        return self.points[-1].velocity_vph - self.points[-2].velocity_vph


class VelocityTracker:
    """
    Tracks multi-point engagement curves for every uploaded clip.
    Detects viral momentum and exposes data to dashboard and GrowthPredictor.
    """

    def __init__(
        self,
        db_path: Path,
        pull_schedule_hours: Optional[List[int]] = None,
        viral_threshold_vph: int = VIRAL_THRESHOLD_VPH,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.pull_schedule = pull_schedule_hours or PULL_SCHEDULE_HOURS
        self.viral_threshold_vph = viral_threshold_vph

        with self._conn() as c:
            c.executescript(SCHEMA)
        log.info("[VelocityTracker] init db=%s pull_at=%s viral_vph=%d",
                 self.db_path, self.pull_schedule, viral_threshold_vph)

    # ── Public API ──────────────────────────────────────────────────────────

    def register_upload(
        self,
        upload_id: str,
        video_id: str,
        platform: str,
        post_id: str,
        clip_num: int = 1,
        niche: str = "movie",
    ) -> None:
        """Register a new upload for velocity tracking."""
        with self._conn() as c:
            c.execute("""
                INSERT OR IGNORE INTO velocity_uploads
                (upload_id, video_id, platform, post_id, clip_num, uploaded_at, niche)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (upload_id, video_id, platform, post_id, clip_num, time.time(), niche))
        log.info("[VelocityTracker] registered %s on %s", upload_id, platform)

    def record_metrics(
        self,
        upload_id: str,
        views: int,
        likes: int,
        shares: int = 0,
        comments: int = 0,
    ) -> Tuple[float, bool]:
        """
        Record a metric pull. Returns (velocity_vph, is_viral).
        Call this after each scheduled pull.
        """
        upload = self._get_upload(upload_id)
        if not upload:
            log.warning("[VelocityTracker] upload_id not found: %s", upload_id)
            return 0.0, False

        now = time.time()
        hours_since = (now - upload["uploaded_at"]) / 3600

        # Compute velocity vs previous point
        prev = self._get_last_point(upload_id)
        if prev and hours_since > prev["hours_since"]:
            delta_views = views - prev["views"]
            delta_hours = hours_since - prev["hours_since"]
            velocity = max(0.0, delta_views / delta_hours) if delta_hours > 0 else 0.0
        else:
            velocity = views / max(1, hours_since)

        with self._conn() as c:
            c.execute("""
                INSERT INTO engagement_timeseries
                (upload_id, pulled_at, hours_since, views, likes, shares, comments, velocity_vph)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (upload_id, now, hours_since, views, likes, shares, comments, velocity))

        # Check viral threshold at ~6h mark
        is_viral = False
        if 4 <= hours_since <= 8 and velocity >= self.viral_threshold_vph:
            if not upload.get("viral_triggered"):
                is_viral = True
                with self._conn() as c:
                    c.execute(
                        "UPDATE velocity_uploads SET viral_triggered=1 WHERE upload_id=?",
                        (upload_id,)
                    )
                log.warning("[VelocityTracker] 🚀 VIRAL DETECTED %s vph=%.0f", upload_id, velocity)

        log.info("[VelocityTracker] %s at %.1fh: views=%d velocity=%.0f vph %s",
                 upload_id, hours_since, views, velocity, "🚀VIRAL" if is_viral else "")
        return velocity, is_viral

    def pending_pulls(self) -> List[dict]:
        """
        Return list of uploads that need a metric pull now.
        Used by the scheduler to know what to pull.
        """
        now = time.time()
        pending = []

        with self._conn() as c:
            uploads = c.execute("""
                SELECT upload_id, video_id, platform, post_id, clip_num, uploaded_at, niche
                FROM velocity_uploads WHERE viral_triggered=0 OR uploaded_at > ?
            """, (now - 72 * 3600,)).fetchall()

        for row in uploads:
            upload_id, video_id, platform, post_id, clip_num, uploaded_at, niche = row
            hours_elapsed = (now - uploaded_at) / 3600
            already_pulled = self._pulled_hours(upload_id)

            for target_h in self.pull_schedule:
                if target_h > hours_elapsed + 0.1:
                    break
                if target_h not in already_pulled:
                    pending.append({
                        "upload_id": upload_id,
                        "video_id": video_id,
                        "platform": platform,
                        "post_id": post_id,
                        "clip_num": clip_num,
                        "target_hours": target_h,
                        "hours_elapsed": hours_elapsed,
                    })
                    break  # one pull per upload per run

        return pending

    def get_velocity_data(self, upload_id: str) -> List[VelocityPoint]:
        """Return time-series data for a specific upload (dashboard)."""
        with self._conn() as c:
            rows = c.execute("""
                SELECT hours_since, views, likes, shares, comments, velocity_vph
                FROM engagement_timeseries WHERE upload_id=?
                ORDER BY hours_since
            """, (upload_id,)).fetchall()
        return [VelocityPoint(hours_since=r[0], views=r[1], likes=r[2],
                              shares=r[3], comments=r[4], velocity_vph=r[5])
                for r in rows]

    def recent_velocities(self, limit: int = 10) -> List[dict]:
        """Return recent uploads with their velocity summaries for dashboard."""
        with self._conn() as c:
            rows = c.execute("""
                SELECT vu.upload_id, vu.platform, vu.niche, vu.uploaded_at,
                       vu.viral_triggered,
                       MAX(ts.views) as max_views,
                       MAX(ts.velocity_vph) as peak_vph
                FROM velocity_uploads vu
                LEFT JOIN engagement_timeseries ts ON ts.upload_id = vu.upload_id
                GROUP BY vu.upload_id
                ORDER BY vu.uploaded_at DESC
                LIMIT ?
            """, (limit,)).fetchall()

        result = []
        for r in rows:
            result.append({
                "upload_id": r[0],
                "platform": r[1],
                "niche": r[2],
                "uploaded_at": r[3],
                "is_viral": bool(r[4]),
                "max_views": r[5] or 0,
                "peak_vph": r[6] or 0.0,
                "points": self.get_velocity_data(r[0]),
            })
        return result

    def velocity_report(self) -> str:
        """Report for --velocity-report CLI."""
        data = self.recent_velocities(20)
        lines = ["=== ENGAGEMENT VELOCITY REPORT (last 20 uploads) ===\n"]
        for d in data:
            age_h = (time.time() - d["uploaded_at"]) / 3600
            viral = "🚀" if d["is_viral"] else "  "
            lines.append(
                f"  {viral} {d['platform']:<12} | age={age_h:.0f}h "
                f"| views={d['max_views']:>6} "
                f"| peak={d['peak_vph']:>5.0f} vph "
                f"| {d['upload_id'][-12:]}"
            )
        return "\n".join(lines)

    # ── Internal ────────────────────────────────────────────────────────────

    def _get_upload(self, upload_id: str) -> Optional[dict]:
        with self._conn() as c:
            row = c.execute("""
                SELECT upload_id, video_id, platform, post_id, clip_num, uploaded_at, niche, viral_triggered
                FROM velocity_uploads WHERE upload_id=?
            """, (upload_id,)).fetchone()
        if not row:
            return None
        keys = ["upload_id", "video_id", "platform", "post_id", "clip_num",
                "uploaded_at", "niche", "viral_triggered"]
        return dict(zip(keys, row))

    def _get_last_point(self, upload_id: str) -> Optional[dict]:
        with self._conn() as c:
            row = c.execute("""
                SELECT hours_since, views, velocity_vph FROM engagement_timeseries
                WHERE upload_id=? ORDER BY hours_since DESC LIMIT 1
            """, (upload_id,)).fetchone()
        if row:
            return {"hours_since": row[0], "views": row[1], "velocity_vph": row[2]}
        return None

    def _pulled_hours(self, upload_id: str) -> List[float]:
        """Return target-hours that have already been pulled for this upload."""
        with self._conn() as c:
            rows = c.execute("""
                SELECT hours_since FROM engagement_timeseries WHERE upload_id=?
            """, (upload_id,)).fetchall()
        pulled = [r[0] for r in rows]
        # Match to nearest schedule target
        matched = []
        for p in pulled:
            for target in PULL_SCHEDULE_HOURS:
                if abs(p - target) < 1.0:
                    matched.append(target)
        return matched

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=15)
