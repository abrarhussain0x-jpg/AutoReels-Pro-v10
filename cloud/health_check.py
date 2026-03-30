"""
health_check.py — Pre-flight system health checker.
Validates everything before the pipeline runs:
  ffmpeg, yt-dlp, disk space, Facebook token, config, Python version.
Exits with clear error messages instead of cryptic failures mid-run.
"""
from __future__ import annotations
import json, logging, os, shutil, subprocess, sys, urllib.request
from pathlib import Path

log = logging.getLogger(__name__)


class HealthCheck:

    def __init__(self, cfg: dict, queue_dir: Path):
        self.cfg       = cfg
        self.queue_dir = Path(queue_dir)
        self.errors    = []
        self.warnings  = []
        self.passed    = []

    def run_all(self, raise_on_error: bool = False) -> bool:
        """Run all checks. Returns True if no critical errors."""
        self._check_python()
        self._check_ffmpeg()
        self._check_ytdlp()
        self._check_disk_space()
        self._check_queue_dir()
        self._check_facebook_token()
        self._check_config()

        print("\n=== HEALTH CHECK RESULTS ===\n")
        for msg in self.passed:
            print(f"  ✅ {msg}")
        for msg in self.warnings:
            print(f"  ⚠️  {msg}")
        for msg in self.errors:
            print(f"  ❌ {msg}")

        ok = len(self.errors) == 0
        print(f"\n{'✅ ALL CHECKS PASSED — ready to run!' if ok else '❌ FIX ERRORS ABOVE before running'}\n")

        if not ok and raise_on_error:
            raise RuntimeError(f"{len(self.errors)} health check(s) failed")
        return ok

    # ── Checks ────────────────────────────────────────────────────────────────

    def _check_python(self):
        v = sys.version_info
        if v >= (3, 9):
            self.passed.append(f"Python {v.major}.{v.minor}.{v.micro}")
        else:
            self.errors.append(f"Python 3.9+ required, got {v.major}.{v.minor}")

    def _check_ffmpeg(self):
        if shutil.which("ffmpeg"):
            try:
                r = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
                ver = r.stdout.decode().split("\n")[0][:50]
                self.passed.append(f"ffmpeg: {ver}")
            except Exception:
                self.passed.append("ffmpeg: installed")
        else:
            self.errors.append("ffmpeg NOT FOUND — install: sudo apt install ffmpeg")

    def _check_ytdlp(self):
        if shutil.which("yt-dlp"):
            try:
                r = subprocess.run(["yt-dlp", "--version"], capture_output=True, timeout=5)
                ver = r.stdout.decode().strip()
                self.passed.append(f"yt-dlp: {ver}")
            except Exception:
                self.passed.append("yt-dlp: installed")
        else:
            self.warnings.append("yt-dlp NOT FOUND — install: pip install yt-dlp  "
                                  "(needed for YouTube download)")

    def _check_disk_space(self):
        total, used, free = shutil.disk_usage(self.queue_dir.parent)
        free_gb = free / 1e9
        if free_gb >= 5:
            self.passed.append(f"Disk space: {free_gb:.1f} GB free")
        elif free_gb >= 1:
            self.warnings.append(f"Low disk space: {free_gb:.1f} GB free (need 5GB+)")
        else:
            self.errors.append(f"Critically low disk space: {free_gb:.2f} GB free")

    def _check_queue_dir(self):
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        test_file = self.queue_dir / ".write_test"
        try:
            test_file.write_text("ok")
            test_file.unlink()
            self.passed.append(f"Queue dir writable: {self.queue_dir}")
        except Exception as e:
            self.errors.append(f"Queue dir not writable: {e}")

    def _check_facebook_token(self):
        fb = self.cfg.get("facebook", {})
        if fb.get("disabled", False):
            self.warnings.append("Facebook: disabled in config")
            return

        accounts = fb.get("accounts", [])
        if not accounts:
            self.warnings.append("Facebook: no accounts configured")
            return

        acc   = accounts[0]
        pid   = acc.get("page_id", "")
        token = acc.get("access_token", "")

        if not pid or pid.startswith("${"):
            self.errors.append("Facebook: page_id not set (set FB_PAGE_ID env var)")
            return
        if not token or token.startswith("${"):
            self.errors.append("Facebook: access_token not set (set FB_PAGE_ACCESS_TOKEN env var)")
            return

        # Quick token validation
        try:
            url = (f"https://graph.facebook.com/v19.0/{pid}"
                   f"?fields=name&access_token={token}")
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
            page_name = data.get("name", pid)
            self.passed.append(f"Facebook token valid — page: {page_name}")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                self.errors.append(f"Facebook token INVALID (HTTP {e.code}) — regenerate token")
            else:
                self.warnings.append(f"Facebook token check failed (HTTP {e.code}) — may still work")
        except Exception as e:
            self.warnings.append(f"Facebook token check skipped (no internet?): {e}")

    def _check_config(self):
        channels = self.cfg.get("channels", [])
        if not channels:
            self.errors.append("No YouTube channels configured in config.yaml")
        else:
            self.passed.append(f"Config: {len(channels)} YouTube channels configured")

        niche = self.cfg.get("niche", "")
        if niche:
            self.passed.append(f"Niche: {niche}")
        else:
            self.warnings.append("No niche set in config — defaulting to 'movie'")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from src.config_manager import ConfigManager
    cfg = ConfigManager(Path("config/config.yaml")).config
    hc  = HealthCheck(cfg, Path("queue"))
    ok  = hc.run_all()
    sys.exit(0 if ok else 1)
