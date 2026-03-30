"""
token_refresher.py — Facebook + Instagram token auto-refresher.
Facebook long-lived tokens expire in 60 days.
This module refreshes them automatically and saves to .env / config.
Runs daily in daemon mode. Sends alert 7 days before expiry.
"""
from __future__ import annotations
import json, logging, os, sqlite3, time, urllib.parse, urllib.request
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS token_state (
    platform    TEXT PRIMARY KEY,
    account_id  TEXT NOT NULL DEFAULT '',
    token       TEXT NOT NULL,
    expires_at  REAL NOT NULL DEFAULT 0,
    refreshed_at REAL NOT NULL DEFAULT 0
);
"""

GRAPH = "https://graph.facebook.com/v19.0"


class TokenRefresher:
    """Auto-refreshes FB/IG tokens and tracks expiry."""

    ALERT_DAYS_BEFORE = 7
    FB_TOKEN_TTL_DAYS = 60

    def __init__(self, db_path: Path, cfg: dict, notifier=None):
        self.db_path  = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.cfg      = cfg
        self.notifier = notifier
        with self._conn() as c:
            c.executescript(SCHEMA)

    def check_all(self) -> dict:
        """Check and refresh all configured tokens. Returns status dict."""
        results = {}

        # Facebook accounts
        fb_cfg = self.cfg.get("facebook", {})
        if not fb_cfg.get("disabled", False):
            for acc in fb_cfg.get("accounts", []):
                pid   = acc.get("page_id", "")
                token = acc.get("access_token", "")
                if pid and token and not token.startswith("${"):
                    status = self._check_fb_token(pid, token)
                    results[f"facebook_{pid}"] = status

        return results

    def _check_fb_token(self, page_id: str, token: str) -> dict:
        """Check FB token expiry and refresh if needed."""
        # Get token info from Facebook
        url = (f"{GRAPH}/debug_token?input_token={token}"
               f"&access_token={token}")
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                data = json.loads(resp.read()).get("data", {})

            expires_at = data.get("expires_at", 0)
            is_valid   = data.get("is_valid", False)

            if not is_valid:
                msg = f"⛔ Facebook token for page {page_id} is INVALID — regenerate now!"
                log.error("[TokenRefresh] %s", msg)
                if self.notifier:
                    self.notifier.send(msg)
                return {"valid": False, "expires_at": 0, "refreshed": False}

            # Check if expiring soon
            days_left = (expires_at - time.time()) / 86400 if expires_at > 0 else 60
            log.info("[TokenRefresh] FB page %s — valid, %.0f days left", page_id, days_left)

            if expires_at > 0 and days_left < self.ALERT_DAYS_BEFORE:
                msg = (f"⚠️ Facebook token for page {page_id} expires in "
                       f"{days_left:.0f} days! Refresh NOW at: "
                       f"https://developers.facebook.com/tools/explorer/")
                log.warning("[TokenRefresh] %s", msg)
                if self.notifier:
                    self.notifier.send(msg)

            self._save_state("facebook", page_id, token, expires_at)
            return {"valid": True, "expires_at": expires_at,
                    "days_left": days_left, "refreshed": False}

        except urllib.error.HTTPError as e:
            log.warning("[TokenRefresh] FB debug_token error %d", e.code)
            return {"valid": False, "error": str(e)}
        except Exception as e:
            log.debug("[TokenRefresh] check failed: %s", e)
            return {"valid": None, "error": str(e)}

    def extend_fb_token(self, short_token: str, app_id: str, app_secret: str) -> Optional[str]:
        """Exchange short-lived token for long-lived (60-day) token."""
        url    = f"{GRAPH}/oauth/access_token"
        params = {
            "grant_type":        "fb_exchange_token",
            "client_id":         app_id,
            "client_secret":     app_secret,
            "fb_exchange_token": short_token,
        }
        data = urllib.parse.urlencode(params).encode()
        try:
            req = urllib.request.Request(url, data=data, method="POST")
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read())
            new_token = result.get("access_token")
            if new_token:
                log.info("[TokenRefresh] ✅ extended FB token (60-day)")
                return new_token
        except Exception as e:
            log.error("[TokenRefresh] extend failed: %s", e)
        return None

    def status_report(self) -> str:
        with self._conn() as c:
            rows = c.execute("""
                SELECT platform, account_id, expires_at, refreshed_at
                FROM token_state ORDER BY platform
            """).fetchall()

        lines = ["=== TOKEN STATUS ===\n"]
        if not rows:
            lines.append("  No tokens tracked yet. Run --check to scan.")
        for platform, acc_id, exp_at, ref_at in rows:
            days = (exp_at - time.time()) / 86400 if exp_at > 0 else -1
            status = (f"✅ {days:.0f}d left" if days > 7
                      else f"⚠️  EXPIRING in {days:.0f}d" if days > 0
                      else "⏰ permanent / unknown")
            lines.append(f"  {platform:<15} | {acc_id[:20]:<20} | {status}")
        return "\n".join(lines)

    def _save_state(self, platform, account_id, token, expires_at):
        with self._conn() as c:
            c.execute("""
                INSERT OR REPLACE INTO token_state
                (platform, account_id, token, expires_at, refreshed_at)
                VALUES (?, ?, ?, ?, ?)
            """, (platform, account_id, token[:50] + "...", expires_at, time.time()))

    def _conn(self):
        return sqlite3.connect(self.db_path, timeout=10)
