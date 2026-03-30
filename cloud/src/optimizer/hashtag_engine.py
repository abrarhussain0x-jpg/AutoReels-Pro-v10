"""
hashtag_engine.py — Niche-aware hashtag selection engine.

Selects and orders hashtags to maximise reach per platform using:
  - A curated niche library
  - Performance-weighted selection (bandit-style)
  - Platform-specific rules (Instagram ≤30, TikTok ≤10, FB loose)
"""
from __future__ import annotations
import json
import logging
import random
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

# ── Built-in niche libraries ──────────────────────────────────────────────────
_LIBRARY: Dict[str, List[str]] = {
    "movie": [
        "movieclips", "moviereels", "filmtok", "cinemaaddicts", "moviecommunity",
        "movierecommendations", "filmlovers", "watchthis", "movienight", "netflixandchill",
        "horrormovies", "actionmovies", "dramafilm", "comedymovies", "thrillermovies",
        "mustwatch", "streamingpicks", "moviestowatch", "filmbuff", "cinematography",
        "filmscene", "moviequotes", "bestscenes", "epicmovies", "moviefanatic",
    ],
    "motivation": [
        "motivation", "mindset", "success", "grind", "hustle", "selfimprovement",
        "personaldevelopment", "discipline", "focus", "goals", "growthmindset",
        "entrepreneurship", "dailymotivation", "levelup", "winning", "inspirationalquotes",
        "motivationalquotes", "successmindset", "hardwork", "nevergiveup",
    ],
    "fitness": [
        "fitness", "workout", "gym", "fitfam", "fitnessmotivation", "bodybuilding",
        "exercise", "health", "wellbeing", "gains", "weightloss", "personaltrainer",
        "homeworkout", "cardio", "strength", "sweat", "fitlife", "healthylifestyle",
    ],
    "tech": [
        "tech", "technology", "ai", "coding", "programming", "developer", "startup",
        "innovation", "software", "machinelearning", "python", "javascript", "cybersecurity",
        "gadgets", "futuretech", "techtok", "artificialintelligence", "techmemes",
    ],
    "finance": [
        "finance", "investing", "stocks", "crypto", "money", "wealthbuilding",
        "passiveincome", "sidehustle", "financialfreedom", "moneytips", "budgeting",
        "stockmarket", "personalfinance", "realestate", "entrepreneur", "richlifestyle",
    ],
    "general": [
        "viral", "trending", "fyp", "foryou", "foryoupage", "explore", "reels",
        "shorts", "video", "content", "creator", "follow", "like", "share",
        "trending", "viral", "mustwatch", "amazing", "interesting",
    ],
}

# Platform limits
_LIMITS = {"instagram": 30, "tiktok": 10, "facebook": 20, "threads": 15}
_DEFAULT_LIMIT = 20


class HashtagEngine:
    """
    Selects and ranks hashtags for a post.

    Tracks performance (clicks/views per hashtag) in a local SQLite DB
    and biases future selection toward better-performing tags using a
    simple UCB1 bandit approach.
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        niche: str = "general",
        enabled: bool = True,
    ):
        self.niche   = niche
        self.enabled = enabled
        self.db_path = db_path or Path("queue/hashtags.db")
        self._init_db()

    # ── Public API ────────────────────────────────────────────────────────────

    def get_hashtags(
        self,
        platform: str,
        niche: Optional[str] = None,
        count: Optional[int] = None,
        extra_tags: Optional[List[str]] = None,
    ) -> List[str]:
        """
        Return a list of hashtags for the given platform.
        Always includes niche-specific tags + general reach tags.
        """
        if not self.enabled:
            return []

        niche      = niche or self.niche
        limit      = count or _LIMITS.get(platform, _DEFAULT_LIMIT)
        pool       = self._build_pool(niche)
        scored     = self._score_tags(pool, platform)
        selected   = [t for t, _ in scored[:limit]]

        if extra_tags:
            for tag in extra_tags:
                tag = tag.lstrip("#").lower().strip()
                if tag and tag not in selected:
                    if len(selected) >= limit:
                        selected.pop()
                    selected.insert(0, tag)

        log.debug("[Hashtag] %s/%s → %d tags", platform, niche, len(selected))
        return selected

    def format_caption(
        self,
        caption: str,
        platform: str,
        niche: Optional[str] = None,
    ) -> str:
        """Append formatted hashtags to a caption."""
        tags = self.get_hashtags(platform, niche)
        if not tags:
            return caption
        tag_str = " ".join(f"#{t}" for t in tags)
        return f"{caption}\n\n{tag_str}"

    def record_performance(self, tag: str, platform: str, views: int, clicks: int = 0):
        """Update performance stats for a hashtag."""
        try:
            with sqlite3.connect(self.db_path) as con:
                con.execute(
                    """INSERT INTO hashtag_stats (tag, platform, impressions, clicks, uses)
                       VALUES (?, ?, ?, ?, 1)
                       ON CONFLICT(tag, platform) DO UPDATE SET
                           impressions = impressions + excluded.impressions,
                           clicks      = clicks      + excluded.clicks,
                           uses        = uses        + 1""",
                    (tag, platform, views, clicks),
                )
        except Exception as e:
            log.debug("[Hashtag] record_performance error: %s", e)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _build_pool(self, niche: str) -> List[str]:
        niche_tags   = _LIBRARY.get(niche, [])
        general_tags = _LIBRARY["general"]
        combined     = list(dict.fromkeys(niche_tags + general_tags))  # dedup, preserve order
        return combined

    def _score_tags(self, pool: List[str], platform: str) -> List[tuple]:
        """
        Score tags by UCB1: score = mean_ctr + sqrt(2 * ln(total_uses) / tag_uses)
        Tags with no data get a random exploration score.
        """
        try:
            with sqlite3.connect(self.db_path) as con:
                rows = con.execute(
                    "SELECT tag, impressions, clicks, uses FROM hashtag_stats WHERE platform=?",
                    (platform,),
                ).fetchall()
            stats = {r[0]: (r[1], r[2], r[3]) for r in rows}
        except Exception:
            stats = {}

        import math
        total_uses = sum(s[2] for s in stats.values()) or 1

        scored = []
        for tag in pool:
            if tag in stats:
                imp, clicks, uses = stats[tag]
                ctr   = clicks / max(imp, 1)
                bonus = math.sqrt(2 * math.log(total_uses) / uses)
                score = ctr + bonus
            else:
                score = 0.5 + random.random() * 0.5   # unexplored → random
            scored.append((tag, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def _init_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with sqlite3.connect(self.db_path) as con:
                con.execute("""
                    CREATE TABLE IF NOT EXISTS hashtag_stats (
                        tag         TEXT    NOT NULL,
                        platform    TEXT    NOT NULL,
                        impressions INTEGER DEFAULT 0,
                        clicks      INTEGER DEFAULT 0,
                        uses        INTEGER DEFAULT 0,
                        PRIMARY KEY (tag, platform)
                    )
                """)
        except Exception as e:
            log.warning("[Hashtag] DB init failed: %s", e)
