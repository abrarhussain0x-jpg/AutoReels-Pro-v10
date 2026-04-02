"""
ab_engine.py v8.0 — A/B caption and hook testing engine.

Tests different narrative angles across clips from the same video
and learns which style drives the most engagement per niche.

How it works:
  • Every generated clip is tagged with a narrative_angle (mystery, shocking, etc.)
  • 24–72h after upload, MetricsPuller pulls real engagement metrics
  • ABEngine reads those metrics, computes winner-per-angle per platform
  • ContentGenerator pulls the winning angle on next video via get_best_angle()
  • Losing angles get a decay penalty; winning angles get a boost weight

Supported angles: mystery | shocking | emotional | educational | controversial | motivational
"""

import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS ab_tests (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id       TEXT    NOT NULL,
    clip_num       INTEGER NOT NULL DEFAULT 1,
    platform       TEXT    NOT NULL,
    post_id        TEXT    NOT NULL,
    angle          TEXT    NOT NULL,
    niche          TEXT    NOT NULL DEFAULT 'general',
    hook           TEXT    NOT NULL DEFAULT '',
    caption_hash   TEXT    NOT NULL DEFAULT '',
    uploaded_at    REAL    NOT NULL,
    views          INTEGER NOT NULL DEFAULT 0,
    likes          INTEGER NOT NULL DEFAULT 0,
    shares         INTEGER NOT NULL DEFAULT 0,
    saves          INTEGER NOT NULL DEFAULT 0,
    comments       INTEGER NOT NULL DEFAULT 0,
    engagement     REAL    NOT NULL DEFAULT 0.0,
    metrics_pulled INTEGER NOT NULL DEFAULT 0,
    pulled_at      REAL    NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS angle_weights (
    platform    TEXT NOT NULL,
    niche       TEXT NOT NULL,
    angle       TEXT NOT NULL,
    weight      REAL NOT NULL DEFAULT 1.0,
    wins        INTEGER NOT NULL DEFAULT 0,
    trials      INTEGER NOT NULL DEFAULT 0,
    updated_at  REAL NOT NULL,
    PRIMARY KEY (platform, niche, angle)
);

CREATE INDEX IF NOT EXISTS idx_ab_platform ON ab_tests(platform);
CREATE INDEX IF NOT EXISTS idx_ab_angle    ON ab_tests(angle, niche);
CREATE INDEX IF NOT EXISTS idx_ab_pulled   ON ab_tests(metrics_pulled);
"""

ANGLES = ["mystery", "shocking", "emotional", "educational", "controversial", "motivational"]


@dataclass
class AngleResult:
    angle:          str
    weight:         float
    avg_engagement: float
    wins:           int
    trials:         int

    def __str__(self) -> str:
        return (f"{self.angle:15s} weight={self.weight:.3f} "
                f"eng={self.avg_engagement:.2f}% wins={self.wins}/{self.trials}")


class ABEngine:
    """
    Tracks A/B test results and returns the best-performing angle
    for a given platform/niche combination.
    """

    # UCB1 exploration constant — higher = more exploration
    EXPLORATION_FACTOR = 1.5
    MIN_TRIALS_FOR_CONFIDENCE = 5

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            log.error("Failed to create AB testing database directory: %s", e)
            raise
        with self._conn() as c:
            c.executescript(SCHEMA)
        self._init_weights()

    # ── Public API ──────────────────────────────────────────────────────────

    def record_upload(
        self,
        video_id:    str,
        clip_num:    int,
        platform:    str,
        post_id:     str,
        angle:       str,
        niche:       str    = "general",
        hook:        str    = "",
        caption:     str    = "",
    ) -> None:
        """Record that a clip was uploaded with a specific angle."""
        import hashlib
        caption_hash = hashlib.md5(caption.encode()).hexdigest()[:12]
        with self._conn() as c:
            c.execute(
                """INSERT OR IGNORE INTO ab_tests
                   (video_id, clip_num, platform, post_id, angle, niche,
                    hook, caption_hash, uploaded_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (video_id, clip_num, platform, post_id, angle, niche,
                 hook, caption_hash, time.time())
            )

    def record_metrics(
        self,
        post_id:    str,
        platform:   str,
        metrics:    Dict,
    ) -> None:
        """Update engagement metrics for a test record and update angle weights."""
        views    = metrics.get("views",    0)
        likes    = metrics.get("likes",    0)
        shares   = metrics.get("shares",   0)
        saves    = metrics.get("saves",    0)
        comments = metrics.get("comments", 0)
        eng      = round(
            (likes + shares * 2 + saves * 3 + comments * 2) / max(1, views) * 100, 4
        )

        with self._conn() as c:
            c.execute(
                """UPDATE ab_tests
                   SET views=?, likes=?, shares=?, saves=?, comments=?,
                       engagement=?, metrics_pulled=1, pulled_at=?
                   WHERE post_id=? AND platform=?""",
                (views, likes, shares, saves, comments, eng, time.time(), post_id, platform)
            )
            # Fetch niche + angle for this post to update weights
            row = c.execute(
                "SELECT angle, niche FROM ab_tests WHERE post_id=? AND platform=? LIMIT 1",
                (post_id, platform)
            ).fetchone()

        if row:
            self._update_weights(platform, row[0], row[1], eng)

    def get_best_angle(
        self,
        platform: str,
        niche:    str = "general",
    ) -> str:
        """
        Return the best angle to use for this platform/niche.
        Uses UCB1 to balance exploration vs exploitation.
        """
        with self._conn() as c:
            rows = c.execute(
                """SELECT angle, weight, wins, trials
                   FROM angle_weights
                   WHERE platform=? AND niche=?""",
                (platform, niche)
            ).fetchall()

        if not rows:
            return "mystery"   # default before any data

        # UCB1 score: avg + sqrt(2 * ln(total_trials) / trials_for_arm)
        total_trials = sum(r[3] for r in rows)
        import math
        best_angle = "mystery"
        best_score = -1.0

        for row in rows:
            angle, weight, wins, trials = row[0], row[1], row[2], row[3]
            if trials == 0:
                # Never tried — highest priority for exploration
                return angle
            exploit = weight
            explore = self.EXPLORATION_FACTOR * math.sqrt(
                math.log(max(1, total_trials)) / trials
            )
            score = exploit + explore
            if score > best_score:
                best_score = score
                best_angle = angle

        return best_angle

    def angle_report(self, platform: str, niche: str = "general") -> List[AngleResult]:
        """Return performance report for all angles on this platform/niche."""
        with self._conn() as c:
            rows = c.execute(
                """SELECT aw.angle, aw.weight, aw.wins, aw.trials,
                          AVG(ab.engagement) as avg_eng
                   FROM angle_weights aw
                   LEFT JOIN ab_tests ab ON ab.angle=aw.angle
                       AND ab.platform=aw.platform
                       AND ab.niche=aw.niche
                       AND ab.metrics_pulled=1
                   WHERE aw.platform=? AND aw.niche=?
                   GROUP BY aw.angle
                   ORDER BY aw.weight DESC""",
                (platform, niche)
            ).fetchall()

        return [
            AngleResult(
                angle          = r[0],
                weight         = r[1],
                wins           = r[2],
                trials         = r[3],
                avg_engagement = r[4] or 0.0,
            )
            for r in rows
        ]

    def pending_metric_pulls(self, min_hours: float = 24.0, max_hours: float = 72.0) -> List[Dict]:
        """Return ab_tests records that are ready for metric pull."""
        now  = time.time()
        low  = now - max_hours * 3600
        high = now - min_hours * 3600
        with self._conn() as c:
            rows = c.execute(
                """SELECT post_id, platform FROM ab_tests
                   WHERE metrics_pulled=0
                   AND uploaded_at BETWEEN ? AND ?""",
                (low, high)
            ).fetchall()
        return [{"post_id": r[0], "platform": r[1]} for r in rows]

    # ── Internal ────────────────────────────────────────────────────────────

    def _update_weights(self, platform: str, angle: str, niche: str, engagement: float) -> None:
        """Update angle weight using exponential moving average."""
        with self._conn() as c:
            row = c.execute(
                "SELECT weight, wins, trials FROM angle_weights WHERE platform=? AND niche=? AND angle=?",
                (platform, niche, angle)
            ).fetchone()

            if row:
                old_weight = row[0]
                wins   = row[1] + (1 if engagement > 3.0 else 0)
                trials = row[2] + 1
                # EMA: new_weight = 0.7*old + 0.3*normalised_engagement
                new_weight = 0.7 * old_weight + 0.3 * min(1.0, engagement / 5.0)
                c.execute(
                    """UPDATE angle_weights
                       SET weight=?, wins=?, trials=?, updated_at=?
                       WHERE platform=? AND niche=? AND angle=?""",
                    (new_weight, wins, trials, time.time(), platform, niche, angle)
                )
            else:
                new_weight = min(1.0, engagement / 5.0)
                c.execute(
                    """INSERT INTO angle_weights (platform, niche, angle, weight, wins, trials, updated_at)
                       VALUES (?,?,?,?,?,?,?)""",
                    (platform, niche, angle, new_weight,
                     1 if engagement > 3.0 else 0, 1, time.time())
                )

    def _init_weights(self) -> None:
        """Insert default weights for all angles if not present."""
        default_platforms = ["facebook", "tiktok", "instagram", "youtube"]
        default_niches    = ["movie", "anime", "kdrama", "horror", "general"]
        with self._conn() as c:
            for platform in default_platforms:
                for niche in default_niches:
                    for angle in ANGLES:
                        c.execute(
                            """INSERT OR IGNORE INTO angle_weights
                               (platform, niche, angle, weight, wins, trials, updated_at)
                               VALUES (?,?,?,1.0,0,0,?)""",
                            (platform, niche, angle, time.time())
                        )

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
