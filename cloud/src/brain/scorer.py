"""
scorer.py v8.0 — Multi-factor video scoring engine.

New in v8:
  • Viral velocity score: views/hour rate (exponential, not linear)
  • Like ratio signal: likes/views as audience quality indicator
  • Comment engagement: high comment ratio = controversy/discussion = algorithmic boost
  • Engagement composite: combines all signals into a single weighted score
  • All thresholds configurable via config.yaml
"""

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Protocol

log = logging.getLogger(__name__)


@dataclass
class VideoScore:
    video_id:          str
    engagement_score:  float    # 0-1: view count via logistic curve
    recency_score:     float    # 1.0=today → 0.0 at 7 days
    velocity_score:    float    # views/hour (exponential normalised)
    trend_boost:       float    # 0-0.5 if title matches trending topics
    channel_perf:      float    # 0-1: channel's historical engagement in our analytics
    like_ratio_score:  float    # 0-1: likes/views quality signal
    comment_score:     float    # 0-1: comments/views discussion signal
    composite:         float    # final weighted score
    decision:          str      # PROCESS | SKIP | DEFER

    def __str__(self) -> str:
        return (
            f"[{self.video_id[:12]}] composite={self.composite:.3f} "
            f"eng={self.engagement_score:.2f} rec={self.recency_score:.2f} "
            f"vel={self.velocity_score:.2f} trend={self.trend_boost:.2f} "
            f"chan={self.channel_perf:.2f} lr={self.like_ratio_score:.2f} "
            f"→ {self.decision}"
        )


class FeedbackDB(Protocol):
    def channel_performance(self, channel_id: str) -> float: ...


class VideoScorer:
    """
    Weights (configurable via config.yaml scoring_weights):
      engagement  0.25  — view count normalised via logistic curve
      recency     0.20  — linear decay over 7 days
      velocity    0.20  — views/hour exponential normalised
      trend       0.15  — trending topic keyword match
      channel     0.10  — historical performance of source channel
      like_ratio  0.07  — likes/views audience quality signal
      comments    0.03  — comments/views discussion signal
    """

    DEFAULT_WEIGHTS = dict(
        engagement  = 0.25,
        recency     = 0.20,
        velocity    = 0.20,
        trend       = 0.15,
        channel     = 0.10,
        like_ratio  = 0.07,
        comments    = 0.03,
    )

    def __init__(
        self,
        feedback_db:       Optional[FeedbackDB] = None,
        trend_topics:      Optional[list]        = None,
        weights:           Optional[dict]        = None,
        process_threshold: float                 = 0.35,
        defer_threshold:   float                 = 0.20,
    ):
        self.feedback          = feedback_db
        self.trends            = set(t.lower() for t in (trend_topics or []))
        self.weights           = {**self.DEFAULT_WEIGHTS, **(weights or {})}
        self.process_threshold = process_threshold
        self.defer_threshold   = defer_threshold

        # Normalise weights to sum to 1.0
        total = sum(self.weights.values())
        if total > 0:
            self.weights = {k: v / total for k, v in self.weights.items()}

    # ── Public ─────────────────────────────────────────────────────────────

    def score(self, video) -> VideoScore:
        eng  = self._engagement(video)
        rec  = self._recency(getattr(video, "upload_date", ""))
        vel  = self._velocity(video)
        trend = self._trend(getattr(video, "title", ""))
        chan  = self._channel(getattr(video, "channel_id", "")) if self.feedback else 0.5
        lr   = self._like_ratio(video)
        comm = self._comment_score(video)

        w = self.weights
        composite = (
            eng  * w.get("engagement",  0.25)
            + rec  * w.get("recency",     0.20)
            + vel  * w.get("velocity",    0.20)
            + trend * w.get("trend",      0.15)
            + chan  * w.get("channel",    0.10)
            + lr   * w.get("like_ratio",  0.07)
            + comm * w.get("comments",    0.03)
        )
        composite = round(min(1.0, max(0.0, composite)), 4)

        # Viral velocity fast-track: if vel > 0.8 and eng > 0.6, always PROCESS
        if vel > 0.80 and eng > 0.60:
            decision = "PROCESS"
        elif composite >= self.process_threshold:
            decision = "PROCESS"
        elif composite >= self.defer_threshold:
            decision = "DEFER"
        else:
            decision = "SKIP"

        vs = VideoScore(
            video_id          = getattr(video, "video_id", "unknown"),
            engagement_score  = eng,
            recency_score     = rec,
            velocity_score    = vel,
            trend_boost       = trend,
            channel_perf      = chan,
            like_ratio_score  = lr,
            comment_score     = comm,
            composite         = composite,
            decision          = decision,
        )
        log.debug("Score: %s", vs)
        return vs

    def score_many(self, videos: list) -> list:
        """Score and sort a list of videos, highest score first."""
        scored = [(v, self.score(v)) for v in videos]
        scored.sort(key=lambda x: x[1].composite, reverse=True)
        return scored

    # ── Scoring components ─────────────────────────────────────────────────

    def _engagement(self, video) -> float:
        """Logistic curve: 100k views → 0.50, 500k → 0.80, 1M+ → ~0.95"""
        views = getattr(video, "view_count", 0) or 0
        try:
            views = int(views)
        except (TypeError, ValueError):
            return 0.0
        if views <= 0:
            return 0.0
        return round(1.0 / (1.0 + math.exp(-0.0000135 * (views - 100_000))), 4)

    def _recency(self, upload_date: str) -> float:
        """Exponential decay: today=1.0, drops faster in first 3 days."""
        if not upload_date:
            return 0.4
        for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d"):
            try:
                dt       = datetime.strptime(str(upload_date), fmt).replace(tzinfo=timezone.utc)
                age_days = max(0, (datetime.now(timezone.utc) - dt).days)
                # Exponential decay with 3-day half-life
                return round(max(0.0, math.exp(-0.25 * age_days)), 4)
            except ValueError:
                continue
        return 0.4

    def _velocity(self, video) -> float:
        """
        Views per hour since upload — exponential normalised.
        1k vph = 0.40, 5k vph = 0.80, 10k+ vph = 1.0
        """
        views       = getattr(video, "view_count", 0) or 0
        upload_date = getattr(video, "upload_date", "") or ""
        if not views or not upload_date:
            return 0.0
        for fmt in ("%Y%m%d", "%Y-%m-%d"):
            try:
                dt    = datetime.strptime(upload_date, fmt)
                hours = max(1.0, (datetime.now() - dt).total_seconds() / 3600)
                vph   = views / hours
                # 1 - exp(-vph/5000) normalises: 5k vph → 0.63, 10k → 0.86, 20k → 0.98
                return round(1.0 - math.exp(-vph / 5000), 4)
            except ValueError:
                continue
        return 0.0

    def _trend(self, title: str) -> float:
        """0-0.5 boost based on trending keyword matches in title."""
        if not self.trends or not title:
            return 0.0
        title_words = set(str(title).lower().replace(",", "").replace(".", "").split())
        matches     = title_words & self.trends
        return round(min(0.5, len(matches) * 0.12), 4)

    def _channel(self, channel_id: str) -> float:
        """Historical engagement score for this source channel."""
        if not self.feedback or not channel_id:
            return 0.5
        try:
            return round(self.feedback.channel_performance(str(channel_id)), 4)
        except Exception:
            return 0.5

    def _like_ratio(self, video) -> float:
        """Likes/views ratio — audience quality signal."""
        likes  = getattr(video, "like_count",  0) or 0
        views  = getattr(video, "view_count",  0) or 0
        if not views:
            return 0.3   # neutral when unknown
        ratio = likes / views
        # 1% like ratio → 0.50, 3% → 0.80, 5%+ → 1.0
        return round(min(1.0, 1.0 - math.exp(-50 * ratio)), 4)

    def _comment_score(self, video) -> float:
        """Comments/views ratio — discussion drives algorithmic boost."""
        comments = getattr(video, "comment_count", 0) or 0
        views    = getattr(video, "view_count",     0) or 0
        if not views:
            return 0.2
        ratio = comments / views
        # 0.1% comment ratio → ~0.50, 0.3%+ → high
        return round(min(1.0, 1.0 - math.exp(-1000 * ratio)), 4)
