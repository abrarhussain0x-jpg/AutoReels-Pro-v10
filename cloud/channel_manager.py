"""
channel_manager.py — Add/remove/list/test YouTube channels from CLI.
Edits config.yaml directly. No manual YAML editing needed.
Tests each channel URL is valid with yt-dlp before adding.

Usage:
    python channel_manager.py --list
    python channel_manager.py --add https://www.youtube.com/@channel/videos
    python channel_manager.py --remove https://www.youtube.com/@channel/videos
    python channel_manager.py --test https://www.youtube.com/@channel/videos
    python channel_manager.py --stats
"""
from __future__ import annotations
import argparse, logging, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

log = logging.getLogger(__name__)

DEFAULT_CHANNEL = {
    "max_videos_per_run": 1,
    "download_quality": "bestvideo[height<=1080]+bestaudio/best",
    "min_duration": 120,
    "max_duration": 7200,
    "max_age_days": 30,
    "min_views": 0,
    "min_like_ratio": 0.0,
    "keywords_filter": [],
    "exclude_keywords": ["live", "podcast", "interview"],
}


def load_config(path: Path) -> dict:
    import yaml, os, re
    raw  = path.read_text(encoding="utf-8")
    raw  = re.sub(r'\$\{(\w+)\}', lambda m: os.environ.get(m.group(1), ""), raw)
    return yaml.safe_load(raw) or {}


def save_channels(config_path: Path, channels: list):
    """Write updated channels list back to config.yaml (preserves other fields)."""
    import yaml
    try:
        content = config_path.read_text(encoding="utf-8")
        cfg     = yaml.safe_load(content) or {}
        cfg["channels"] = channels
        config_path.write_text(yaml.dump(cfg, default_flow_style=False, allow_unicode=True))
        print(f"✅ config.yaml updated ({len(channels)} channels)")
    except Exception as e:
        print(f"❌ Failed to save config: {e}")
        raise


def test_channel(url: str, cookies: str = "") -> bool:
    """Test if a YouTube channel URL is accessible with yt-dlp."""
    cmd = [
        "yt-dlp", "--flat-playlist", "--playlist-end", "1",
        "--no-warnings", "--quiet", "--simulate",
    ]
    if cookies and Path(cookies).exists():
        cmd += ["--cookies", cookies]
    cmd.append(url)

    print(f"  Testing {url[:60]}...")
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=20)
        if r.returncode == 0:
            print("  ✅ Channel is accessible")
            return True
        err = r.stderr.decode()[:100]
        print(f"  ❌ Error: {err}")
        return False
    except FileNotFoundError:
        print("  ⚠️  yt-dlp not installed — can't test. Add anyway? (unverified)")
        return True
    except Exception as e:
        print(f"  ⚠️  Test error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="AUTO-REELS Channel Manager")
    parser.add_argument("--list",   action="store_true", help="List all channels")
    parser.add_argument("--add",    metavar="URL",        help="Add a channel URL")
    parser.add_argument("--remove", metavar="URL",        help="Remove a channel URL")
    parser.add_argument("--test",   metavar="URL",        help="Test a channel URL")
    parser.add_argument("--stats",  action="store_true",  help="Show channel performance stats")
    parser.add_argument("--set-limit", nargs=2, metavar=("URL","N"),
                        help="Set max_videos_per_run for a channel")
    parser.add_argument("--config", default="config/config.yaml")
    args = parser.parse_args()

    config_path = ROOT / args.config
    if not config_path.exists():
        print(f"❌ Config not found: {config_path}")
        sys.exit(1)

    cfg      = load_config(config_path)
    channels = cfg.get("channels", [])
    cookies  = cfg.get("youtube", {}).get("cookies_file", "config/cookies.txt")

    if args.list or not any([args.add, args.remove, args.test, args.stats, args.set_limit]):
        print(f"\n=== CONFIGURED CHANNELS ({len(channels)}) ===\n")
        for i, ch in enumerate(channels, 1):
            url   = ch.get("url", "")
            limit = ch.get("max_videos_per_run", 1)
            dur   = f"{ch.get('min_duration',0)//60}–{ch.get('max_duration',0)//60}min"
            print(f"  {i}. {url}")
            print(f"     max_per_run={limit}  duration={dur}  "
                  f"age<={ch.get('max_age_days',30)}d\n")
        return

    if args.add:
        url = args.add.rstrip("/")
        if any(ch.get("url") == url for ch in channels):
            print(f"⚠️  Already exists: {url}")
            return
        if test_channel(url, cookies):
            new_ch = {**DEFAULT_CHANNEL, "url": url}
            channels.append(new_ch)
            save_channels(config_path, channels)
            print(f"✅ Added: {url}")
        else:
            ans = input("Add anyway? [y/N] ")
            if ans.lower() == "y":
                channels.append({**DEFAULT_CHANNEL, "url": url})
                save_channels(config_path, channels)
        return

    if args.remove:
        url  = args.remove.rstrip("/")
        orig = len(channels)
        channels = [ch for ch in channels if ch.get("url", "").rstrip("/") != url]
        if len(channels) < orig:
            save_channels(config_path, channels)
            print(f"✅ Removed: {url}")
        else:
            print(f"❌ Not found: {url}")
        return

    if args.test:
        test_channel(args.test, cookies)
        return

    if args.set_limit:
        url, n = args.set_limit
        url = url.rstrip("/")
        found = False
        for ch in channels:
            if ch.get("url", "").rstrip("/") == url:
                ch["max_videos_per_run"] = int(n)
                found = True
                break
        if found:
            save_channels(config_path, channels)
            print(f"✅ Set max_videos_per_run={n} for {url}")
        else:
            print(f"❌ Channel not found: {url}")
        return

    if args.stats:
        queue_dir = ROOT / "queue"
        db_path   = queue_dir / "analytics.db"
        if not db_path.exists():
            print("No analytics data yet.")
            return
        import sqlite3
        conn = sqlite3.connect(db_path, timeout=5)
        print("\n=== CHANNEL PERFORMANCE ===\n")
        rows = conn.execute("""
            SELECT channel_id, COUNT(*) as uploads,
                   AVG(COALESCE(p.engagement,0)) as avg_eng,
                   SUM(COALESCE(p.views,0)) as total_views
            FROM uploads u
            LEFT JOIN performance p ON p.upload_id=u.id
            GROUP BY channel_id ORDER BY avg_eng DESC
        """).fetchall()
        for ch_id, uploads, avg_eng, views in rows:
            print(f"  {(ch_id or 'unknown')[:40]:<40} | uploads={uploads} "
                  f"| views={int(views or 0):,} | eng={avg_eng or 0:.2f}%")
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    main()
