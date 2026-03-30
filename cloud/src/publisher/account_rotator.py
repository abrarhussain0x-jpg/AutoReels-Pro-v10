"""
account_rotator.py v10.0 — Multi-Account Rotation Engine.

Distributes clips across multiple accounts per platform to avoid
rate limiting and maximize daily upload capacity.

New in v10:
  - Round-robin distribution across configured accounts
  - Per-account daily upload counter in SQLite
  - Auto-rotation when an account hits its daily limit
  - Circuit-breaker per account (auth failures → skip account)
  - Graceful deferral when ALL accounts for a platform are maxed
  - Config: facebook.accounts[] / tiktok.accounts[] etc.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS account_usage (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    platform        TEXT    NOT NULL,
    account_id      TEXT    NOT NULL,
    date            TEXT    NOT NULL,
    uploads         INTEGER NOT NULL DEFAULT 0,
    failures        INTEGER NOT NULL DEFAULT 0,
    last_used       REAL    NOT NULL DEFAULT 0,
    circuit_open    INTEGER NOT NULL DEFAULT 0,
    circuit_until   REAL    NOT NULL DEFAULT 0,
    UNIQUE(platform, account_id, date)
);

CREATE INDEX IF NOT EXISTS idx_usage_platform ON account_usage(platform, date);
"""


@dataclass
class AccountConfig:
    platform: str
    account_id: str
    credentials: dict
    daily_limit: int = 10


@dataclass
class RotationResult:
    account: Optional[AccountConfig]
    reason: str
    all_maxed: bool = False


class AccountRotator:
    """
    Selects the best available account for a given platform upload.
    Tracks daily usage in SQLite and rotates on exhaustion.
    """

    def __init__(self, db_path: Path, config: dict) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._accounts: Dict[str, List[AccountConfig]] = {}
        self._pointers: Dict[str, int] = {}

        with self._conn() as c:
            c.executescript(SCHEMA)

        self._load_config(config)
        log.info("[AccountRotator] loaded platforms: %s",
                 {p: len(accs) for p, accs in self._accounts.items()})

    # ── Public API ──────────────────────────────────────────────────────────

    def get_next_account(self, platform: str) -> RotationResult:
        """Return the next available account for this platform."""
        accounts = self._accounts.get(platform, [])
        if not accounts:
            return RotationResult(None, f"No accounts configured for {platform}", all_maxed=True)

        today = date.today().isoformat()
        start_idx = self._pointers.get(platform, 0)
        n = len(accounts)

        for offset in range(n):
            idx = (start_idx + offset) % n
            acc = accounts[idx]
            usage = self._get_usage(platform, acc.account_id, today)

            if usage["circuit_open"] and time.time() < usage["circuit_until"]:
                log.debug("[Rotator] %s/%s circuit open — skipping", platform, acc.account_id)
                continue

            if usage["uploads"] >= acc.daily_limit:
                log.debug("[Rotator] %s/%s daily limit reached (%d/%d)",
                          platform, acc.account_id, usage["uploads"], acc.daily_limit)
                continue

            # Found a good account — advance pointer
            self._pointers[platform] = (idx + 1) % n
            log.info("[Rotator] selected %s/%s (uploads=%d/%d)",
                     platform, acc.account_id, usage["uploads"], acc.daily_limit)
            return RotationResult(acc, f"Account {acc.account_id} available")

        return RotationResult(
            None,
            f"All {n} accounts for {platform} are maxed or circuit-open today",
            all_maxed=True,
        )

    def record_upload(self, platform: str, account_id: str) -> None:
        """Increment upload count after a successful post."""
        today = date.today().isoformat()
        with self._conn() as c:
            c.execute("""
                INSERT INTO account_usage (platform, account_id, date, uploads, last_used)
                VALUES (?, ?, ?, 1, ?)
                ON CONFLICT(platform, account_id, date) DO UPDATE SET
                    uploads = uploads + 1,
                    last_used = ?
            """, (platform, account_id, today, time.time(), time.time()))
        log.info("[Rotator] recorded upload for %s/%s", platform, account_id)

    def record_failure(self, platform: str, account_id: str, is_auth: bool = False) -> None:
        """Record a failed upload; open circuit on auth failure or 3+ failures."""
        today = date.today().isoformat()
        circuit_until = 0.0
        circuit_open = 0

        usage = self._get_usage(platform, account_id, today)
        new_failures = usage["failures"] + 1

        if is_auth or new_failures >= 3:
            circuit_open = 1
            circuit_until = time.time() + 1800  # 30 min
            log.warning("[Rotator] circuit OPEN for %s/%s (auth=%s failures=%d)",
                        platform, account_id, is_auth, new_failures)

        with self._conn() as c:
            c.execute("""
                INSERT INTO account_usage
                    (platform, account_id, date, failures, circuit_open, circuit_until, last_used)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, account_id, date) DO UPDATE SET
                    failures = failures + 1,
                    circuit_open = ?,
                    circuit_until = CASE WHEN ? > 0 THEN ? ELSE circuit_until END,
                    last_used = ?
            """, (
                platform, account_id, today, 1, circuit_open, circuit_until, time.time(),
                circuit_open, circuit_until, circuit_until, time.time(),
            ))

    def status_report(self) -> str:
        """Return formatted status for --rotate-accounts CLI."""
        today = date.today().isoformat()
        lines = ["=== ACCOUNT ROTATION STATUS ===\n"]
        with self._conn() as c:
            rows = c.execute("""
                SELECT platform, account_id, uploads, failures, circuit_open, circuit_until
                FROM account_usage WHERE date=?
                ORDER BY platform, account_id
            """, (today,)).fetchall()

        if not rows:
            lines.append("  No activity today.")
        for row in rows:
            platform, acc_id, uploads, failures, co, cu = row
            accounts = self._accounts.get(platform, [])
            limit = next(
                (a.daily_limit for a in accounts if a.account_id == acc_id), 10
            )
            circuit = f"OPEN until {int((cu-time.time())/60)}m" if co and time.time() < cu else "OK"
            lines.append(
                f"  {platform:<12} | {acc_id:<20} | uploads={uploads}/{limit} "
                f"| fails={failures} | circuit={circuit}"
            )
        return "\n".join(lines)

    # ── Internal ────────────────────────────────────────────────────────────

    def _load_config(self, config: dict) -> None:
        """Parse accounts from config.yaml structure."""
        platform_keys = {
            "facebook": ("page_id", "access_token"),
            "tiktok":   ("account_id", "access_token"),
            "instagram": ("ig_user_id", "access_token"),
            "youtube_shorts": ("client_id", "refresh_token"),
            "threads":  ("user_id", "access_token"),
        }
        for platform, (id_key, token_key) in platform_keys.items():
            plat_cfg = config.get(platform, {})
            if plat_cfg.get("disabled", True):
                continue

            accounts_list = plat_cfg.get("accounts", [])
            if not accounts_list:
                # Single-account legacy format
                acc_id = plat_cfg.get(id_key, plat_cfg.get("page_id", "default"))
                token = plat_cfg.get(token_key, plat_cfg.get("access_token", ""))
                if acc_id and token:
                    accounts_list = [{id_key: acc_id, token_key: token,
                                      "daily_limit": plat_cfg.get("daily_limit", 10)}]

            parsed = []
            for acc in accounts_list:
                acc_id = acc.get(id_key) or acc.get("page_id") or acc.get("account_id", "default")
                if not acc_id or acc_id.startswith("${"):
                    continue
                parsed.append(AccountConfig(
                    platform=platform,
                    account_id=str(acc_id),
                    credentials=acc,
                    daily_limit=int(acc.get("daily_limit", 10)),
                ))

            if parsed:
                self._accounts[platform] = parsed

    def _get_usage(self, platform: str, account_id: str, today: str) -> dict:
        with self._conn() as c:
            row = c.execute("""
                SELECT uploads, failures, circuit_open, circuit_until
                FROM account_usage WHERE platform=? AND account_id=? AND date=?
            """, (platform, account_id, today)).fetchone()
        if row:
            return {"uploads": row[0], "failures": row[1],
                    "circuit_open": row[2], "circuit_until": row[3]}
        return {"uploads": 0, "failures": 0, "circuit_open": 0, "circuit_until": 0.0}

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=15)
