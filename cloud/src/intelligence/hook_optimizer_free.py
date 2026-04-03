"""
hook_optimizer_free.py v10.0 FREE — No API hook selection.

Selects hooks from the built-in library using UCB1 on stored performance data.
Generates new hooks from templates when library is sparse.
Zero API calls needed.
"""

from __future__ import annotations

import logging
import math
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

# Same SCHEMA + SEED_HOOKS as hook_optimizer.py
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
    avg_retention   REAL    NOT NULL DEFAULT 0.0,
    weight          REAL    NOT NULL DEFAULT 1.0,
    created_at      REAL    NOT NULL,
    updated_at      REAL    NOT NULL,
    UNIQUE(phrase, platform, niche, angle)
);
CREATE INDEX IF NOT EXISTS idx_hooks_ctx ON hooks(platform, niche, angle);
"""

SEED_HOOKS: Dict[str, List[str]] = {
    "mystery":       ["NOBODY TALKS ABOUT THIS", "THE REAL STORY", "WHAT THEY HID",
                      "THIS WAS DELETED", "THE TRUTH FINALLY"],
    "shocking":      ["THE TWIST IS INSANE", "WAIT FOR IT", "NOBODY SAW THIS COMING",
                      "PLOT TWIST ALERT", "THIS CHANGES EVERYTHING"],
    "emotional":     ["THIS HIT DIFFERENT", "I WASN'T READY", "GRAB TISSUES",
                      "MOST EMOTIONAL SCENE", "BROKE EVERYONE"],
    "educational":   ["WHAT THEY DON'T TELL YOU", "THE REAL MEANING", "HIDDEN DETAILS",
                      "MOST MISS THIS", "DIRECTOR'S SECRET"],
    "controversial": ["HOT TAKE", "UNPOPULAR OPINION", "THEY LIED TO US",
                      "MOST DISAGREE", "CONTROVERSIAL TRUTH"],
    "motivational":  ["WATCH IF STUCK", "LIFE CHANGING", "THIS HITS HARD",
                      "NEVER GIVE UP", "REAL TALK"],
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


class HookOptimizerFree:
    """UCB1 hook optimizer — learns from real data, generates from templates."""

    EXPLORATION_FACTOR = 1.5

    def __init__(
        self,
        db_path: Path,
        api_key: str = "",      # ignored
        niche: str = "movie",
        enabled: bool = True,
        exploration_factor: float = 1.5,
        min_trials: int = 10,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.niche = niche
        self.enabled = enabled
        self.EXPLORATION_FACTOR = exploration_factor

        with self._conn() as c:
            c.executescript(SCHEMA)
        self._seed_library()
        log.info("[HookOptimizerFree] init db=%s", self.db_path)

    def get_best_hook(self, platform: str, niche: str, angle: str) -> HookResult:
        hooks = self._load_hooks(platform, niche, angle)
        if not hooks:
            self._seed_context(platform, niche, angle)
            hooks = self._load_hooks(platform, niche, angle)

        total_uses = sum(h["uses"] for h in hooks)
        best = self._ucb1_select(hooks, total_uses)
        return HookResult(
            phrase=best["phrase"].upper()[:30],
            angle=angle, platform=platform, niche=niche,
            weight=best["weight"], from_library=True,
        )

    def record_result(self, phrase, platform, niche, angle, views, likes, retention_rate):
        is_win = retention_rate > 0.5 or (likes / max(1, views)) * 100 > 3.0
        with self._conn() as c:
            c.execute("""
                INSERT INTO hooks (phrase, platform, niche, angle, uses, wins,
                    total_views, avg_retention, weight, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, ?, ?, 1.0, ?, ?)
                ON CONFLICT(phrase, platform, niche, angle) DO UPDATE SET
                    uses = uses + 1, wins = wins + ?,
                    total_views = total_views + ?,
                    avg_retention = (avg_retention * uses + ?) / (uses + 1),
                    updated_at = ?
            """, (phrase, platform, niche, angle, 1 if is_win else 0, views,
                  retention_rate, time.time(), time.time(),
                  1 if is_win else 0, views, retention_rate, time.time()))

    def get_top_hooks(self, limit: int = 20) -> List[dict]:
        with self._conn() as c:
            rows = c.execute("""
                SELECT phrase, platform, niche, angle, uses, wins, avg_retention, weight
                FROM hooks WHERE uses > 0 ORDER BY weight DESC LIMIT ?
            """, (limit,)).fetchall()
        return [{"phrase": r[0], "platform": r[1], "niche": r[2], "angle": r[3],
                 "uses": r[4], "wins": r[5], "avg_retention": r[6], "weight": r[7]}
                for r in rows]

    def report(self) -> str:
        rows = self.get_top_hooks(30)
        if not rows:
            return "No hook data yet. Hooks will be tracked after first upload."
        lines = ["=== HOOK PHRASE LEADERBOARD ===\n"]
        for r in rows:
            lines.append(
                f"  {r['phrase']:<32} | {r['platform']:<12} | {r['angle']:<15} | "
                f"weight={r['weight']:.3f} | wins={r['wins']}/{r['uses']}"
            )
        return "\n".join(lines)

    def _ucb1_select(self, hooks, total_uses):
        best = hooks[0]
        best_score = -1.0
        ln_total = math.log(max(1, total_uses))
        for h in hooks:
            if h["uses"] == 0:
                return h
            score = h["weight"] + self.EXPLORATION_FACTOR * math.sqrt(ln_total / h["uses"])
            if score > best_score:
                best_score = score
                best = h
        return best

    def _load_hooks(self, platform, niche, angle):
        with self._conn() as c:
            rows = c.execute("""
                SELECT phrase, uses, wins, avg_retention, weight FROM hooks
                WHERE platform=? AND niche=? AND angle=? ORDER BY weight DESC
            """, (platform, niche, angle)).fetchall()
        return [{"phrase": r[0], "uses": r[1], "wins": r[2],
                 "avg_retention": r[3], "weight": r[4]} for r in rows]

    def _seed_library(self):
        with self._conn() as c:
            count = c.execute("SELECT COUNT(*) FROM hooks").fetchone()[0]
        if count > 0:
            return
        now = time.time()
        platforms = ["facebook", "tiktok", "instagram", "youtube", "threads"]
        niches = ["movie", "anime", "kdrama", "horror", "documentary", "general"]
        with self._conn() as c:
            for angle, phrases in SEED_HOOKS.items():
                for phrase in phrases:
                    for platform in platforms:
                        for niche in niches:
                            try:
                                c.execute("""
                                    INSERT OR IGNORE INTO hooks
                                    (phrase, platform, niche, angle, uses, wins,
                                     total_views, avg_retention, weight, created_at, updated_at)
                                    VALUES (?, ?, ?, ?, 0, 0, 0, 0.0, 1.0, ?, ?)
                                """, (phrase, platform, niche, angle, now, now))
                            except Exception:
                                pass

    def _seed_context(self, platform, niche, angle):
        phrases = SEED_HOOKS.get(angle, ["WATCH THIS"])
        now = time.time()
        with self._conn() as c:
            for phrase in phrases:
                c.execute("""
                    INSERT OR IGNORE INTO hooks
                    (phrase, platform, niche, angle, uses, wins,
                     total_views, avg_retention, weight, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 0, 0, 0, 0.0, 1.0, ?, ?)
                """, (phrase, platform, niche, angle, now, now))

    def _conn(self):
        return sqlite3.connect(self.db_path, timeout=15)


HookOptimizer = HookOptimizerFree
