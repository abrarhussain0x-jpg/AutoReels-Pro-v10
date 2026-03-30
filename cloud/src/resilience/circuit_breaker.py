"""
circuit_breaker.py — Simple circuit breaker for platform API calls.

States: CLOSED (normal) → OPEN (failing) → HALF_OPEN (testing recovery)
"""
from __future__ import annotations
import logging
import time
from enum import Enum
from threading import Lock
from typing import Callable, Optional

log = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED    = "closed"      # normal operation
    OPEN      = "open"        # failing — calls blocked
    HALF_OPEN = "half_open"   # one probe allowed


class CircuitBreakerOpen(Exception):
    """Raised when a call is attempted against an open circuit."""


class CircuitBreaker:
    """
    Thread-safe circuit breaker.

    Usage:
        cb = CircuitBreaker(name="facebook", failure_threshold=3, reset_timeout=30)

        try:
            with cb:
                result = facebook_api_call()
        except CircuitBreakerOpen:
            log.warning("Facebook circuit open — skipping")
    """

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 3,
        reset_timeout: float = 30.0,
        success_threshold: int = 1,
    ):
        self.name              = name
        self.failure_threshold = failure_threshold
        self.reset_timeout     = reset_timeout
        self.success_threshold = success_threshold

        self._state            = CircuitState.CLOSED
        self._failure_count    = 0
        self._success_count    = 0
        self._last_failure_at: Optional[float] = None
        self._lock             = Lock()

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._state

    @property
    def is_open(self) -> bool:
        return self.state == CircuitState.OPEN

    # ── Context manager ───────────────────────────────────────────────────────

    def __enter__(self):
        with self._lock:
            if self._state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self._state = CircuitState.HALF_OPEN
                    log.info("[Circuit:%s] → HALF_OPEN (probing)", self.name)
                else:
                    raise CircuitBreakerOpen(
                        f"Circuit '{self.name}' is OPEN. "
                        f"Retry after {self._seconds_until_reset():.0f}s."
                    )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None and exc_type is not CircuitBreakerOpen:
            self._record_failure()
        else:
            self._record_success()
        return False  # do not suppress exceptions

    # ── Manual call API ───────────────────────────────────────────────────────

    def call(self, func: Callable, *args, **kwargs):
        """Execute func inside the circuit breaker."""
        with self:
            return func(*args, **kwargs)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _record_failure(self):
        with self._lock:
            self._failure_count  += 1
            self._success_count   = 0
            self._last_failure_at = time.monotonic()
            if self._state == CircuitState.HALF_OPEN or self._failure_count >= self.failure_threshold:
                if self._state != CircuitState.OPEN:
                    log.warning(
                        "[Circuit:%s] → OPEN after %d failures",
                        self.name, self._failure_count,
                    )
                self._state = CircuitState.OPEN

    def _record_success(self):
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    log.info("[Circuit:%s] → CLOSED (recovered)", self.name)
                    self._state         = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
            elif self._state == CircuitState.CLOSED:
                self._failure_count = 0

    def _should_attempt_reset(self) -> bool:
        if self._last_failure_at is None:
            return True
        return (time.monotonic() - self._last_failure_at) >= self.reset_timeout

    def _seconds_until_reset(self) -> float:
        if self._last_failure_at is None:
            return 0.0
        elapsed = time.monotonic() - self._last_failure_at
        return max(0.0, self.reset_timeout - elapsed)

    def reset(self):
        """Manually reset circuit to CLOSED."""
        with self._lock:
            self._state         = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            log.info("[Circuit:%s] manually reset → CLOSED", self.name)

    def __repr__(self) -> str:
        return (
            f"CircuitBreaker(name={self.name!r}, state={self._state.value}, "
            f"failures={self._failure_count}/{self.failure_threshold})"
        )
