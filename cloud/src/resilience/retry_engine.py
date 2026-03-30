"""
retry_engine.py v10.0 — Failsafe Retry Architecture.

Wraps every upload call in exponential backoff with per-platform
circuit breakers and a persistent dead letter queue.

New in v10:
  - Exponential backoff: 1s → 2s → 4s → 8s → 16s (max 5 retries)
  - Error type classification: rate_limit | auth_error | server_error | invalid_media
  - Per-platform circuit breaker: 3 consecutive failures → 30-min open
  - Dead letter queue (SQLite: failed.db) — retried on next daemon run
  - auth_error / circuit_open → immediate notifier alert

Usage:
    engine = RetryEngine(db_path, notifier, max_retries=5)
    result = engine.call_with_retry(
        fn=lambda: uploader.upload(clip_path, caption),
        platform="facebook",
        context={"video_id": "...", "clip_num": 1}
    )
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS failed_uploads (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    platform        TEXT    NOT NULL,
    video_id        TEXT    NOT NULL,
    clip_num        INTEGER NOT NULL DEFAULT 1,
    clip_path       TEXT    NOT NULL,
    caption         TEXT    NOT NULL DEFAULT '',
    context_json    TEXT    NOT NULL DEFAULT '{}',
    error_type      TEXT    NOT NULL DEFAULT 'unknown',
    error_message   TEXT    NOT NULL DEFAULT '',
    attempts        INTEGER NOT NULL DEFAULT 1,
    first_failed_at REAL    NOT NULL,
    last_failed_at  REAL    NOT NULL,
    retry_after     REAL    NOT NULL DEFAULT 0,
    resolved        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS circuit_state (
    platform        TEXT    PRIMARY KEY,
    failures        INTEGER NOT NULL DEFAULT 0,
    open            INTEGER NOT NULL DEFAULT 0,
    open_until      REAL    NOT NULL DEFAULT 0,
    last_success    REAL    NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_failed_platform ON failed_uploads(platform, resolved);
CREATE INDEX IF NOT EXISTS idx_failed_retry   ON failed_uploads(retry_after, resolved);
"""

ERROR_TYPES = {
    "rate_limit":    "Rate limited — wait and retry",
    "auth_error":    "Authentication failed — stop and alert",
    "server_error":  "Server error — retry with backoff",
    "invalid_media": "Invalid media — skip this clip",
    "network":       "Network error — retry",
    "unknown":       "Unknown error — retry",
}

# Backoff delays per retry attempt (seconds)
BACKOFF_DELAYS = [1, 2, 4, 8, 16, 32]


@dataclass
class RetryResult:
    success: bool
    return_value: Any = None
    error_type: str = ""
    error_message: str = ""
    attempts: int = 0
    queued_for_retry: bool = False


class RetryEngine:
    """
    Wraps upload functions with retry logic, circuit breakers,
    and dead letter queue for persistent failure handling.
    """

    def __init__(
        self,
        db_path: Path,
        notifier=None,
        max_retries: int = 5,
        base_delay_s: float = 1.0,
        circuit_threshold: int = 3,
        circuit_reset_minutes: int = 30,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.notifier = notifier
        self.max_retries = max_retries
        self.base_delay_s = base_delay_s
        self.circuit_threshold = circuit_threshold
        self.circuit_reset_s = circuit_reset_minutes * 60

        with self._conn() as c:
            c.executescript(SCHEMA)
        log.info("[RetryEngine] init max_retries=%d circuit_threshold=%d reset=%dmin",
                 max_retries, circuit_threshold, circuit_reset_minutes)

    # ── Public API ──────────────────────────────────────────────────────────

    def call_with_retry(
        self,
        fn: Callable,
        platform: str,
        clip_path: str = "",
        caption: str = "",
        context: Optional[dict] = None,
    ) -> RetryResult:
        """
        Call fn() with exponential backoff retry.
        Returns RetryResult with success status and return value.
        """
        ctx = context or {}

        # Check circuit breaker
        if self._is_circuit_open(platform):
            log.warning("[RetryEngine] circuit OPEN for %s — skipping", platform)
            self._queue_for_dlq(platform, clip_path, caption, ctx,
                                "circuit_open", "Circuit breaker is open")
            return RetryResult(success=False, error_type="circuit_open",
                               error_message="Circuit open", queued_for_retry=True)

        last_error = ""
        last_error_type = "unknown"

        for attempt in range(self.max_retries + 1):
            try:
                result = fn()
                self._record_success(platform)
                return RetryResult(success=True, return_value=result, attempts=attempt + 1)

            except Exception as exc:
                error_str = str(exc)
                error_type = self._classify_error(error_str)
                last_error = error_str
                last_error_type = error_type

                log.warning("[RetryEngine] %s attempt %d/%d failed (%s): %s",
                            platform, attempt + 1, self.max_retries + 1,
                            error_type, error_str[:100])

                self._record_failure(platform)

                # Auth error: stop immediately, alert
                if error_type == "auth_error":
                    msg = f"🔴 AUTH ERROR on {platform}: {error_str[:200]}"
                    self._notify(msg)
                    self._queue_for_dlq(platform, clip_path, caption, ctx,
                                        error_type, error_str)
                    return RetryResult(success=False, error_type=error_type,
                                       error_message=error_str, attempts=attempt + 1,
                                       queued_for_retry=True)

                # Invalid media: skip, don't retry
                if error_type == "invalid_media":
                    log.error("[RetryEngine] invalid media — skip: %s", error_str)
                    return RetryResult(success=False, error_type=error_type,
                                       error_message=error_str, attempts=attempt + 1)

                # Circuit opened during attempts
                if self._is_circuit_open(platform):
                    msg = f"⚠️ Circuit OPENED for {platform} after {attempt+1} failures"
                    self._notify(msg)
                    self._queue_for_dlq(platform, clip_path, caption, ctx,
                                        error_type, error_str)
                    return RetryResult(success=False, error_type="circuit_open",
                                       error_message=error_str, attempts=attempt + 1,
                                       queued_for_retry=True)

                # Wait before next attempt
                if attempt < self.max_retries:
                    delay = self._backoff_delay(attempt, error_type)
                    log.info("[RetryEngine] waiting %.0fs before retry %d...", delay, attempt + 2)
                    time.sleep(delay)

        # All retries exhausted → DLQ
        self._queue_for_dlq(platform, clip_path, caption, ctx,
                            last_error_type, last_error)
        log.error("[RetryEngine] all retries exhausted for %s — queued to DLQ", platform)
        return RetryResult(success=False, error_type=last_error_type,
                           error_message=last_error, attempts=self.max_retries + 1,
                           queued_for_retry=True)

    def retry_dead_letter_queue(self, fn_map: Dict[str, Callable]) -> int:
        """
        Retry items in the dead letter queue.
        fn_map: {platform: upload_fn(clip_path, caption, context) -> any}
        Returns number of successful retries.
        """
        now = time.time()
        succeeded = 0

        with self._conn() as c:
            rows = c.execute("""
                SELECT id, platform, clip_path, caption, context_json, attempts
                FROM failed_uploads
                WHERE resolved=0 AND retry_after <= ? AND error_type NOT IN ('auth_error', 'invalid_media')
                ORDER BY first_failed_at
                LIMIT 20
            """, (now,)).fetchall()

        for row in rows:
            fid, platform, clip_path, caption, ctx_json, attempts = row
            if platform not in fn_map:
                continue
            try:
                ctx = json.loads(ctx_json)
            except Exception:
                ctx = {}

            fn = fn_map[platform]
            result = self.call_with_retry(
                lambda: fn(clip_path, caption, ctx),
                platform=platform,
                clip_path=clip_path,
                caption=caption,
                context=ctx,
            )
            if result.success:
                with self._conn() as c:
                    c.execute("UPDATE failed_uploads SET resolved=1 WHERE id=?", (fid,))
                succeeded += 1
                log.info("[RetryEngine] DLQ item %d resolved for %s", fid, platform)
            else:
                with self._conn() as c:
                    c.execute("""
                        UPDATE failed_uploads SET attempts=attempts+1, last_failed_at=?,
                        retry_after=? WHERE id=?
                    """, (now, now + min(3600, 2 ** attempts * 60), fid))

        log.info("[RetryEngine] DLQ sweep: %d/%d resolved", succeeded, len(rows))
        return succeeded

    def dlq_report(self) -> str:
        """Report for --retry-failed CLI."""
        with self._conn() as c:
            rows = c.execute("""
                SELECT platform, video_id, clip_num, error_type, error_message,
                       attempts, first_failed_at, resolved
                FROM failed_uploads ORDER BY first_failed_at DESC LIMIT 30
            """).fetchall()

        lines = ["=== DEAD LETTER QUEUE ===\n"]
        if not rows:
            lines.append("  Queue is empty. 🎉")
        for r in rows:
            platform, vid, clip, etype, emsg, attempts, failed_at, resolved = r
            age_h = (time.time() - failed_at) / 3600
            status = "✅ resolved" if resolved else f"❌ {etype} ({attempts} attempts)"
            lines.append(
                f"  {platform:<12} | {vid[:20]:<20} clip={clip} "
                f"| {status} | age={age_h:.0f}h | {emsg[:50]}"
            )
        return "\n".join(lines)

    # ── Circuit Breaker ────────────────────────────────────────────────────

    def _is_circuit_open(self, platform: str) -> bool:
        with self._conn() as c:
            row = c.execute(
                "SELECT open, open_until FROM circuit_state WHERE platform=?",
                (platform,)
            ).fetchone()
        if not row:
            return False
        is_open, until = row
        if is_open and time.time() < until:
            return True
        if is_open and time.time() >= until:
            # Auto-reset
            with self._conn() as c:
                c.execute(
                    "UPDATE circuit_state SET open=0, failures=0 WHERE platform=?",
                    (platform,)
                )
        return False

    def _record_failure(self, platform: str) -> None:
        with self._conn() as c:
            c.execute("""
                INSERT INTO circuit_state (platform, failures, open, open_until, last_success)
                VALUES (?, 1, 0, 0, 0)
                ON CONFLICT(platform) DO UPDATE SET failures = failures + 1
            """, (platform,))
            failures = c.execute(
                "SELECT failures FROM circuit_state WHERE platform=?", (platform,)
            ).fetchone()[0]
            if failures >= self.circuit_threshold:
                c.execute("""
                    UPDATE circuit_state SET open=1, open_until=? WHERE platform=?
                """, (time.time() + self.circuit_reset_s, platform))
                log.warning("[RetryEngine] circuit OPENED for %s (%d failures)", platform, failures)

    def _record_success(self, platform: str) -> None:
        with self._conn() as c:
            c.execute("""
                INSERT INTO circuit_state (platform, failures, open, open_until, last_success)
                VALUES (?, 0, 0, 0, ?)
                ON CONFLICT(platform) DO UPDATE SET failures=0, open=0, last_success=?
            """, (platform, time.time(), time.time()))

    # ── Error Classification ───────────────────────────────────────────────

    @staticmethod
    def _classify_error(error_str: str) -> str:
        e = error_str.lower()
        if any(k in e for k in ["401", "403", "invalid token", "oauth", "access denied", "unauthorized"]):
            return "auth_error"
        if any(k in e for k in ["429", "rate limit", "too many requests", "quota"]):
            return "rate_limit"
        if any(k in e for k in ["invalid video", "unsupported format", "corrupt", "invalid media"]):
            return "invalid_media"
        if any(k in e for k in ["500", "502", "503", "504", "server error", "internal error"]):
            return "server_error"
        if any(k in e for k in ["timeout", "connection", "network", "unreachable"]):
            return "network"
        return "unknown"

    @staticmethod
    def _backoff_delay(attempt: int, error_type: str) -> float:
        base = BACKOFF_DELAYS[min(attempt, len(BACKOFF_DELAYS) - 1)]
        if error_type == "rate_limit":
            return base * 3  # longer wait on rate limit
        return float(base)

    # ── DLQ ───────────────────────────────────────────────────────────────

    def _queue_for_dlq(
        self,
        platform: str,
        clip_path: str,
        caption: str,
        context: dict,
        error_type: str,
        error_message: str,
    ) -> None:
        now = time.time()
        retry_after = now + 300  # retry in 5 min by default
        with self._conn() as c:
            c.execute("""
                INSERT INTO failed_uploads
                (platform, video_id, clip_num, clip_path, caption, context_json,
                 error_type, error_message, attempts, first_failed_at, last_failed_at, retry_after)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
            """, (
                platform,
                context.get("video_id", "unknown"),
                context.get("clip_num", 1),
                clip_path,
                caption[:1000],
                json.dumps(context),
                error_type,
                error_message[:500],
                now, now, retry_after,
            ))

    def _notify(self, message: str) -> None:
        if self.notifier:
            try:
                self.notifier.send(message)
            except Exception as exc:
                log.debug("[RetryEngine] notifier failed: %s", exc)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=15)
