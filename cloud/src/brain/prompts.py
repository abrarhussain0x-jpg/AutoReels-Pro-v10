"""
prompts.py v9.0 — Prompt builders for AI content generation.
Adds build_content_prompt_v9() with arc role + platform style guide support.
"""
from typing import Optional


def build_content_prompt_v9(
    video_title: str,
    platform:    str,
    clip_index:  int,
    total_clips: int,
    angle:       str,
    niche:       str,
    arc_role:    str   = "",
    arc_context: str   = "",
    channel:     str   = "AutoReels",
    style_guide: str   = "",
) -> str:
    arc_block = ""
    if arc_role:
        arc_block = f"\nNarrative role for this clip: {arc_role}"
    if arc_context:
        arc_block += f"\nSeries context: {arc_context}"

    return f"""You are a viral content strategist for {niche} on {platform.title()}.

Video: "{video_title}" | Clip: {clip_index}/{total_clips} | Angle: {angle}
Channel: {channel}
Platform style: {style_guide}{arc_block}

Generate a JSON object with these exact keys:
  "hook"          — 2-6 ALL-CAPS words (max 28 chars) that appear as a video overlay
  "title_rewrite" — SEO-optimised title variant (50-80 chars)
  "caption"       — platform-native caption (follows platform style guide exactly)
  "hashtags"      — array of strings without # prefix (platform-appropriate count)
  "cta"           — 3-8 word call-to-action specific to {platform}

Rules:
- hook must match the arc role — {arc_role or 'be attention-grabbing'}
- caption must naturally include "Part {clip_index}"
- build continuity from previous parts if clip_index > 1
- cta must drive the key engagement action on {platform}

Respond ONLY with the JSON object. No preamble or explanation."""


def build_content_prompt(
    video_title: str,
    platform:    str,
    clip_index:  int,
    total_clips: int,
    angle:       str,
    niche:       str,
) -> str:
    """v8 compatibility shim — delegates to v9."""
    return build_content_prompt_v9(
        video_title=video_title,
        platform=platform,
        clip_index=clip_index,
        total_clips=total_clips,
        angle=angle,
        niche=niche,
    )
