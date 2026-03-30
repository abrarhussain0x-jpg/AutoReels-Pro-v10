"""
progress.py — Real-time terminal progress bars for pipeline operations.
Shows download progress, clip processing, and upload status.
Works in any terminal. No external deps.
"""
from __future__ import annotations
import sys, time, threading
from typing import Optional


class ProgressBar:
    """Thread-safe terminal progress bar."""

    def __init__(self, total: int, desc: str = "", width: int = 40):
        self.total   = max(1, total)
        self.desc    = desc
        self.width   = width
        self.current = 0
        self.start_t = time.time()
        self._lock   = threading.Lock()
        self._done   = False

    def update(self, n: int = 1, status: str = ""):
        with self._lock:
            self.current = min(self.total, self.current + n)
            self._render(status)

    def set(self, n: int, status: str = ""):
        with self._lock:
            self.current = min(self.total, max(0, n))
            self._render(status)

    def done(self, status: str = "✅ done"):
        with self._lock:
            self.current = self.total
            self._render(status)
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._done = True

    def fail(self, reason: str = "❌ failed"):
        with self._lock:
            self._render(reason, failed=True)
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._done = True

    def _render(self, status: str = "", failed: bool = False):
        pct    = self.current / self.total
        filled = int(self.width * pct)
        bar    = "█" * filled + "░" * (self.width - filled)
        color  = "\033[31m" if failed else ("\033[32m" if pct >= 1.0 else "\033[33m")
        reset  = "\033[0m"
        elapsed = time.time() - self.start_t
        eta_str = ""
        if pct > 0.05 and pct < 1.0:
            eta = (elapsed / pct) * (1 - pct)
            eta_str = f" ETA:{eta:.0f}s"
        label = f"{self.desc[:20]:<20}" if self.desc else ""
        line  = (f"\r{color}{label} [{bar}] {self.current}/{self.total} "
                 f"({pct:.0%}){eta_str} {status[:30]}{reset}")
        sys.stdout.write(line)
        sys.stdout.flush()


class PipelineProgress:
    """High-level progress tracker for the full pipeline."""

    def __init__(self, total_videos: int, total_clips_per_video: int):
        self.total_videos = total_videos
        self.clips_per    = total_clips_per_video
        self._video_bar: Optional[ProgressBar] = None
        self._clip_bar:  Optional[ProgressBar] = None

    def start_video(self, idx: int, title: str):
        print(f"\n📽  [{idx}/{self.total_videos}] {title[:60]}")
        self._video_bar = None

    def start_download(self):
        self._video_bar = ProgressBar(100, "⬇ Download")
        self._video_bar.update(0, "connecting...")

    def download_progress(self, pct: int):
        if self._video_bar:
            self._video_bar.set(pct, f"{pct}%")

    def download_done(self):
        if self._video_bar:
            self._video_bar.done("downloaded")

    def start_clipping(self, n_clips: int):
        self._clip_bar = ProgressBar(n_clips, "✂  Clipping")

    def clip_done(self, i: int):
        if self._clip_bar:
            self._clip_bar.update(1, f"clip {i}")

    def clipping_done(self):
        if self._clip_bar:
            self._clip_bar.done()

    def start_uploading(self, n: int):
        self._clip_bar = ProgressBar(n, "📤 Uploading")

    def upload_done(self, i: int, platform: str = ""):
        if self._clip_bar:
            self._clip_bar.update(1, f"{platform} clip {i}")

    def upload_failed(self, i: int):
        if self._clip_bar:
            self._clip_bar.update(1, f"❌ clip {i}")

    def all_done(self, total_uploaded: int):
        print(f"\n\n✅ Pipeline complete — {total_uploaded} clips uploaded\n")


class SpinnerThread:
    """Animated spinner for operations with unknown duration."""

    FRAMES = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]

    def __init__(self, message: str = "Working..."):
        self.message = message
        self._stop   = threading.Event()
        self._thread = threading.Thread(target=self._spin, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_):
        self._stop.set()
        self._thread.join(timeout=2)
        sys.stdout.write(f"\r{' ' * (len(self.message) + 10)}\r")
        sys.stdout.flush()

    def _spin(self):
        i = 0
        while not self._stop.is_set():
            frame = self.FRAMES[i % len(self.FRAMES)]
            sys.stdout.write(f"\r\033[36m{frame}\033[0m {self.message}")
            sys.stdout.flush()
            self._stop.wait(timeout=0.1)
            i += 1
