from pathlib import Path
import os, sys

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "cloud"))

from src.config_manager import ConfigManager
from cloud.run_pipeline import load_all, run_once

VIDEO_ID = os.environ.get("TEST_VIDEO_ID", "dQw4w9WgXcQ")
VIDEO_URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"

cfg = ConfigManager(ROOT / "cloud" / "config" / "config.yaml").config
queue_dir = ROOT / "cloud" / "queue"
queue_dir.mkdir(exist_ok=True)

engines = load_all(cfg, queue_dir)

meta = engines['yt_monitor']._get_metadata(VIDEO_URL)
if not meta:
    print("Failed to fetch metadata for", VIDEO_URL)
    sys.exit(1)

# Override scan_all to return our single video
engines['yt_monitor'].scan_all = lambda: [meta]

print("Running pipeline for:", meta.video_id, meta.title)
run_once(cfg, queue_dir, engines)
