"""
decision_engine_free.py v10.0 FREE — Rule-based PROCESS/SKIP/DEFER.

No AI calls. Uses only composite video score + hard rules.
Drop-in for decision_engine.py with no API key required.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

EXCLUDED_KEYWORDS = [
    "live stream", "podcast full", "interview full", "#shorts",
    "unboxing", "stream highlights", "vlog"
]


@dataclass
class DecisionResult:
    decision: str   # PROCESS | SKIP | DEFER
    reason: str
    score: float = 0.0
    angle: str = "mystery"
    ai_used: bool = False


class DecisionEngineFree:
    """100% free rule-based decision engine. No API calls."""

    def __init__(
        self,
        scorer,
        content_gen=None,           # ignored
        ai_threshold_low: float = 0.20,
        ai_threshold_high: float = 0.55,
        min_duration_s: int = 60,
        max_duration_s: int = 7200,
    ) -> None:
        self.scorer = scorer
        self.process_threshold = ai_threshold_low   # anything above this → PROCESS
        self.min_duration_s = min_duration_s
        self.max_duration_s = max_duration_s
        self._stats = {"PROCESS": 0, "SKIP": 0, "DEFER": 0}

    def decide(self, video, history_summary: str = "") -> DecisionResult:
        dur = getattr(video, "duration", 0) or 0

        # Hard duration gates
        if dur < self.min_duration_s:
            return DecisionResult("SKIP", f"Too short ({dur}s)", 0.0)
        if dur > self.max_duration_s:
            return DecisionResult("SKIP", f"Too long ({dur}s)", 0.0)

        # Keyword exclusion
        title = (getattr(video, "title", "") or "").lower()
        for kw in EXCLUDED_KEYWORDS:
            if kw in title:
                return DecisionResult("SKIP", f"Excluded keyword: {kw}", 0.0)

        # Score-based decision
        vs = self.scorer.score(video)
        score = vs.composite

        self._stats[vs.decision] = self._stats.get(vs.decision, 0) + 1

        if score >= self.process_threshold:
            angle = self._pick_angle(vs)
            log.debug("[Decision] PROCESS score=%.3f angle=%s", score, angle)
            return DecisionResult("PROCESS", f"Score {score:.3f}", score, angle=angle)

        log.debug("[Decision] SKIP score=%.3f", score)
        return DecisionResult("SKIP", f"Low score ({score:.3f})", score)

    def _pick_angle(self, vs) -> str:
        """Pick best angle based on video metrics — no AI needed."""
        velocity = getattr(vs, "velocity_score", 0.5)
        engagement = getattr(vs, "engagement_score", 0.5)

        if velocity > 0.7:
            return "shocking"       # fast growing = shocking angle
        if engagement > 0.7:
            return "emotional"      # high engagement = emotional
        if velocity < 0.3:
            return "educational"    # slow but steady = educational
        return "mystery"            # default safe bet

    def stats(self) -> dict:
        return dict(self._stats)


# Drop-in alias
DecisionEngine = DecisionEngineFree
