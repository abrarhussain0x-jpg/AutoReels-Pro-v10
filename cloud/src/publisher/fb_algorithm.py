"""
fb_algorithm.py — Facebook Algorithm Optimizer.

Implements every known Facebook Reels ranking signal to maximize reach:
  1. Watch-time optimization (first 3 seconds hook text)
  2. Completion rate boosters (cliffhanger endings)
  3. Engagement velocity triggers (question CTAs, polls)
  4. Share bait formulas (emotion + social proof)
  5. Comment triggers (open-ended questions)
  6. Save triggers (series continuity)
  7. Optimal description length (Facebook prefers 100-250 chars)
  8. Hashtag strategy (3-5 broad + 2-3 niche)
  9. First-comment strategy (auto-post first comment)
  10. Posting frequency optimizer

Facebook Reels ranking factors (2024-2025):
  - Watch time / completion rate (highest weight ~40%)
  - Shares (second highest ~25%)
  - Comments (15%)
  - Likes/reactions (10%)
  - Saves (10%)
"""
from __future__ import annotations
import logging, random, re
from dataclasses import dataclass
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

# ── Proven Hook Formulas (3-second retention) ────────────────────────────────
HOOK_FORMULAS = {
    "question":     ["Wait — did {subject} actually {action}?",
                     "Why does NOBODY talk about {subject}?",
                     "Can you guess what happens to {subject}?"],
    "number":       ["{n} things you missed in {title}",
                     "Part {i} — {n} secrets revealed",
                     "The #{n} moment everyone skips"],
    "contrast":     ["Everyone watched this wrong",
                     "The real ending nobody explains",
                     "What the trailer didn't show you"],
    "urgency":      ["Watch before Part {next} drops",
                     "You need to see Part {i} first",
                     "Don't scroll — this part matters"],
}

# ── Proven CTA Formulas (drives comments + shares) ───────────────────────────
CTA_FORMULAS = {
    "question":   [
        "💬 Comment your reaction below!",
        "💬 Did you see this coming? Comment!",
        "💬 What would YOU have done? Comment below!",
        "💬 Drop a 🔥 if you're watching the whole series!",
        "💬 Who else didn't see that twist coming?",
    ],
    "share":      [
        "📤 Tag someone who needs to see this!",
        "📤 Share with a movie lover who'd love this!",
        "📤 Send this to someone who needs a good story!",
        "📤 Tag your watch partner!",
    ],
    "follow":     [
        "🔔 Follow {channel} — Part {next} drops soon!",
        "👆 Follow {channel} so you never miss a part!",
        "✅ Follow {channel} for the full story!",
        "🎬 Follow {channel} — we post daily recaps!",
    ],
    "save":       [
        "🔖 Save this so you can find Part {next}!",
        "📌 Save this series — {total} parts total!",
        "💾 Save for later — the ending is INSANE!",
    ],
}

# ── First Comment Templates (boosts early engagement) ────────────────────────
FIRST_COMMENTS = [
    "⬇️ PART {next} is already up on our page! Don't miss it!",
    "🔥 Full story is on our page — {total} parts total! Follow us!",
    "👇 Drop a 🔥 if you want Part {next} faster!",
    "💬 Comment 'MORE' and we'll know you want Part {next}!",
    "📌 Save this post to find it when Part {next} drops!",
    "⚡ Part {next} is coming — follow so you don't miss it!",
]

# ── Caption length optimization ───────────────────────────────────────────────
# Facebook shows full caption for < ~400 chars, truncates with "See more" after
OPTIMAL_CAPTION_MAX = 380    # characters before "See more" cuts off
OPTIMAL_CAPTION_MIN = 100    # too short = less context for algorithm


@dataclass
class OptimizedPost:
    caption: str
    first_comment: str
    hook_overlay: str       # burned into video (top text)
    end_card_text: str      # burned into last 2 seconds
    hashtags: List[str]
    best_cta_type: str
    predicted_reach_multiplier: float


class FacebookAlgorithmOptimizer:
    """
    Optimizes every post for maximum Facebook algorithm reach.
    Applies all known ranking signals to captions, CTAs, and hooks.
    """

    def __init__(self, channel_name: str = "AutoReels", niche: str = "movie"):
        self.channel = channel_name
        self.niche   = niche
        self._post_count = 0  # tracks rotation
        log.info("[FBAlgo] init channel=%s niche=%s", channel_name, niche)

    def optimize(
        self,
        base_caption: str,
        video_title:  str,
        clip_index:   int,
        total_clips:  int,
        hook_text:    str = "",
        angle:        str = "mystery",
        hashtags:     Optional[List[str]] = None,
    ) -> OptimizedPost:
        """
        Full Facebook algorithm optimization pass.
        Returns OptimizedPost with all elements ready to use.
        """
        self._post_count += 1

        # ── 1. Build optimized caption ────────────────────────────────────────
        caption = self._build_caption(
            base_caption, video_title, clip_index, total_clips, angle
        )

        # ── 2. Pick CTAs (rotate types for algorithm diversity) ───────────────
        cta_types = self._select_cta_rotation(clip_index)
        cta_block  = self._build_cta_block(cta_types, clip_index, total_clips)
        caption    = caption + "\n\n" + cta_block

        # ── 3. Enforce optimal length ─────────────────────────────────────────
        caption = self._trim_to_optimal(caption)

        # ── 4. Build hashtag block (3-5 broad + 2 niche) ─────────────────────
        optimized_tags = self._build_hashtags(hashtags or [], clip_index)

        # ── 5. Hook overlay text (burned into first 3 seconds of video) ───────
        hook_overlay = self._build_hook_overlay(
            hook_text, video_title, clip_index, angle
        )

        # ── 6. End card text (last 2 seconds drives follow + next part) ───────
        end_card = f"PART {clip_index + 1} → Follow {self.channel}!"

        # ── 7. First comment (boosts early engagement velocity) ───────────────
        first_comment = self._build_first_comment(clip_index, total_clips)

        # ── 8. Predict reach multiplier ───────────────────────────────────────
        reach_mult = self._predict_reach(caption, optimized_tags, cta_types)

        log.info("[FBAlgo] clip %d optimized | len=%d tags=%d reach_mult=%.1fx",
                 clip_index, len(caption), len(optimized_tags), reach_mult)

        return OptimizedPost(
            caption=caption + "\n" + " ".join(f"#{t}" for t in optimized_tags),
            first_comment=first_comment,
            hook_overlay=hook_overlay,
            end_card_text=end_card,
            hashtags=optimized_tags,
            best_cta_type=cta_types[0],
            predicted_reach_multiplier=reach_mult,
        )

    # ── Caption Building ──────────────────────────────────────────────────────

    def _build_caption(
        self, base: str, title: str, idx: int, total: int, angle: str
    ) -> str:
        """Build attention-optimized caption with emotion + social proof."""
        short_title = title[:40] if len(title) > 40 else title

        # Opening line (must grab attention before "See more" cutoff)
        openers = {
            "mystery":       f"🔍 Part {idx} — the truth about \"{short_title}\" nobody talks about.",
            "shocking":      f"😱 Part {idx} — the twist in \"{short_title}\" broke everyone.",
            "emotional":     f"😭 Part {idx} — the most emotional moment in \"{short_title}\".",
            "educational":   f"🧠 Part {idx} — hidden details in \"{short_title}\" you missed.",
            "controversial": f"🔥 Part {idx} — the most controversial scene in \"{short_title}\".",
            "motivational":  f"💪 Part {idx} — the life-changing moment in \"{short_title}\".",
        }
        opener = openers.get(angle, f"🎬 Part {idx} of \"{short_title}\" is here.")

        # Middle (social proof + urgency)
        middle_options = [
            f"Thousands are watching this series right now — don't fall behind!",
            f"This is the part everyone's been waiting for.",
            f"If you haven't seen Part 1, go to our page first!",
            f"The story gets even better from here.",
            f"Follow our page — {total - idx} more parts to go!",
        ]
        middle = middle_options[idx % len(middle_options)]

        return f"{opener}\n{middle}"

    def _build_cta_block(self, cta_types: List[str], idx: int, total: int) -> str:
        """Build a 2-3 line CTA block targeting different engagement types."""
        lines = []
        for cta_type in cta_types[:2]:
            pool = CTA_FORMULAS.get(cta_type, CTA_FORMULAS["follow"])
            line = pool[idx % len(pool)].format(
                channel=self.channel,
                next=idx + 1,
                total=total,
            )
            lines.append(line)
        return "\n".join(lines)

    def _select_cta_rotation(self, clip_index: int) -> List[str]:
        """
        Rotate CTA types to avoid algorithm fatigue.
        Facebook rewards diverse engagement signals.
        Pattern: question → share → follow → save → repeat
        """
        patterns = [
            ["question", "follow"],
            ["share", "follow"],
            ["question", "save"],
            ["follow", "question"],
            ["share", "save"],
        ]
        return patterns[clip_index % len(patterns)]

    def _trim_to_optimal(self, text: str) -> str:
        """Keep caption body within optimal length (before 'See more' cutoff)."""
        lines = text.split("\n")
        result = []
        total  = 0
        for line in lines:
            if total + len(line) + 1 > OPTIMAL_CAPTION_MAX:
                break
            result.append(line)
            total += len(line) + 1
        return "\n".join(result)

    # ── Hook Overlay ──────────────────────────────────────────────────────────

    def _build_hook_overlay(
        self, hook: str, title: str, idx: int, angle: str
    ) -> str:
        """Build the 3-second hook overlay text burned into video."""
        if hook and len(hook) >= 5:
            return hook.upper()[:28]

        # Generate from formula
        formula_type = {
            "mystery": "contrast", "shocking": "contrast",
            "emotional": "question", "educational": "number",
            "controversial": "contrast", "motivational": "urgency",
        }.get(angle, "contrast")

        pool = HOOK_FORMULAS.get(formula_type, HOOK_FORMULAS["contrast"])
        tpl  = pool[idx % len(pool)]
        text = tpl.format(
            subject="this scene", action="really happen",
            title=title[:20], n=idx, i=idx, next=idx + 1,
        )
        return text.upper()[:28]

    # ── Hashtags ──────────────────────────────────────────────────────────────

    def _build_hashtags(self, base_tags: List[str], idx: int) -> List[str]:
        """
        Facebook optimal hashtag strategy:
        - 3-5 broad reach tags
        - 2-3 niche-specific tags
        - 1-2 trending/timely tags
        Total: 6-9 tags (more hurts reach on Facebook)
        """
        broad_tags = {
            "movie":       ["movierecap", "filmtok", "movienight", "watchthis"],
            "anime":       ["anime", "animerecommendation", "animelover", "manga"],
            "kdrama":      ["kdrama", "koreandramas", "koreandrama", "kdramaaddict"],
            "horror":      ["horror", "scarymovie", "horrorfan", "horrorfilm"],
            "documentary": ["documentary", "truestory", "facts", "didyouknow"],
        }
        niche_tags = {
            "movie":       ["movieexplained", "moviebreakdown", "filmrecap"],
            "anime":       ["animerecap", "animereview", "animecommunity"],
            "kdrama":      ["kdramarecap", "kdramaedit", "dramaaddicted"],
            "horror":      ["horrorrecap", "horrorexplained", "scarystories"],
            "documentary": ["realstory", "historyfacts", "docureview"],
        }
        trending = ["viral", "reels", "fbreels"]

        all_tags = []
        all_tags += broad_tags.get(self.niche, ["viral", "watchthis"])[:4]
        all_tags += niche_tags.get(self.niche, ["recap"])[:2]
        all_tags += trending[:2]

        # Add base tags (deduplicated)
        for t in base_tags:
            if t not in all_tags:
                all_tags.append(t)

        return list(dict.fromkeys(all_tags))[:9]   # max 9 for Facebook

    # ── First Comment ─────────────────────────────────────────────────────────

    def _build_first_comment(self, clip_index: int, total_clips: int) -> str:
        """First comment posted immediately after upload to seed engagement."""
        tpl = FIRST_COMMENTS[clip_index % len(FIRST_COMMENTS)]
        return tpl.format(
            next=clip_index + 1,
            total=total_clips,
            channel=self.channel,
        )

    # ── Reach Predictor ───────────────────────────────────────────────────────

    def _predict_reach(
        self, caption: str, tags: List[str], cta_types: List[str]
    ) -> float:
        """
        Simple rule-based reach multiplier predictor.
        Based on Facebook algorithm known factors.
        """
        score = 1.0

        # Caption length (100-380 optimal)
        cap_len = len(caption)
        if OPTIMAL_CAPTION_MIN <= cap_len <= OPTIMAL_CAPTION_MAX:
            score += 0.3
        elif cap_len < OPTIMAL_CAPTION_MIN:
            score -= 0.1

        # Has question CTA (drives comments = big reach boost)
        if "question" in cta_types:
            score += 0.4

        # Has share CTA
        if "share" in cta_types:
            score += 0.25

        # Optimal hashtag count (6-9 for Facebook)
        if 6 <= len(tags) <= 9:
            score += 0.2
        elif len(tags) > 15:
            score -= 0.15   # too many hurts reach

        # Has emoji (increases engagement rate)
        if re.search(r'[^\x00-\x7F]', caption):
            score += 0.1

        return round(score, 2)
