import os
import subprocess
import sys
from pathlib import Path

COOKIES = "cloud/config/cookies.txt"
TEST_URL = "https://www.youtube.com/watch?v=8viqd3M7Kek"


def _is_strict_mode() -> bool:
    # Default strict locally; allow relaxed mode in CI with YTDLP_HEALTH_STRICT=0.
    return os.getenv("YTDLP_HEALTH_STRICT", "1").strip() not in {"0", "false", "False"}


def _known_platform_block(stderr_or_stdout: str) -> bool:
    text = (stderr_or_stdout or "").lower()
    patterns = [
        "sign in to confirm you're not a bot",
        "sign in to confirm you’re not a bot",
        "no supported javascript runtime could be found",
        "challenge solving failed",
        "only images are available",
    ]
    return any(p in text for p in patterns)


def _run_health_cmd() -> subprocess.CompletedProcess:
    cmd = ["yt-dlp", "--dump-json", "--no-playlist", "--skip-download"]
    cookies_file = Path(COOKIES)
    if cookies_file.exists() and cookies_file.stat().st_size > 0:
        print("Testing yt-dlp with cookies:", COOKIES)
        cmd.extend(["--cookies", COOKIES])
    else:
        print("Cookies file missing/empty; running yt-dlp check without cookies")
    cmd.append(TEST_URL)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


def main():
    strict = _is_strict_mode()
    print(f"yt-dlp health mode: {'strict' if strict else 'relaxed'}")

    try:
        result = _run_health_cmd()
        output = (result.stderr.strip() or result.stdout.strip())
        if result.returncode == 0 and result.stdout.strip().startswith("{"):
            print("✅ yt-dlp is working! Metadata fetched.")
            sys.exit(0)

        if not strict and _known_platform_block(output):
            print("⚠️ yt-dlp reached known YouTube anti-bot/JS-runtime constraint in CI.")
            print("Proceeding in relaxed mode because tooling itself is installed.")
            print(output)
            sys.exit(0)

        else:
            print("❌ yt-dlp failed. Error output:")
            print(output)
            if "rate-limit" in result.stderr or "rate-limit" in result.stdout:
                print("You are rate-limited. Wait 1 hour or refresh cookies.")
            elif "cookies" in result.stderr or "cookies" in result.stdout:
                print("Cookies expired or invalid. Refresh cookies.txt.")
            elif "JS" in result.stderr or "JS" in result.stdout:
                print("JS challenge. Make sure Node.js is installed and in PATH.")
            else:
                print("Unknown error. Try updating yt-dlp and cookies.")
            sys.exit(1)
    except Exception as e:
        print("Exception running yt-dlp:", e)
        sys.exit(2)

if __name__ == "__main__":
    main()
