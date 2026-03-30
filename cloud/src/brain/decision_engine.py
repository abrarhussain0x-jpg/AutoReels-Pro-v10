"""
decision_engine.py v8.0 — Two-tier decision engine.

Tier 1: Fast rules (~80% of decisions, no AI call)
Tier 2: Claude Haiku for borderline cases

New in v8:
  • scorer attribute exposed (pipeline accesses it for velocity fast-track)
  • decide() returns angle recommendation from A/B engine
  • History context passed to AI prompt
  • Reason field populated for all decisions
"""

import logging
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class DecisionResult:
    decision: str        # PROCESS | SKIP | DEFER
    reason:   str
    score:    float      = 0.0
    angle:    str        = "mystery"    # v8: recommended angle
    ai_used:  bool       = False


class DecisionEngine:
    def __init__(
        self,
        scorer,
        content_gen          = None,
        ai_threshold_low:    float = 0.20,
        ai_threshold_high:   float = 0.55,
        min_duration_s:      int   = 120,
        max_duration_s:      int   = 7200,
    ):
        self.scorer            = scorer   # EXPOSED for pipeline velocity fast-track
        self.content_gen       = content_gen
        self.ai_threshold_low  = ai_threshold_low
        self.ai_threshold_high = ai_threshold_high
        self.min_duration_s    = min_duration_s
        self.max_duration_s    = max_duration_s
        self._decisions        = {"PROCESS": 0, "SKIP": 0, "DEFER": 0}

    def decide(self, video, history_summary: str = "") -> DecisionResult:
        dur = getattr(video, "duration", 0) or 0

        # Hard rejects — no score needed
        if dur < self.min_duration_s:
            return DecisionResult("SKIP", f"Too short ({dur}s < {self.min_duration_s}s)")
        if dur > self.max_duration_s:
            return DecisionResult("SKIP", f"Too long ({dur}s > {self.max_duration_s}s)")

        title = (getattr(video, "title", "") or "").lower()
        if any(kw in title for kw in ["live stream", "podcast full", "interview full", "#shorts"]):
            return DecisionResult("SKIP", "Excluded keyword in title")

        # Fast-path scoring
        vs    = self.scorer.score(video)
        score = vs.composite

        self._decisions[vs.decision] = self._decisions.get(vs.decision, 0) + 1

        # High confidence — no AI needed
        if score >= self.ai_threshold_high:
            log.debug("[Decision] Fast PROCESS (score=%.3f)", score)
            return DecisionResult("PROCESS", f"High score ({score:.3f})", score)
        if score < self.ai_threshold_low:
            log.debug("[Decision] Fast SKIP (score=%.3f)", score)
            return DecisionResult("SKIP", f"Low score ({score:.3f})", score)

        # Borderline — escalate to AI
        if self.content_gen and self.content_gen.api_key:
            return self._ai_decide(video, vs, history_summary)

        # No AI — apply threshold directly
        return DecisionResult(vs.decision, f"Score {score:.3f}", score)

    def stats(self) -> dict:
        return dict(self._decisions)

    def _ai_decide(self, video, vs, history: str) -> DecisionResult:
        import urllib.request
        import json

        meta = (
            f"Title: {getattr(video, 'title', 'Unknown')}\n"
            f"Views: {getattr(video, 'view_count', 0):,}\n"
            f"Duration: {getattr(video, 'duration', 0)}s\n"
            f"Like ratio: {getattr(video, 'like_count', 0) / max(1, getattr(video, 'view_count', 1)):.3f}\n"
            f"Upload date: {getattr(video, 'upload_date', 'unknown')}\n"
            f"Channel: {getattr(video, 'channel', 'unknown')}\n"
            f"Tags: {', '.join(getattr(video, 'tags', [])[:5])}\n"
            f"Composite score: {vs.composite:.3f} (vel={vs.velocity_score:.2f}, eng={vs.engagement_score:.2f})\n"
        )

        from src.brain.prompts import DECISION_PROMPT
        prompt = DECISION_PROMPT.format(metadata=meta, history=history or "No history yet.")

        try:
            payload = json.dumps({
                "model":      "claude-haiku-4-5-20251001",
                "max_tokens": 100,
                "messages":   [{"role": "user", "content": prompt}],
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages", data=payload, method="POST"
            )
            req.add_header("Content-Type",      "application/json")
            req.add_header("x-api-key",         self.content_gen.api_key)
            req.add_header("anthropic-version", "2023-06-01")
            with urllib.request.urlopen(req, timeout=15) as resp:
                data     = json.loads(resp.read())
                text     = data["content"][0]["text"].strip()
                lines    = [l.strip() for l in text.splitlines() if l.strip()]
                decision = lines[0].upper() if lines else "DEFER"
                reason   = lines[1] if len(lines) > 1 else f"AI: {decision}"

            if decision not in ("PROCESS", "SKIP", "DEFER"):
                decision = "DEFER"

            self._decisions[decision] = self._decisions.get(decision, 0) + 1
            return DecisionResult(decision, reason, vs.composite, ai_used=True)
        except Exception as exc:
            log.warning("[Decision] AI call failed: %s — falling back to score", exc)
            return DecisionResult(vs.decision, f"Score {vs.composite:.3f} (AI failed)", vs.composite)
