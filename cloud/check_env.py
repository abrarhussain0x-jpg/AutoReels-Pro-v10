"""Simple environment checker for AUTO-REELS v10.

Checks: ffmpeg, yt-dlp, Node.js (optional JS solver), and yt-dlp's ability
to extract formats for a test YouTube video.
"""
from __future__ import annotations

import shutil, subprocess, sys

def which(cmd):
    return shutil.which(cmd) is not None

def run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return 255, "", str(e)

def main():
    print("=== AUTO-REELS ENV CHECK ===")

    tools = ["ffmpeg", "yt-dlp", "node"]
    found = {}
    for t in tools:
        ok = which(t)
        found[t] = ok
        print(f"{t}: {'FOUND' if ok else 'MISSING'}")

    # ffmpeg and yt-dlp are required for core pipeline functionality.
    required_missing = [t for t in ("ffmpeg", "yt-dlp") if not found[t]]
    if required_missing:
        print("Missing required tools:", ", ".join(required_missing))
        print("Install missing tools before running AUTO-REELS.")
        sys.exit(1)

    code, out, err = run(["yt-dlp", "--version"]) if which("yt-dlp") else (1, "", "yt-dlp missing")
    if code == 0:
        print("yt-dlp version:", out.splitlines()[0])
    else:
        print("yt-dlp check error:", err[:200])
        sys.exit(1)

    code, out, err = run(["ffmpeg", "-version"]) if which("ffmpeg") else (1, "", "ffmpeg missing")
    if code == 0:
        print(out.splitlines()[0])
    else:
        print("ffmpeg check error:", err[:200])
        sys.exit(1)

    # Test yt-dlp extraction on a known public video
    test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    print("Testing yt-dlp format extraction for", test_url)
    code, out, err = run(["yt-dlp", "--dump-json", "--no-playlist", "--skip-download", test_url]) if which("yt-dlp") else (1, "", "yt-dlp missing")
    if code != 0:
        print("yt-dlp extraction failed. stderr:")
        print(err[:1000])
        if "challenge solving failed" in err or "Only images are available" in err:
            print("Detected JavaScript challenge — install Node.js and follow yt-dlp EJS setup:")
            print("  https://github.com/yt-dlp/yt-dlp/wiki/EJS")
        sys.exit(2)
    else:
        print("yt-dlp extraction OK — formats available.")

    print("Environment looks OK for AUTO-REELS (basic checks passed).")

if __name__ == '__main__':
    main()
