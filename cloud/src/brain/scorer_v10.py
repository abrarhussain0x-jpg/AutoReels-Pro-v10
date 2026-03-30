"""
scorer_v10.py — Real 8-component video scorer using live metadata.
Scores videos BEFORE downloading based on: engagement, recency,
velocity, trend keywords, channel history, duration fit, title quality,
and viral potential signals.

Outputs composite 0.0-1.0 score to gate PROCESS vs SKIP decisions.
"""
from __future__ import annotations
import logging, math, re, time
from dataclasses import dataclass
from datetime import datetime
from typing import List

log = logging.getLogger(__name__)

VIRAL_KEYWORDS = [
    "explained", "recap", "full movie", "ending explained", "plot twist",
    "every", "all", "entire", "complete", "breakdown", "summary",
    "reaction", "twist", "secret", "hidden", "real story",
]
SKIP_KEYWORDS = [
    "live", "stream", "podcast", "interview", "vlog", "unboxing",
    "shorts", "compilation", "#shorts",
]

NICHE_KEYWORDS = {
    "movie":       ["movie", "film", "cinema", "recap", "explained", "plot"],
    "anime":       ["anime", "manga", "episode", "season", "arc"],
    "kdrama":      ["kdrama", "korean", "drama", "ep", "episode"],
    "horror":      ["horror", "scary", "terror", "thriller", "ghost"],
    "documentary": ["documentary", "real", "true story", "history", "facts"],
}


@dataclass
class VideoScore:
    composite:        float
    engagement_score: float
    recency_score:    float
    velocity_score:   float
    trend_score:      float
    channel_score:    float
    duration_score:   float
    title_score:      float
    viral_score:      float
    decision:         str   # PROCESS | DEFER | SKIP
    reasons:          List[str]


class VideoScorerV10:
    """
    8-component scorer. No external calls — uses metadata from VideoMeta.
    Weights tunable in config.yaml under scoring_weights.
    """

    def __init__(self, config: dict):
        w = config.get("scoring_weights", {})
        self.w_engagement = w.get("engagement",  0.25)
        self.w_recency    = w.get("recency",      0.20)
        self.w_velocity   = w.get("velocity",     0.15)
        self.w_trend      = w.get("trend",        0.15)
        self.w_channel    = w.get("channel",      0.10)
        self.w_duration   = w.get("duration",     0.05)
        self.w_title      = w.get("title",        0.05)
        self.w_viral      = w.get("viral",        0.05)

        self.niche            = config.get("niche", "movie")
        self.process_threshold = float(config.get("process_threshold", 0.01))
        self.defer_threshold   = float(config.get("defer_threshold",   0.01))
        self._channel_history: dict = {}   # channel_id → avg_score

    def score(self, video) -> VideoScore:
        reasons = []

        # ── 1. Engagement ─────────────────────────────────────────────────────
        views = getattr(video, "view_count", 0) or 0
        likes = getattr(video, "like_count", 0) or 0
        like_ratio = likes / max(1, views)
        eng = min(1.0, math.log1p(views) / math.log1p(1_000_000))
        eng = eng * 0.7 + min(1.0, like_ratio / 0.05) * 0.3
        if views > 100_000: reasons.append(f"high views {views:,}")

        # ── 2. Recency ────────────────────────────────────────────────────────
        upload_date = getattr(video, "upload_date", "") or ""
        rec = 0.5
        if upload_date and len(upload_date) == 8:
            try:
                dt   = datetime.strptime(upload_date, "%Y%m%d")
                days = (datetime.now() - dt).days
                rec  = max(0.0, 1.0 - days / 30)
                if days <= 3:  reasons.append("very recent (<3d)")
            except Exception:
                pass

        # ── 3. Velocity (like/view growth proxy) ──────────────────────────────
        vel = min(1.0, like_ratio / 0.04)

        # ── 4. Trend keywords ─────────────────────────────────────────────────
        title_lower = (getattr(video, "title", "") or "").lower()
        niche_kws   = NICHE_KEYWORDS.get(self.niche, [])
        viral_hits  = sum(1 for kw in VIRAL_KEYWORDS if kw in title_lower)
        niche_hits  = sum(1 for kw in niche_kws if kw in title_lower)
        trend = min(1.0, (viral_hits * 0.15 + niche_hits * 0.2))
        if niche_hits > 0: reasons.append(f"niche match ({niche_hits} keywords)")

        # ── 5. Channel history ────────────────────────────────────────────────
        ch_id  = getattr(video, "channel", "") or ""
        ch_score = self._channel_history.get(ch_id, 0.5)

        # ── 6. Duration fit ───────────────────────────────────────────────────
        dur = getattr(video, "duration", 0) or 0
        if 300 <= dur <= 3600:
            dur_score = 1.0     # ideal: 5 min to 1 hour
        elif 60 <= dur < 300:
            dur_score = 0.7
        elif 3600 < dur <= 7200:
            dur_score = 0.6
        else:
            dur_score = 0.1

        # ── 7. Title quality ──────────────────────────────────────────────────
        title_len  = len(title_lower)
        has_number = bool(re.search(r'\d', title_lower))
        title_score = min(1.0,
            (0.5 if 30 <= title_len <= 80 else 0.2) +
            (0.3 if viral_hits > 0 else 0.0) +
            (0.2 if has_number else 0.0)
        )

        # ── 8. Viral potential ────────────────────────────────────────────────
        desc   = (getattr(video, "description", "") or "").lower()
        tags   = [t.lower() for t in getattr(video, "tags", [])]
        viral  = min(1.0,
            viral_hits * 0.12 +
            sum(0.08 for t in tags if t in VIRAL_KEYWORDS) +
            (0.2 if "explained" in title_lower else 0) +
            (0.15 if "recap" in title_lower else 0)
        )

        # ── Composite ─────────────────────────────────────────────────────────
        composite = (
            self.w_engagement * eng +
            self.w_recency    * rec +
            self.w_velocity   * vel +
            self.w_trend      * trend +
            self.w_channel    * ch_score +
            self.w_duration   * dur_score +
            self.w_title      * title_score +
            self.w_viral      * viral
        )

        # Skip hard-reject keywords
        if any(kw in title_lower for kw in SKIP_KEYWORDS):
            composite = 0.0
            reasons.append("skip keyword in title")

        # Decision gate
        if composite >= self.process_threshold:
            decision = "PROCESS"
        elif composite >= self.defer_threshold:
            decision = "DEFER"
        else:
            decision = "SKIP"

        return VideoScore(
            composite=round(composite, 4),
            engagement_score=eng, recency_score=rec,
            velocity_score=vel,   trend_score=trend,
            channel_score=ch_score, duration_score=dur_score,
            title_score=title_score, viral_score=viral,
            decision=decision, reasons=reasons,
        )

    def update_channel_history(self, channel_id: str, score: float):
        """Update running channel average (fed by analytics after uploads)."""
        old = self._channel_history.get(channel_id, 0.5)
        self._channel_history[channel_id] = old * 0.8 + score * 0.2
