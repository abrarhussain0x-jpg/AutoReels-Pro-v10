"""
narrative_arc.py v9.0 — TV-show style narrative arc planner.

Plans an entire clip series as a structured arc (SETUP → CLUE_DROP →
ESCALATION → REVELATION) before processing begins. Each clip gets a
unique narrative role for series continuity.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

ARC_ROLES = ["SETUP", "CLUE_DROP", "ESCALATION", "REVELATION"]

ARC_TYPES: Dict[str, List[str]] = {
    "movie":       ["mystery", "thriller"],
    "anime":       ["binge", "mystery"],
    "kdrama":      ["emotional", "binge"],
    "horror":      ["thriller", "mystery"],
    "documentary": ["educational", "mystery"],
    "general":     ["mystery", "binge"],
}

ANGLE_FOR_ROLE: Dict[str, str] = {
    "SETUP":       "mystery",
    "CLUE_DROP":   "shocking",
    "ESCALATION":  "emotional",
    "REVELATION":  "controversial",
}


@dataclass
class NarrativeNode:
    clip_index: int
    role: str
    angle: str
    hook_context: str = ""
    arc_type: str = "mystery"


@dataclass
class NarrativeArcPlan:
    video_id: str
    video_title: str
    arc_type: str
    nodes: List[NarrativeNode] = field(default_factory=list)

    def get_clip(self, clip_index: int) -> NarrativeNode:
        for node in self.nodes:
            if node.clip_index == clip_index:
                return node
        # Fallback
        role = ARC_ROLES[(clip_index - 1) % len(ARC_ROLES)]
        return NarrativeNode(clip_index=clip_index, role=role,
                             angle=ANGLE_FOR_ROLE[role], arc_type=self.arc_type)

    def angle_for(self, clip_index: int) -> str:
        return self.get_clip(clip_index).angle


class NarrativeArcEngine:
    """Plans a complete arc for a video series in a single AI call."""

    ENDPOINT = "https://api.anthropic.com/v1/messages"

    def __init__(
        self,
        api_key: str = "",
        niche: str = "movie",
        enabled: bool = True,
    ) -> None:
        self.api_key = api_key
        self.niche = niche
        self.enabled = enabled

    def plan(self, video_id: str, video_title: str, n_clips: int) -> NarrativeArcPlan:
        """Plan the narrative arc for all n_clips."""
        arc_types = ARC_TYPES.get(self.niche, ARC_TYPES["general"])
        arc_type = arc_types[0]

        if not self.enabled or not self.api_key:
            return self._deterministic_plan(video_id, video_title, n_clips, arc_type)

        try:
            return self._ai_plan(video_id, video_title, n_clips, arc_type)
        except Exception as exc:
            log.warning("[NarrativeArc] AI planning failed: %s — fallback", exc)
            return self._deterministic_plan(video_id, video_title, n_clips, arc_type)

    def _ai_plan(
        self, video_id: str, title: str, n_clips: int, arc_type: str
    ) -> NarrativeArcPlan:
        prompt = (
            f"Plan a {arc_type} narrative arc for {n_clips} short-form video clips "
            f"from: \"{title}\" (niche: {self.niche}).\n\n"
            f"Arc roles available: {', '.join(ARC_ROLES)}\n"
            f"Angles available: mystery, shocking, emotional, educational, controversial, motivational\n\n"
            f"For each clip return: clip_index, role, angle, hook_context (1 sentence teaser).\n"
            f"Respond ONLY with a JSON array of {n_clips} objects. No preamble."
        )
        body = json.dumps({
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": n_clips * 80 + 200,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(
            self.ENDPOINT, data=body,
            headers={"Content-Type": "application/json",
                     "x-api-key": self.api_key,
                     "anthropic-version": "2023-06-01"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        text = data["content"][0]["text"].strip()
        if text.startswith("```"):
            text = "\n".join(text.split("\n")[1:]).rstrip("```").strip()
        items = json.loads(text)

        nodes = []
        for item in items:
            role = str(item.get("role", "ESCALATION")).upper()
            if role not in ARC_ROLES:
                role = ARC_ROLES[len(nodes) % len(ARC_ROLES)]
            nodes.append(NarrativeNode(
                clip_index=int(item.get("clip_index", len(nodes) + 1)),
                role=role,
                angle=str(item.get("angle", ANGLE_FOR_ROLE[role])),
                hook_context=str(item.get("hook_context", ""))[:100],
                arc_type=arc_type,
            ))
        return NarrativeArcPlan(video_id=video_id, video_title=title,
                                arc_type=arc_type, nodes=nodes)

    def _deterministic_plan(
        self, video_id: str, title: str, n_clips: int, arc_type: str
    ) -> NarrativeArcPlan:
        nodes = []
        for i in range(1, n_clips + 1):
            role = ARC_ROLES[(i - 1) % len(ARC_ROLES)]
            nodes.append(NarrativeNode(
                clip_index=i, role=role,
                angle=ANGLE_FOR_ROLE[role], arc_type=arc_type,
            ))
        return NarrativeArcPlan(video_id=video_id, video_title=title,
                                arc_type=arc_type, nodes=nodes)
