"""
rate_limiter.py — Per-platform token-bucket rate limiters.

Keeps AutoReels within each platform's published API limits so we never
hit 429s during upload bursts.
"""
from __future__ import annotations
import logging
import time
from threading import Lock
from typing import Dict, Optional

log = logging.getLogger(__name__)


class TokenBucket:
    """
    Classic token-bucket rate limiter.

    - capacity: max burst size
    - refill_rate: tokens added per second
    - Calling acquire(n) blocks until n tokens are available.
    """

    def __init__(self, capacity: float, refill_rate: float, name: str = ""):
        self.capacity     = float(capacity)
        self.refill_rate  = float(refill_rate)
        self.name         = name
        self._tokens      = float(capacity)
        self._last_refill = time.monotonic()
        self._lock        = Lock()

    def acquire(self, tokens: float = 1.0, timeout: Optional[float] = None) -> bool:
        """
        Acquire `tokens` from the bucket.
        Returns True immediately if available, otherwise waits up to `timeout` seconds.
        Returns False if timed out.
        """
        deadline = time.monotonic() + timeout if timeout is not None else None

        while True:
            with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return True
                wait_time = (tokens - self._tokens) / self.refill_rate

            if deadline is not None and time.monotonic() + wait_time > deadline:
                return False

            sleep_time = min(wait_time, 0.1)
            log.debug("[RateLimit:%s] waiting %.2fs for tokens", self.name, wait_time)
            time.sleep(sleep_time)

    def _refill(self):
        now     = time.monotonic()
        elapsed = now - self._last_refill
        gained  = elapsed * self.refill_rate
        self._tokens      = min(self.capacity, self._tokens + gained)
        self._last_refill = now

    @property
    def available(self) -> float:
        with self._lock:
            self._refill()
            return self._tokens


class PlatformRateLimiters:
    """
    Pre-configured rate limiters for each social platform.

    Default limits are conservative estimates — platforms don't publish
    exact numbers, so we stay well below known thresholds.

    Usage:
        limiters = PlatformRateLimiters()
        limiters.acquire("facebook")   # blocks if needed
        facebook_api_call()
    """

    # (capacity, refill_rate_per_second)  — tune via config if needed
    _DEFAULTS: Dict[str, tuple] = {
        "facebook":  (5.0, 0.083),   # ~5 req burst, 5/min sustained
        "instagram": (5.0, 0.083),
        "tiktok":    (3.0, 0.05),    # 3 req burst, 3/min sustained
        "youtube":   (3.0, 0.05),
        "threads":   (3.0, 0.05),
        "generic":   (10.0, 0.167),  # 10/min fallback
    }

    def __init__(self, config: Optional[Dict] = None):
        self._buckets: Dict[str, TokenBucket] = {}
        cfg = config or {}
        for platform, (cap, rate) in self._DEFAULTS.items():
            override = cfg.get(platform, {})
            self._buckets[platform] = TokenBucket(
                capacity=override.get("burst", cap),
                refill_rate=override.get("rate_per_sec", rate),
                name=platform,
            )

    def acquire(self, platform: str, tokens: float = 1.0, timeout: Optional[float] = 30.0) -> bool:
        """
        Acquire a rate-limit token for `platform`.
        Returns False (and logs a warning) if timed out.
        """
        bucket = self._buckets.get(platform) or self._buckets["generic"]
        ok = bucket.acquire(tokens, timeout=timeout)
        if not ok:
            log.warning(
                "[RateLimit:%s] timed out waiting for token (%.1f available)",
                platform, bucket.available,
            )
        return ok

    def available(self, platform: str) -> float:
        bucket = self._buckets.get(platform) or self._buckets["generic"]
        return bucket.available

    def status(self) -> Dict[str, float]:
        return {name: b.available for name, b in self._buckets.items()}
