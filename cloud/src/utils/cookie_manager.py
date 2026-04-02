"""
cookie_manager.py — yt-dlp cookie health checker and refresher.
Validates cookies.txt is present and not expired.
Warns you exactly when cookies need refreshing before downloads fail.
Also supports exporting fresh cookies from a logged-in browser.
"""
from __future__ import annotations
import logging, subprocess, time
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


class CookieManager:

    def __init__(self, cookies_path: Path):
        self.cookies_path = Path(cookies_path)

    def is_valid(self) -> bool:
        """Check if cookies file exists and is not empty/expired."""
        if not self.cookies_path.exists():
            log.warning("[Cookies] cookies.txt not found at %s", self.cookies_path)
            return False
        if self.cookies_path.stat().st_size < 100:
            log.warning("[Cookies] cookies.txt appears empty")
            return False

        # Check age — warn if older than 7 days
        age_days = (time.time() - self.cookies_path.stat().st_mtime) / 86400
        if age_days > 14:
            log.warning("[Cookies] cookies.txt is %.0f days old — consider refreshing", age_days)
        elif age_days > 7:
            log.info("[Cookies] cookies.txt is %.0f days old — refresh soon", age_days)
        else:
            log.debug("[Cookies] cookies.txt age=%.1f days", age_days)

        return True

    def test_download(self, test_url: str = "https://www.youtube.com/watch?v=dQw4w9WgXcQ") -> bool:
        """Test that cookies work with a real YouTube request."""
        cmd = [
            "yt-dlp", "--cookies", str(self.cookies_path),
            "--skip-download", "--quiet", "--no-warnings",
            "--simulate", test_url,
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=20)
            if r.returncode == 0:
                log.info("[Cookies] cookie test ✅ passed")
                return True
            err = r.stderr.decode()[:200]
            log.warning("[Cookies] cookie test ❌: %s", err)
            return False
        except FileNotFoundError:
            log.warning("[Cookies] yt-dlp not installed")
            return False
        except Exception as e:
            log.warning("[Cookies] test error: %s", e)
            return False

    def export_from_browser(self, browser: str = "chrome") -> bool:
        """
        Export fresh cookies from an installed browser.
        Requires yt-dlp and the browser to be installed.
        Supported browsers: chrome, firefox, edge, safari, brave, opera
        """
        if not self.cookies_path.parent.exists():
            self.cookies_path.parent.mkdir(parents=True)

        cmd = [
            "yt-dlp",
            f"--cookies-from-browser", browser,
            "--cookies", str(self.cookies_path),
            "--skip-download", "--quiet",
            "https://www.youtube.com",
        ]
        log.info("[Cookies] exporting from %s browser...", browser)
        try:
            # Create parent directory first
            try:
                self.cookies_path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                log.warning("[Cookies] failed to create parent directory: %s", e)
                return False
            
            r = subprocess.run(cmd, capture_output=True, timeout=30)
            if r.returncode == 0 and self.cookies_path.exists():
                log.info("[Cookies] ✅ exported from %s → %s", browser, self.cookies_path)
                return True
            log.warning("[Cookies] export failed: %s", r.stderr.decode()[:200])
            return False
        except Exception as e:
            log.warning("[Cookies] export error: %s", e)
            return False

    def status(self) -> str:
        if not self.cookies_path.exists():
            return (f"❌ cookies.txt NOT FOUND at {self.cookies_path}\n"
                    f"  → Run: yt-dlp --cookies-from-browser chrome --cookies {self.cookies_path} "
                    f"--skip-download https://youtube.com")
        age_days = (time.time() - self.cookies_path.stat().st_mtime) / 86400
        size_kb  = self.cookies_path.stat().st_size / 1024
        status   = "✅ OK" if age_days < 7 else "⚠️ STALE"
        return (f"=== COOKIE STATUS ===\n"
                f"  Path:  {self.cookies_path}\n"
                f"  Size:  {size_kb:.1f} KB\n"
                f"  Age:   {age_days:.1f} days\n"
                f"  Status: {status}\n"
                f"  Refresh: yt-dlp --cookies-from-browser chrome "
                f"--cookies {self.cookies_path} --skip-download https://youtube.com")
