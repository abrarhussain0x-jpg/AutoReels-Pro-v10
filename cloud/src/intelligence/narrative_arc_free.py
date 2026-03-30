"""
narrative_arc_free.py v10.0 FREE — Deterministic arc planner, no API.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List

ARC_ROLES = ["SETUP", "CLUE_DROP", "ESCALATION", "REVELATION"]
ANGLE_FOR_ROLE: Dict[str, str] = {
    "SETUP": "mystery", "CLUE_DROP": "shocking",
    "ESCALATION": "emotional", "REVELATION": "controversial",
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
        role = ARC_ROLES[(clip_index - 1) % len(ARC_ROLES)]
        return NarrativeNode(clip_index=clip_index, role=role,
                             angle=ANGLE_FOR_ROLE[role], arc_type=self.arc_type)

    def angle_for(self, clip_index: int) -> str:
        return self.get_clip(clip_index).angle

class NarrativeArcEngine:
    def __init__(self, api_key="", niche="movie", enabled=True):
        self.niche = niche

    def plan(self, video_id: str, video_title: str, n_clips: int) -> NarrativeArcPlan:
        nodes = []
        for i in range(1, n_clips + 1):
            role = ARC_ROLES[(i - 1) % len(ARC_ROLES)]
            nodes.append(NarrativeNode(
                clip_index=i, role=role,
                angle=ANGLE_FOR_ROLE[role], arc_type="mystery",
            ))
        return NarrativeArcPlan(video_id=video_id, video_title=video_title,
                                arc_type="mystery", nodes=nodes)
