"""
growth_predictor.py v9.0 — ML Engagement Predictor.

Pre-upload predictor that gates uploads based on predicted engagement.
Uses mini-batch gradient descent — pure Python, no scikit-learn needed.
Auto-retrains after every --pull-metrics run.

Features (10):
  clip_quality, arc_role_weight, angle_weight, platform_weight,
  day_of_week, hour_of_day, niche_weight, hook_length,
  series_position, channel_performance
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS predictions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    upload_id       TEXT    NOT NULL UNIQUE,
    platform        TEXT    NOT NULL,
    niche           TEXT    NOT NULL,
    features_json   TEXT    NOT NULL,
    predicted_score REAL    NOT NULL DEFAULT 0.0,
    actual_score    REAL    NOT NULL DEFAULT -1.0,
    created_at      REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS model_weights (
    feature     TEXT    PRIMARY KEY,
    weight      REAL    NOT NULL DEFAULT 0.0,
    updated_at  REAL    NOT NULL
);
"""

FEATURES = [
    "clip_quality", "arc_role_weight", "angle_weight", "platform_weight",
    "day_of_week", "hour_of_day", "niche_weight", "hook_length",
    "series_position", "channel_performance",
]

ARC_ROLE_WEIGHTS = {"SETUP": 0.6, "CLUE_DROP": 0.8, "ESCALATION": 0.9, "REVELATION": 1.0}
ANGLE_WEIGHTS = {"mystery": 0.9, "shocking": 0.85, "emotional": 0.8,
                 "educational": 0.7, "controversial": 0.75, "motivational": 0.65}
PLATFORM_WEIGHTS = {"tiktok": 1.0, "instagram": 0.9, "youtube": 0.85,
                    "facebook": 0.8, "threads": 0.6}


@dataclass
class PredictionResult:
    upload_id: str
    predicted_score: float
    passed_gate: bool
    confidence: float
    features: Dict[str, float]


class GrowthPredictor:
    """Predicts engagement score before upload to gate low-value clips."""

    def __init__(
        self,
        db_path: Path,
        prediction_gate: bool = False,
        threshold: float = 1.2,
        min_confidence: float = 0.30,
        min_samples: int = 20,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.gate = prediction_gate
        self.threshold = threshold
        self.min_confidence = min_confidence
        self.min_samples = min_samples
        self._weights: Dict[str, float] = {f: 0.1 for f in FEATURES}

        with self._conn() as c:
            c.executescript(SCHEMA)
        self._load_weights()
        log.info("[GrowthPredictor] init gate=%s threshold=%.2f", self.gate, self.threshold)

    def predict(
        self,
        upload_id: str,
        platform: str,
        niche: str,
        clip_quality: float = 0.5,
        arc_role: str = "ESCALATION",
        angle: str = "mystery",
        hook_length: int = 20,
        series_position: int = 1,
        total_clips: int = 10,
        channel_performance: float = 0.5,
    ) -> PredictionResult:
        now = time.localtime()
        features = {
            "clip_quality": clip_quality,
            "arc_role_weight": ARC_ROLE_WEIGHTS.get(arc_role, 0.7),
            "angle_weight": ANGLE_WEIGHTS.get(angle, 0.7),
            "platform_weight": PLATFORM_WEIGHTS.get(platform, 0.7),
            "day_of_week": now.tm_wday / 6.0,
            "hour_of_day": now.tm_hour / 23.0,
            "niche_weight": 0.8,  # updated by retraining
            "hook_length": min(1.0, hook_length / 28.0),
            "series_position": 1.0 - (series_position / max(1, total_clips)),
            "channel_performance": channel_performance,
        }

        score = sum(self._weights.get(f, 0.1) * v for f, v in features.items())
        samples = self._sample_count()
        confidence = min(1.0, samples / self.min_samples)
        passed = (not self.gate) or (confidence < self.min_confidence) or (score >= self.threshold)

        with self._conn() as c:
            c.execute("""
                INSERT OR REPLACE INTO predictions
                (upload_id, platform, niche, features_json, predicted_score, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (upload_id, platform, niche, json.dumps(features), score, time.time()))

        return PredictionResult(upload_id=upload_id, predicted_score=score,
                                passed_gate=passed, confidence=confidence, features=features)

    def record_actual(self, upload_id: str, actual_engagement: float) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE predictions SET actual_score=? WHERE upload_id=?",
                (actual_engagement, upload_id),
            )

    def retrain(self) -> int:
        """Mini-batch gradient descent on collected samples. Returns sample count."""
        with self._conn() as c:
            rows = c.execute("""
                SELECT features_json, actual_score FROM predictions
                WHERE actual_score >= 0 ORDER BY created_at DESC LIMIT 200
            """).fetchall()

        if len(rows) < 5:
            log.info("[GrowthPredictor] insufficient data (%d samples)", len(rows))
            return len(rows)

        lr = 0.01
        for features_json, actual in rows:
            try:
                features = json.loads(features_json)
            except Exception:
                continue
            predicted = sum(self._weights.get(f, 0.1) * v for f, v in features.items())
            error = actual - predicted
            for f, v in features.items():
                self._weights[f] = self._weights.get(f, 0.1) + lr * error * v

        self._save_weights()
        log.info("[GrowthPredictor] retrained on %d samples", len(rows))
        return len(rows)

    def _load_weights(self) -> None:
        with self._conn() as c:
            rows = c.execute("SELECT feature, weight FROM model_weights").fetchall()
        for feature, weight in rows:
            self._weights[feature] = weight

    def _save_weights(self) -> None:
        now = time.time()
        with self._conn() as c:
            for feature, weight in self._weights.items():
                c.execute("""
                    INSERT OR REPLACE INTO model_weights (feature, weight, updated_at)
                    VALUES (?, ?, ?)
                """, (feature, weight, now))

    def _sample_count(self) -> int:
        with self._conn() as c:
            return c.execute(
                "SELECT COUNT(*) FROM predictions WHERE actual_score >= 0"
            ).fetchone()[0]

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=15)
