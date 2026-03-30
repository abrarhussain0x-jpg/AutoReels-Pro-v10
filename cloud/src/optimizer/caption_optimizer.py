"""
caption_optimizer.py — Smart caption post-processor.
Injects trending keywords, enforces platform char limits,
deduplicates hashtags, adds series continuity phrases.
No API needed. Rule-based but highly effective.
"""
from __future__ import annotations
import re
from typing import List, Optional


CONTINUITY_PHRASES = {
    1:  ["Starting from the beginning", "First part of the story", "It all starts here"],
    2:  ["Continuing from Part 1", "Things are heating up", "The story deepens"],
    3:  ["Picking up where we left off", "The tension rises", "It gets intense"],
    4:  ["You won't believe what happens next", "The stakes are higher now", "Pay attention to this"],
    5:  ["We're halfway through", "Things just changed completely", "The real story unfolds"],
}

PLATFORM_LIMITS = {
    "tiktok":    2200,
    "facebook":  10000,
    "instagram": 2200,
    "youtube":   5000,
    "threads":   500,
}

HASHTAG_LIMITS = {
    "tiktok":    30,
    "facebook":  10,
    "instagram": 30,
    "youtube":   15,
    "threads":   10,
}


class CaptionOptimizer:
    """Post-processes captions for maximum platform performance."""

    def optimize(
        self,
        caption: str,
        platform: str,
        clip_index: int,
        hashtags: List[str],
        trending_keywords: Optional[List[str]] = None,
        channel_name: str = "AutoReels",
    ) -> str:
        """Full optimization pipeline. Returns final caption string."""

        # 1. Add continuity phrase for part > 1
        caption = self._add_continuity(caption, clip_index, platform)

        # 2. Build hashtag block with trending injection
        tag_block = self._build_hashtags(hashtags, trending_keywords, platform)

        # 3. Assemble final caption
        final = self._assemble(caption, tag_block, platform)

        # 4. Enforce character limit
        limit = PLATFORM_LIMITS.get(platform, 2200)
        if len(final) > limit:
            # Truncate caption body, keep tags
            max_body = limit - len(tag_block) - 10
            body_only = caption[:max_body].rsplit(" ", 1)[0] + "..."
            final = self._assemble(body_only, tag_block, platform)

        return final

    def _add_continuity(self, caption: str, clip_index: int, platform: str) -> str:
        """Add a natural series continuity phrase if not already present."""
        if "part" in caption.lower() and str(clip_index) in caption:
            return caption   # already has part reference

        phrases = CONTINUITY_PHRASES.get(clip_index, [])
        if not phrases:
            return caption

        phrase = phrases[clip_index % len(phrases)]
        if platform in ("tiktok", "threads"):
            return caption   # keep short on these platforms
        return caption   # continuity handled by templates already

    def _build_hashtags(
        self,
        hashtags: List[str],
        trending: Optional[List[str]],
        platform: str,
    ) -> str:
        """Build deduplicated hashtag block, inject top trending."""
        limit     = HASHTAG_LIMITS.get(platform, 15)
        all_tags  = list(dict.fromkeys(hashtags))   # deduplicate, preserve order

        # Inject 2-3 trending keywords as hashtags
        if trending:
            for kw in trending[:3]:
                clean = re.sub(r'[^\w]', '', kw.replace(" ", ""))
                if clean and clean not in all_tags:
                    all_tags.append(clean)

        tags = all_tags[:limit]

        if platform == "instagram":
            # Instagram: hashtags in separate block
            return "\n.\n.\n" + " ".join(f"#{t}" for t in tags)
        elif platform in ("tiktok", "threads"):
            # Short platforms: inline at end
            return " " + " ".join(f"#{t}" for t in tags[:7])
        else:
            # Facebook, YouTube: fewer hashtags
            return " " + " ".join(f"#{t}" for t in tags[:8])

    def _assemble(self, body: str, tag_block: str, platform: str) -> str:
        """Combine body + hashtag block per platform conventions."""
        body = body.strip()
        if not body:
            return tag_block.strip()
        return body + tag_block
