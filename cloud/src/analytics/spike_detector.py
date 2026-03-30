"""
spike_detector.py — Real-time engagement spike detector.
Polls Facebook Graph API for recent post metrics every hour.
Detects viral spikes and triggers fast-track repost automatically.
Runs as background thread in daemon mode.
"""
from __future__ import annotations
import json, logging, sqlite3, threading, time, urllib.request
from pathlib import Path
from typing import Callable, List, Optional

log = logging.getLogger(__name__)

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS spike_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id     TEXT NOT NULL,
    platform    TEXT NOT NULL,
    metric      TEXT NOT NULL,
    value       REAL NOT NULL,
    threshold   REAL NOT NULL,
    detected_at REAL NOT NULL,
    actioned    INTEGER NOT NULL DEFAULT 0
);
"""

GRAPH = "https://graph.facebook.com/v19.0"


class SpikeDetector:
    """
    Polls recent posts and fires callbacks when engagement spikes.
    on_spike(post_id, metric, value) is called when threshold crossed.
    """

    def __init__(
        self,
        db_path: Path,
        access_token: str = "",
        page_id: str = "",
        poll_interval_s: int = 3600,          # 1 hour
        views_spike_threshold: int = 1000,    # views/hour
        likes_spike_threshold: int = 100,     # likes/hour
        on_spike: Optional[Callable] = None,
    ):
        self.db_path          = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.token            = access_token
        self.page_id          = page_id
        self.poll_interval    = poll_interval_s
        self.views_threshold  = views_spike_threshold
        self.likes_threshold  = likes_spike_threshold
        self.on_spike         = on_spike
        self._stop            = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_metrics: dict = {}

        with self._conn() as c:
            c.executescript(SCHEMA)
        log.info("[SpikeDetector] init poll=%ds views>%d/h likes>%d/h",
                 poll_interval_s, views_spike_threshold, likes_spike_threshold)

    def start(self):
        """Start background polling thread."""
        if not self.token or self.token.startswith("${"):
            log.info("[SpikeDetector] no token — disabled")
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._poll_loop,
                                        daemon=True, name="SpikeDetector")
        self._thread.start()
        log.info("[SpikeDetector] started")

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)

    def check_now(self, post_ids: List[str]) -> List[dict]:
        """Manually check specific post IDs for spikes."""
        spikes = []
        for post_id in post_ids:
            metrics = self._fetch_metrics(post_id)
            if not metrics:
                continue
            detected = self._check_thresholds(post_id, metrics)
            spikes.extend(detected)
        return spikes

    # ── Internal ──────────────────────────────────────────────────────────────

    def _poll_loop(self):
        while not self._stop.is_set():
            try:
                self._poll_recent_posts()
            except Exception as e:
                log.debug("[SpikeDetector] poll error: %s", e)
            self._stop.wait(timeout=self.poll_interval)

    def _poll_recent_posts(self):
        """Fetch recent posts from the page and check for spikes."""
        url = (f"{GRAPH}/{self.page_id}/posts"
               f"?fields=id,created_time&limit=10"
               f"&access_token={self.token}")
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                data = json.loads(resp.read())
            for post in data.get("data", []):
                post_id = post.get("id")
                if not post_id:
                    continue
                metrics  = self._fetch_metrics(post_id)
                detected = self._check_thresholds(post_id, metrics)
                for spike in detected:
                    self._record_spike(spike)
                    if self.on_spike:
                        try:
                            self.on_spike(spike["post_id"], spike["metric"], spike["value"])
                        except Exception as e:
                            log.debug("[SpikeDetector] on_spike callback error: %s", e)
        except Exception as e:
            log.debug("[SpikeDetector] page posts fetch error: %s", e)

    def _fetch_metrics(self, post_id: str) -> dict:
        url = (f"{GRAPH}/{post_id}"
               f"?fields=likes.summary(true),comments.summary(true),shares"
               f"&access_token={self.token}")
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
            return {
                "views":    data.get("insights", {}).get("impressions", 0),
                "likes":    data.get("likes",    {}).get("summary", {}).get("total_count", 0),
                "comments": data.get("comments", {}).get("summary", {}).get("total_count", 0),
                "shares":   data.get("shares",   {}).get("count", 0),
            }
        except Exception:
            return {}

    def _check_thresholds(self, post_id: str, metrics: dict) -> List[dict]:
        """Compare current metrics vs last snapshot to compute rates."""
        spikes = []
        prev   = self._last_metrics.get(post_id, {})
        elapsed_h = self.poll_interval / 3600

        for metric, threshold in [("likes", self.likes_threshold)]:
            curr = metrics.get(metric, 0)
            prev_val = prev.get(metric, curr)
            rate = (curr - prev_val) / elapsed_h if elapsed_h > 0 else 0

            if rate >= threshold:
                spikes.append({
                    "post_id": post_id, "platform": "facebook",
                    "metric": metric, "value": rate, "threshold": threshold,
                })
                log.warning("[SpikeDetector] 🚀 SPIKE! %s %s=%.0f/h (threshold=%d)",
                            post_id, metric, rate, threshold)

        self._last_metrics[post_id] = metrics
        return spikes

    def _record_spike(self, spike: dict):
        with self._conn() as c:
            c.execute("""
                INSERT INTO spike_events
                (post_id, platform, metric, value, threshold, detected_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (spike["post_id"], spike["platform"], spike["metric"],
                  spike["value"], spike["threshold"], time.time()))

    def _conn(self):
        return sqlite3.connect(self.db_path, timeout=10)
