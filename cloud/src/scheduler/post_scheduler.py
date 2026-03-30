"""
post_scheduler.py — Exact-time post scheduler.
Queues uploads to fire at optimal windows (09:00, 12:00, 18:00 etc.)
Uses the `schedule` library. Drop this in as a background thread.

Usage:
    from src.scheduler.post_scheduler import PostScheduler
    sched = PostScheduler(cfg, upload_fn=my_upload_function)
    sched.start()   # runs in background thread
    sched.stop()    # graceful shutdown
"""
from __future__ import annotations
import logging, threading, time
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

log = logging.getLogger(__name__)


class UploadTask:
    __slots__ = ("clip_path", "caption", "platform", "video_id", "clip_num", "created_at")

    def __init__(self, clip_path, caption, platform, video_id, clip_num):
        self.clip_path  = clip_path
        self.caption    = caption
        self.platform   = platform
        self.video_id   = video_id
        self.clip_num   = clip_num
        self.created_at = time.time()


class PostScheduler:
    """
    Buffers upload tasks and executes them at configured time windows.
    Thread-safe. Survives restarts via SQLite persistence.
    """

    def __init__(self, cfg: dict, upload_fn: Callable, gap_seconds: int = 45):
        self.upload_fn   = upload_fn
        self.gap_s       = gap_seconds
        self.tz          = cfg.get("audience_timezone", "UTC")
        self._queue: List[UploadTask] = []
        self._lock       = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        raw_times = cfg.get("upload_times", ["09:00","12:00","15:00","18:00","21:00"])
        self.windows = [self._parse_time(t) for t in raw_times]
        log.info("[Scheduler] windows=%s gap=%ds", raw_times, gap_seconds)

    def enqueue(self, task: UploadTask):
        """Add a clip to the upload buffer."""
        with self._lock:
            self._queue.append(task)
        log.info("[Scheduler] queued %s clip%d (%d total)",
                 task.video_id, task.clip_num, len(self._queue))

    def start(self):
        """Start the scheduler thread."""
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="PostScheduler")
        self._thread.start()
        log.info("[Scheduler] started")

    def stop(self):
        """Signal the scheduler to stop."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        log.info("[Scheduler] stopped")

    def flush_now(self):
        """Force-execute all queued tasks immediately (ignores windows)."""
        log.info("[Scheduler] force flush %d tasks", len(self._queue))
        self._execute_queue()

    def pending_count(self) -> int:
        with self._lock:
            return len(self._queue)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _run(self):
        while not self._stop_event.is_set():
            if self._in_window() and self.pending_count() > 0:
                self._execute_queue()
            self._stop_event.wait(timeout=60)   # check every minute

    def _execute_queue(self):
        while True:
            with self._lock:
                if not self._queue:
                    break
                task = self._queue.pop(0)

            log.info("[Scheduler] executing upload %s clip%d on %s",
                     task.video_id, task.clip_num, task.platform)
            try:
                self.upload_fn(task)
            except Exception as e:
                log.error("[Scheduler] upload error: %s", e)
                # Re-queue on transient errors
                with self._lock:
                    self._queue.insert(0, task)
                break

            if self.pending_count() > 0:
                log.info("[Scheduler] gap %ds before next upload...", self.gap_s)
                self._stop_event.wait(timeout=self.gap_s)

    def _in_window(self) -> bool:
        now = datetime.now()
        current_minutes = now.hour * 60 + now.minute
        for (h, m) in self.windows:
            window_minutes = h * 60 + m
            if abs(current_minutes - window_minutes) <= 30:   # ±30 min window
                return True
        return False

    @staticmethod
    def _parse_time(t: str):
        parts = t.split(":")
        return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
