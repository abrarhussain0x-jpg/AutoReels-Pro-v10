"""
hook_optimizer.py v10.0 — Viral Hook Intelligence Engine.

Learns which specific hook PHRASES drive the highest 3-second retention
per platform × niche × angle. Uses UCB1 (same as ab_engine) but for
individual hook text strings, not just angles.

New in v10:
  - HookLibrary: SQLite table tracking phrase-level performance
  - UCB1 selection: balances exploration vs exploitation per context
  - Claude integration: generate candidate hooks when library is sparse
  - Auto-retrains from real engagement after every --pull-metrics run
  - get_best_hook(platform, niche, angle) → winning phrase

Architecture:
  HookOptimizer
    ├── HookLibrary (SQLite: hooks.db)
    ├── UCB1Selector
    └── HookGenerator (Claude fallback)
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS hooks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    phrase          TEXT    NOT NULL,
    platform        TEXT    NOT NULL,
    niche           TEXT    NOT NULL,
    angle           TEXT    NOT NULL,
    uses            INTEGER NOT NULL DEFAULT 0,
    wins            INTEGER NOT NULL DEFAULT 0,
    total_views     INTEGER NOT NULL DEFAULT 0,
    total_likes     INTEGER NOT NULL DEFAULT 0,
    avg_retention   REAL    NOT NULL DEFAULT 0.0,
    weight          REAL    NOT NULL DEFAULT 1.0,
    created_at      REAL    NOT NULL,
    updated_at      REAL    NOT NULL,
    UNIQUE(phrase, platform, niche, angle)
);

CREATE INDEX IF NOT EXISTS idx_hooks_ctx ON hooks(platform, niche, angle);
CREATE INDEX IF NOT EXISTS idx_hooks_weight ON hooks(weight DESC);
"""

# Seed hooks per angle — used when library is empty (no data yet)
SEED_HOOKS: Dict[str, List[str]] = {
    "mystery":       ["NOBODY TALKS ABOUT THIS", "THE REAL STORY", "WHAT THEY HID", "YOU WON'T BELIEVE", "THE SECRET ENDING"],
    "shocking":      ["THE TWIST IS INSANE", "WAIT FOR IT", "NOBODY SAW THIS COMING", "PLOT TWIST ALERT", "THIS CHANGES EVERYTHING"],
    "emotional":     ["THIS HIT DIFFERENT", "I WASN'T READY", "GRAB TISSUES", "MOST EMOTIONAL SCENE", "BROKE EVERYONE"],
    "educational":   ["WHAT THEY DON'T TELL YOU", "THE REAL MEANING", "HIDDEN DETAILS", "MOST MISS THIS", "DIRECTOR'S SECRET"],
    "controversial": ["HOT TAKE", "UNPOPULAR OPINION", "THEY LIED TO US", "MOST DISAGREE", "CONTROVERSIAL TRUTH"],
    "motivational":  ["WATCH IF STUCK", "LIFE CHANGING", "THIS HITS HARD", "NEVER GIVE UP", "REAL TALK"],
}


@dataclass
class HookResult:
    phrase: str
    angle: str
    platform: str
    niche: str
    weight: float
    from_library: bool = True
    from_claude: bool = False


class HookOptimizer:
    """
    Selects and learns the best hook phrases per (platform, niche, angle).
    Uses UCB1 to balance exploration of new hooks vs exploitation of proven ones.
    """

    EXPLORATION_FACTOR = 1.5
    MIN_TRIALS_FOR_CONFIDENCE = 10
    ENDPOINT = "https://api.anthropic.com/v1/messages"

    def __init__(
        self,
        db_path: Path,
        api_key: str = "",
        niche: str = "movie",
        enabled: bool = True,
        exploration_factor: float = 1.5,
        min_trials: int = 10,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.api_key = api_key
        self.niche = niche
        self.enabled = enabled
        self.EXPLORATION_FACTOR = exploration_factor
        self.MIN_TRIALS_FOR_CONFIDENCE = min_trials

        with self._conn() as c:
            c.executescript(SCHEMA)
        self._seed_library()
        log.info("[HookOptimizer] init db=%s enabled=%s", self.db_path, enabled)

    # ── Public API ──────────────────────────────────────────────────────────

    def get_best_hook(self, platform: str, niche: str, angle: str) -> HookResult:
        """Return the UCB1-optimal hook phrase for this context."""
        if not self.enabled:
            phrase = SEED_HOOKS.get(angle, ["WATCH THIS"])[0]
            return HookResult(phrase=phrase, angle=angle, platform=platform,
                              niche=niche, weight=1.0, from_library=False)

        hooks = self._load_hooks(platform, niche, angle)
        if not hooks:
            self._seed_context(platform, niche, angle)
            hooks = self._load_hooks(platform, niche, angle)

        total_uses = sum(h["uses"] for h in hooks)
        best = self._ucb1_select(hooks, total_uses)

        log.debug("[HookOptimizer] selected '%s' for %s/%s/%s (weight=%.3f)",
                  best["phrase"], platform, niche, angle, best["weight"])
        return HookResult(
            phrase=best["phrase"].upper()[:30],
            angle=angle, platform=platform, niche=niche,
            weight=best["weight"], from_library=True,
        )

    def record_result(
        self,
        phrase: str,
        platform: str,
        niche: str,
        angle: str,
        views: int,
        likes: int,
        retention_rate: float,
    ) -> None:
        """Update hook performance after metrics pull."""
        engagement = (likes / max(1, views)) * 100
        is_win = retention_rate > 0.5 or engagement > 3.0

        with self._conn() as c:
            c.execute("""
                INSERT INTO hooks (phrase, platform, niche, angle, uses, wins,
                    total_views, total_likes, avg_retention, weight, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, 1.0, ?, ?)
                ON CONFLICT(phrase, platform, niche, angle) DO UPDATE SET
                    uses = uses + 1,
                    wins = wins + ?,
                    total_views = total_views + ?,
                    total_likes = total_likes + ?,
                    avg_retention = (avg_retention * uses + ?) / (uses + 1),
                    updated_at = ?
            """, (
                phrase, platform, niche, angle,
                1 if is_win else 0, views, likes, retention_rate, 1.0,
                time.time(), time.time(),
                1 if is_win else 0, views, likes, retention_rate, time.time(),
            ))
        self._recompute_weights(platform, niche, angle)
        log.info("[HookOptimizer] recorded '%s' views=%d likes=%d ret=%.2f win=%s",
                 phrase, views, likes, retention_rate, is_win)

    def generate_hooks_with_claude(
        self, platform: str, niche: str, angle: str, n: int = 5
    ) -> List[str]:
        """Ask Claude to generate fresh hook candidates for sparse library slots."""
        if not self.api_key:
            return SEED_HOOKS.get(angle, ["WATCH THIS"])[:n]

        prompt = (
            f"You are a viral short-form video expert specialising in {niche} content on {platform}.\n"
            f"Generate {n} unique ALL-CAPS hook phrases for the '{angle}' angle.\n"
            f"Rules: max 28 chars each, punchy, creates curiosity, no punctuation except apostrophes.\n"
            f"Respond ONLY with a JSON array of {n} strings. No preamble."
        )
        try:
            body = json.dumps({
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 200,
                "messages": [{"role": "user", "content": prompt}],
            }).encode()
            req = urllib.request.Request(
                self.ENDPOINT, data=body,
                headers={"Content-Type": "application/json",
                         "x-api-key": self.api_key,
                         "anthropic-version": "2023-06-01"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read())
            text = data["content"][0]["text"].strip()
            if text.startswith("```"):
                text = "\n".join(text.split("\n")[1:]).rstrip("```").strip()
            hooks = json.loads(text)
            result = [str(h).upper()[:28] for h in hooks if h][:n]
            log.info("[HookOptimizer] Claude generated %d hooks for %s/%s/%s", len(result), platform, niche, angle)
            return result
        except Exception as exc:
            log.warning("[HookOptimizer] Claude hook gen failed: %s", exc)
            return SEED_HOOKS.get(angle, ["WATCH THIS"])[:n]

    def report(self) -> str:
        """Return leaderboard text for --hook-report CLI."""
        lines = ["=== HOOK PHRASE LEADERBOARD ===\n"]
        with self._conn() as c:
            rows = c.execute("""
                SELECT phrase, platform, niche, angle, uses, wins,
                       avg_retention, weight
                FROM hooks
                WHERE uses > 0
                ORDER BY weight DESC
                LIMIT 30
            """).fetchall()
        if not rows:
            return "No hook data yet. Run after your first --pull-metrics."
        for r in rows:
            phrase, platform, niche, angle, uses, wins, ret, weight = r
            lines.append(
                f"  {phrase:<32} | {platform:<12} | {angle:<15} | "
                f"weight={weight:.3f} | wins={wins}/{uses} | ret={ret:.1%}"
            )
        return "\n".join(lines)

    # ── Internal ────────────────────────────────────────────────────────────

    def _ucb1_select(self, hooks: List[dict], total_uses: int) -> dict:
        """UCB1 algorithm: score = avg_reward + C * sqrt(ln(N) / n_i)."""
        best_hook = hooks[0]
        best_score = -1.0
        ln_total = math.log(max(1, total_uses))

        for h in hooks:
            if h["uses"] == 0:
                return h  # Always explore untriedNodes first
            exploitation = h["weight"]
            exploration = self.EXPLORATION_FACTOR * math.sqrt(ln_total / h["uses"])
            score = exploitation + exploration
            if score > best_score:
                best_score = score
                best_hook = h
        return best_hook

    def _recompute_weights(self, platform: str, niche: str, angle: str) -> None:
        with self._conn() as c:
            hooks = c.execute("""
                SELECT id, wins, uses, avg_retention FROM hooks
                WHERE platform=? AND niche=? AND angle=? AND uses > 0
            """, (platform, niche, angle)).fetchall()

            if not hooks:
                return

            max_score = max((r[1] / r[2]) * (1 + r[3]) for r in hooks) or 1.0
            for row in hooks:
                hid, wins, uses, ret = row
                score = (wins / uses) * (1 + ret)
                weight = max(0.1, score / max_score)
                c.execute("UPDATE hooks SET weight=?, updated_at=? WHERE id=?",
                          (weight, time.time(), hid))

    def _load_hooks(self, platform: str, niche: str, angle: str) -> List[dict]:
        with self._conn() as c:
            rows = c.execute("""
                SELECT phrase, uses, wins, avg_retention, weight
                FROM hooks WHERE platform=? AND niche=? AND angle=?
                ORDER BY weight DESC
            """, (platform, niche, angle)).fetchall()
        return [{"phrase": r[0], "uses": r[1], "wins": r[2],
                 "avg_retention": r[3], "weight": r[4]} for r in rows]

    def _seed_library(self) -> None:
        """Populate DB with seed hooks if empty."""
        with self._conn() as c:
            count = c.execute("SELECT COUNT(*) FROM hooks").fetchone()[0]
        if count > 0:
            return

        now = time.time()
        platforms = ["facebook", "tiktok", "instagram", "youtube", "threads"]
        niches = ["movie", "anime", "kdrama", "horror", "documentary"]

        with self._conn() as c:
            for angle, phrases in SEED_HOOKS.items():
                for phrase in phrases:
                    for platform in platforms:
                        for niche in niches:
                            try:
                                c.execute("""
                                    INSERT OR IGNORE INTO hooks
                                    (phrase, platform, niche, angle, uses, wins,
                                     total_views, total_likes, avg_retention, weight,
                                     created_at, updated_at)
                                    VALUES (?, ?, ?, ?, 0, 0, 0, 0, 0.0, 1.0, ?, ?)
                                """, (phrase, platform, niche, angle, now, now))
                            except Exception:
                                pass
        log.info("[HookOptimizer] seeded library with default hooks")

    def _seed_context(self, platform: str, niche: str, angle: str) -> None:
        """Add seed hooks for a specific context if missing."""
        phrases = SEED_HOOKS.get(angle, ["WATCH THIS"])
        now = time.time()
        with self._conn() as c:
            for phrase in phrases:
                c.execute("""
                    INSERT OR IGNORE INTO hooks
                    (phrase, platform, niche, angle, uses, wins,
                     total_views, total_likes, avg_retention, weight, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 0, 0, 0, 0, 0.0, 1.0, ?, ?)
                """, (phrase, platform, niche, angle, now, now))

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=15)
