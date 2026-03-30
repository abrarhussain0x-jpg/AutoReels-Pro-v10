"""
caption_ab_tester.py — Caption formula A/B testing engine.

Tests different caption structures on real posts and learns
which formula drives the most comments, shares, and follows.

Caption types tested:
  A: Question-led   ("Did you see what happened?...")
  B: Statement-led  ("This scene broke everyone...")
  C: Number-led     ("3 things you missed...")
  D: Story-led      ("Nobody talks about this...")
  E: Urgency-led    ("Watch before Part X drops...")

Rotates types per upload, records results, picks winner after 10+ trials.
"""
from __future__ import annotations
import logging, math, sqlite3, time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS caption_tests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id         TEXT NOT NULL,
    caption_type    TEXT NOT NULL,
    niche           TEXT NOT NULL DEFAULT 'movie',
    platform        TEXT NOT NULL DEFAULT 'facebook',
    caption_preview TEXT NOT NULL DEFAULT '',
    comments        INTEGER NOT NULL DEFAULT 0,
    shares          INTEGER NOT NULL DEFAULT 0,
    likes           INTEGER NOT NULL DEFAULT 0,
    reach           INTEGER NOT NULL DEFAULT 0,
    engagement_rate REAL    NOT NULL DEFAULT 0.0,
    uploaded_at     REAL    NOT NULL,
    metrics_pulled  INTEGER NOT NULL DEFAULT 0,
    UNIQUE(post_id)
);
CREATE TABLE IF NOT EXISTS caption_weights (
    caption_type TEXT NOT NULL,
    niche        TEXT NOT NULL,
    platform     TEXT NOT NULL,
    weight       REAL NOT NULL DEFAULT 1.0,
    wins         INTEGER NOT NULL DEFAULT 0,
    trials       INTEGER NOT NULL DEFAULT 0,
    avg_eng      REAL NOT NULL DEFAULT 0.0,
    updated_at   REAL NOT NULL,
    PRIMARY KEY(caption_type, niche, platform)
);
"""

CAPTION_TYPES = ["question", "statement", "number", "story", "urgency"]
EXPLORATION   = 1.5


# Caption formula builders per type
def build_caption(
    caption_type: str, title: str, clip_idx: int,
    total_clips: int, channel: str, angle: str
) -> str:
    short = title[:35]
    nxt   = clip_idx + 1
    remaining = total_clips - clip_idx

    formulas = {
        "question": (
            f"😱 Did you see what happened in Part {clip_idx}?\n"
            f"\"{short}\" just took an unexpected turn — comment your reaction below!\n"
            f"💬 What would YOU have done? Tell us!\n"
            f"Follow {channel} — Part {nxt} drops soon! 🔥"
        ),
        "statement": (
            f"🎬 Part {clip_idx} of \"{short}\" just broke the internet.\n"
            f"This scene left everyone speechless — and Part {nxt} is even more intense.\n"
            f"📤 Tag someone who NEEDS to watch this whole series!\n"
            f"Follow {channel} for daily recaps! 🔔"
        ),
        "number": (
            f"🧠 {clip_idx} things you need to know about \"{short}\"\n"
            f"Part {clip_idx} reveals what most people completely miss.\n"
            f"💾 Save this so you can find Part {nxt} easily!\n"
            f"Follow {channel} — {remaining} parts left! 🎯"
        ),
        "story": (
            f"🔍 Nobody talks about this moment in \"{short}\" (Part {clip_idx})\n"
            f"The hidden detail most viewers completely overlooked...\n"
            f"📌 Save + Follow {channel} — the real twist comes in Part {nxt}.\n"
            f"💬 Drop a 🔥 if you caught this the first time!"
        ),
        "urgency": (
            f"⏰ WATCH PART {clip_idx} BEFORE PART {nxt} DROPS!\n"
            f"\"{short}\" — you need this context for what comes next.\n"
            f"Follow {channel} RIGHT NOW — Part {nxt} posts in a few hours!\n"
            f"📤 Share with your watch partner — they'll thank you! 🎬"
        ),
    }
    return formulas.get(caption_type, formulas["story"])


@dataclass
class CaptionSelection:
    caption_type: str
    caption_text: str
    weight: float


class CaptionABTester:
    """UCB1-based caption formula tester."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)
        self._init_weights()
        log.info("[CaptionAB] init db=%s", self.db_path)

    def select_caption(
        self,
        title: str,
        clip_index: int,
        total_clips: int,
        channel: str,
        niche: str = "movie",
        platform: str = "facebook",
        angle: str = "mystery",
    ) -> CaptionSelection:
        """UCB1-select the best caption type and build the caption."""
        weights = self._load_weights(niche, platform)
        total_trials = sum(w["trials"] for w in weights.values())
        best_type = self._ucb1_select(weights, total_trials)

        caption = build_caption(best_type, title, clip_index, total_clips, channel, angle)
        weight  = weights.get(best_type, {}).get("weight", 1.0)

        log.info("[CaptionAB] selected type='%s' weight=%.3f", best_type, weight)
        return CaptionSelection(caption_type=best_type, caption_text=caption, weight=weight)

    def register_upload(
        self, post_id: str, caption_type: str,
        niche: str, platform: str, caption_preview: str
    ):
        with self._conn() as c:
            c.execute("""
                INSERT OR IGNORE INTO caption_tests
                (post_id, caption_type, niche, platform, caption_preview, uploaded_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (post_id, caption_type, niche, platform, caption_preview[:100], time.time()))

    def record_results(
        self, post_id: str, comments: int, shares: int,
        likes: int, reach: int
    ):
        eng = ((comments + shares + likes) / max(1, reach)) * 100
        with self._conn() as c:
            c.execute("""
                UPDATE caption_tests SET comments=?, shares=?, likes=?, reach=?,
                    engagement_rate=?, metrics_pulled=1
                WHERE post_id=?
            """, (comments, shares, likes, reach, eng, post_id))

            row = c.execute(
                "SELECT caption_type, niche, platform FROM caption_tests WHERE post_id=?",
                (post_id,)
            ).fetchone()

        if row:
            self._update_weights(row[0], row[1], row[2])

    def report(self) -> str:
        with self._conn() as c:
            rows = c.execute("""
                SELECT caption_type, niche, platform, wins, trials, avg_eng, weight
                FROM caption_weights ORDER BY niche, weight DESC
            """).fetchall()
        lines = ["=== CAPTION A/B TEST RESULTS ===\n"]
        for r in rows:
            ct, niche, plat, wins, trials, avg_eng, weight = r
            if trials < 1:
                continue
            lines.append(f"  [{ct:<10}] {niche:<12} {plat:<10} "
                         f"wins={wins}/{trials} eng={avg_eng:.2f}% weight={weight:.3f}")
        return "\n".join(lines) if len(lines) > 1 else "No test data yet."

    def _ucb1_select(self, weights: dict, total_trials: int) -> str:
        best_type  = CAPTION_TYPES[0]
        best_score = -1.0
        ln_total   = math.log(max(1, total_trials))
        for ct, w in weights.items():
            if w["trials"] == 0:
                return ct
            score = w["weight"] + EXPLORATION * math.sqrt(ln_total / w["trials"])
            if score > best_score:
                best_score = score
                best_type  = ct
        return best_type

    def _update_weights(self, caption_type: str, niche: str, platform: str):
        with self._conn() as c:
            all_rows = c.execute("""
                SELECT caption_type, AVG(engagement_rate), COUNT(*)
                FROM caption_tests
                WHERE niche=? AND platform=? AND metrics_pulled=1
                GROUP BY caption_type
            """, (niche, platform)).fetchall()

            max_eng = max((r[1] or 0) for r in all_rows) or 1.0
            for ct, avg_eng, cnt in all_rows:
                weight = max(0.1, (avg_eng or 0) / max_eng)
                wins   = c.execute("""
                    SELECT COUNT(*) FROM caption_tests
                    WHERE caption_type=? AND niche=? AND platform=?
                    AND engagement_rate >= (
                        SELECT AVG(engagement_rate) FROM caption_tests
                        WHERE niche=? AND platform=? AND metrics_pulled=1
                    )
                """, (ct, niche, platform, niche, platform)).fetchone()[0]

                c.execute("""
                    UPDATE caption_weights SET weight=?, trials=?, wins=?, avg_eng=?, updated_at=?
                    WHERE caption_type=? AND niche=? AND platform=?
                """, (weight, cnt, wins, avg_eng or 0, time.time(), ct, niche, platform))

    def _load_weights(self, niche: str, platform: str) -> Dict[str, dict]:
        with self._conn() as c:
            rows = c.execute("""
                SELECT caption_type, weight, wins, trials, avg_eng
                FROM caption_weights WHERE niche=? AND platform=?
            """, (niche, platform)).fetchall()
        return {r[0]: {"weight": r[1], "wins": r[2], "trials": r[3], "avg_eng": r[4]}
                for r in rows}

    def _init_weights(self):
        niches    = ["movie", "anime", "kdrama", "horror", "documentary", "general"]
        platforms = ["facebook", "tiktok", "instagram"]
        now = time.time()
        with self._conn() as c:
            for niche in niches:
                for platform in platforms:
                    for ct in CAPTION_TYPES:
                        c.execute("""
                            INSERT OR IGNORE INTO caption_weights
                            (caption_type, niche, platform, weight, wins, trials, avg_eng, updated_at)
                            VALUES (?, ?, ?, 1.0, 0, 0, 0.0, ?)
                        """, (ct, niche, platform, now))

    def _conn(self):
        return sqlite3.connect(self.db_path, timeout=15)
