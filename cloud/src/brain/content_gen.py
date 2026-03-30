"""
content_gen.py v9.0 — Adaptive multi-model AI content generation.

Upgrades vs v8:
  - Model tiering: Sonnet 4 for high-value clips, Haiku for standard
  - Arc-aware captions: uses NarrativeArcNode context for series continuity
  - Batch generation: all clips in ONE API call per platform
  - Cross-platform differentiation: structurally different captions per platform
  - Proven retention hook formula (curiosity gap + social proof + urgency)
  - Enhanced cache keyed on (video_title, platform, clip_index, angle, arc_role)
"""

import hashlib
import json
import logging
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

MODEL_HAIKU  = "claude-haiku-4-5-20251001"
MODEL_SONNET = "claude-sonnet-4-6"
HIGH_VALUE_SCORE = 0.65

FALLBACK_HOOKS: Dict[str, str] = {
    "mystery":       "NOBODY TALKS ABOUT THIS",
    "shocking":      "THE TWIST IS INSANE",
    "emotional":     "THIS HIT DIFFERENT",
    "educational":   "WHAT THEY DON T TELL YOU",
    "controversial": "HOT TAKE NOBODY ASKED FOR",
    "motivational":  "WATCH THIS IF YOU FEEL STUCK",
}

FALLBACK_CAPTIONS: Dict[str, str] = {
    "tiktok":    "Part {index} just dropped! Follow {channel} so you never miss an episode!",
    "facebook":  "Part {index} is here! Follow {channel} for daily recaps!",
    "instagram": "Part {index} Save this + follow {channel} for the next part!",
    "youtube":   "Watch Part {index} now. Subscribe to {channel} for daily content!",
    "threads":   "Part {index} thread — follow {channel} for the full story.",
}

PLATFORM_CAP_LIMIT: Dict[str, int] = {
    "tiktok": 2200, "facebook": 10000, "instagram": 2200, "youtube": 5000, "threads": 500,
}
PLATFORM_TAG_LIMIT: Dict[str, int] = {
    "tiktok": 30, "facebook": 10, "instagram": 30, "youtube": 15, "threads": 10,
}
PLATFORM_STYLES: Dict[str, str] = {
    "tiktok":    "1-2 sentences, start with emoji/verb, 3-7 high-reach hashtags, conversational lowercase",
    "facebook":  "2-3 sentences, ask a question, 3-5 broad hashtags, warm friendly tone",
    "instagram": "Hook first line, 2-3 sentences, hashtags in separate block, strategic emojis",
    "youtube":   "Keyword-rich first line, 2-3 descriptive sentences, 10-15 keyword hashtags",
    "threads":   "1-2 sentences max (500 chars), conversational, 3-5 hashtags, minimal emoji",
}


@dataclass
class GeneratedContent:
    hook:          str
    title_rewrite: str
    caption:       str
    hashtags:      List[str]
    cta:           str
    angle:         str  = "mystery"
    platform:      str  = "tiktok"
    arc_role:      str  = ""
    from_cache:    bool = False
    from_fallback: bool = False
    model_used:    str  = ""


@dataclass
class BatchPlan:
    video_id: str
    clips: Dict[int, Dict[str, "GeneratedContent"]] = field(default_factory=dict)

    def get(self, clip_index: int, platform: str) -> Optional["GeneratedContent"]:
        return self.clips.get(clip_index, {}).get(platform)


class ContentGenerator:
    ENDPOINT  = "https://api.anthropic.com/v1/messages"
    CACHE_TTL = 3600

    def __init__(self, api_key: str = "", niche: str = "movie", channel_name: str = "AutoReels"):
        self.api_key      = api_key
        self.niche        = niche
        self.channel_name = channel_name
        self._cache: Dict[str, tuple] = {}

    def generate(
        self,
        video_title:       str,
        platform:          str   = "tiktok",
        clip_index:        int   = 1,
        total_clips:       int   = 10,
        angle:             str   = "mystery",
        video_description: str   = "",
        arc_role:          str   = "",
        arc_context:       str   = "",
        composite_score:   float = 0.0,
    ) -> GeneratedContent:
        cache_key = hashlib.md5(
            f"{video_title}|{platform}|{clip_index}|{angle}|{arc_role}".encode()
        ).hexdigest()
        if cache_key in self._cache:
            cached, ts = self._cache[cache_key]
            if time.time() - ts < self.CACHE_TTL:
                c = GeneratedContent(**vars(cached))
                c.from_cache = True
                return c

        if not self.api_key:
            return self._fallback(video_title, platform, clip_index, angle, arc_role)

        model = MODEL_SONNET if composite_score >= HIGH_VALUE_SCORE else MODEL_HAIKU
        try:
            result = self._single_call(
                model, video_title, platform, clip_index, total_clips,
                angle, arc_role, arc_context
            )
            result.model_used = model
            self._cache[cache_key] = (result, time.time())
            return result
        except Exception as e:
            log.warning("[ContentGen] API error (%s) — fallback: %s", model, e)
            return self._fallback(video_title, platform, clip_index, angle, arc_role)

    def generate_batch(
        self,
        video_id:        str,
        video_title:     str,
        n_clips:         int,
        platforms:       List[str],
        arc_plan=None,
        composite_score: float = 0.0,
    ) -> BatchPlan:
        plan = BatchPlan(video_id=video_id)
        for platform in platforms:
            try:
                clips = self._batch_call(video_title, platform, n_clips, arc_plan, composite_score)
                for idx, content in clips.items():
                    plan.clips.setdefault(idx, {})[platform] = content
            except Exception as e:
                log.warning("[ContentGen] Batch failed %s: %s — using fallbacks", platform, e)
                for i in range(1, n_clips + 1):
                    angle    = arc_plan.angle_for(i) if arc_plan else "mystery"
                    arc_role = arc_plan.get_clip(i).role if arc_plan else ""
                    plan.clips.setdefault(i, {})[platform] = self._fallback(
                        video_title, platform, i, angle, arc_role
                    )
        return plan

    def _single_call(
        self, model, video_title, platform, clip_index, total_clips,
        angle, arc_role, arc_context
    ) -> GeneratedContent:
        from src.brain.prompts import build_content_prompt_v9
        prompt = build_content_prompt_v9(
            video_title=video_title, platform=platform, clip_index=clip_index,
            total_clips=total_clips, angle=angle, niche=self.niche,
            arc_role=arc_role, arc_context=arc_context, channel=self.channel_name,
            style_guide=PLATFORM_STYLES.get(platform, ""),
        )
        raw = self._call(model, prompt, max_tokens=500)
        return self._parse_single(raw, platform, angle, arc_role)

    def _batch_call(
        self, video_title, platform, n_clips, arc_plan, composite_score
    ) -> Dict[int, GeneratedContent]:
        model       = MODEL_SONNET if composite_score >= HIGH_VALUE_SCORE else MODEL_HAIKU
        style_guide = PLATFORM_STYLES.get(platform, "")
        cap_limit   = PLATFORM_CAP_LIMIT.get(platform, 500)
        tag_limit   = PLATFORM_TAG_LIMIT.get(platform, 15)

        specs = []
        for i in range(1, n_clips + 1):
            role  = arc_plan.get_clip(i).role if arc_plan else "ESCALATION"
            angle = arc_plan.angle_for(i) if arc_plan else "mystery"
            specs.append(f"  Clip {i}: role={role}, angle={angle}")

        prompt = (
            f"You are a viral content strategist for {self.niche} on {platform.title()}.\n"
            f"Video: \"{video_title}\" | Channel: {self.channel_name}\n"
            f"Platform style: {style_guide}\n"
            f"Caption limit: {cap_limit} chars | Max hashtags: {tag_limit}\n\n"
            f"Generate content for {n_clips} clips:\n"
            + "\n".join(specs)
            + f"\n\nFor EACH clip return a JSON object with: clip_index, hook (ALL-CAPS 2-6 words max 28 chars), "
              f"title_rewrite (50-80 chars), caption (platform-native), hashtags (array no # prefix), "
              f"cta (3-8 words).\n"
              f"Build series continuity — each caption references previous parts naturally.\n"
              f"Respond ONLY with a JSON array of {n_clips} objects. No preamble."
        )

        raw  = self._call(model, prompt, max_tokens=n_clips * 200 + 300)
        raw  = self._strip_fences(raw)
        try:
            items = json.loads(raw)
        except Exception:
            return {}

        result = {}
        for item in items:
            idx   = int(item.get("clip_index", 0))
            angle = arc_plan.angle_for(idx) if (arc_plan and idx) else "mystery"
            role  = arc_plan.get_clip(idx).role if (arc_plan and idx) else ""
            if not idx:
                continue
            result[idx] = GeneratedContent(
                hook=str(item.get("hook", FALLBACK_HOOKS.get(angle,"WATCH THIS"))).upper()[:30],
                title_rewrite=str(item.get("title_rewrite",""))[:80],
                caption=str(item.get("caption",""))[:cap_limit],
                hashtags=[str(h).lstrip("#") for h in item.get("hashtags",[])][:tag_limit],
                cta=str(item.get("cta","Follow for more"))[:60],
                angle=angle, platform=platform, arc_role=role, model_used=model,
            )
        return result

    def _call(self, model: str, prompt: str, max_tokens: int = 600) -> str:
        body = json.dumps({
            "model": model, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(
            self.ENDPOINT, data=body,
            headers={"Content-Type": "application/json",
                     "x-api-key": self.api_key,
                     "anthropic-version": "2023-06-01"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read())
        return data["content"][0]["text"].strip()

    def _parse_single(self, raw: str, platform: str, angle: str, arc_role: str) -> GeneratedContent:
        raw = self._strip_fences(raw)
        try:
            d = json.loads(raw)
            return GeneratedContent(
                hook=str(d.get("hook", FALLBACK_HOOKS.get(angle,"WATCH THIS"))).upper()[:30],
                title_rewrite=str(d.get("title_rewrite",""))[:80],
                caption=str(d.get("caption",""))[:PLATFORM_CAP_LIMIT.get(platform,500)],
                hashtags=[str(h).lstrip("#") for h in d.get("hashtags",[])][:30],
                cta=str(d.get("cta","Follow for more"))[:60],
                angle=angle, platform=platform, arc_role=arc_role,
            )
        except Exception:
            return self._fallback("", platform, 1, angle, arc_role)

    @staticmethod
    def _strip_fences(text: str) -> str:
        if text.startswith("```"):
            text = "\n".join(text.split("\n")[1:])
        if text.endswith("```"):
            text = "\n".join(text.split("\n")[:-1])
        return text.strip()

    def _fallback(self, video_title, platform, clip_index, angle, arc_role="") -> GeneratedContent:
        tpl     = FALLBACK_CAPTIONS.get(platform, FALLBACK_CAPTIONS["tiktok"])
        caption = tpl.format(index=clip_index, channel=self.channel_name, next=clip_index+1)
        return GeneratedContent(
            hook=FALLBACK_HOOKS.get(angle,"WATCH THIS"),
            title_rewrite=video_title[:80],
            caption=caption,
            hashtags=[self.niche,"viral","reels",platform,"trending"],
            cta=f"Follow {self.channel_name} for Part {clip_index+1}!",
            angle=angle, platform=platform, arc_role=arc_role, from_fallback=True,
        )
