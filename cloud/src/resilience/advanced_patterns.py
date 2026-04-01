"""Advanced resilience patterns: circuit breaker, bulkhead, retry strategies."""

import logging
import time
from datetime import datetime, timedelta
from typing import Callable, Optional, Any, Type
from enum import Enum
import random

log = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"          # Normal operation
    OPEN = "open"              # Failure threshold exceeded
    HALF_OPEN = "half_open"    # Testing recovery


class CircuitBreaker:
    """
    Circuit breaker pattern for fault tolerance.
    
    Prevents cascading failures by stopping calls to failing services.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        expected_exception: Type = Exception
    ):
        """
        Initialize circuit breaker.
        
        Args:
            name: Service name
            failure_threshold: Failures before opening circuit
            recovery_timeout: Seconds before attempting recovery
            expected_exception: Exception type to catch
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = None
        self.success_count = 0

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function through circuit breaker."""
        
        if self.state == CircuitState.OPEN:
            if self._should_attempt_recovery():
                self.state = CircuitState.HALF_OPEN
                log.info(f"[CircuitBreaker] {self.name}: HALF_OPEN - attempting recovery")
            else:
                raise Exception(f"Circuit breaker OPEN for {self.name}")
        
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exception as e:
            self._on_failure()
            raise

    def _on_success(self):
        """Handle successful call."""
        self.failure_count = 0
        
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= 2:  # 2 successes to close
                self.state = CircuitState.CLOSED
                self.success_count = 0
                log.info(f"[CircuitBreaker] {self.name}: CLOSED - recovery successful")

    def _on_failure(self):
        """Handle failed call."""
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            log.error(f"[CircuitBreaker] {self.name}: OPEN after {self.failure_count} failures")

    def _should_attempt_recovery(self) -> bool:
        """Check if enough time has passed to attempt recovery."""
        if not self.last_failure_time:
            return True
        elapsed = (datetime.now() - self.last_failure_time).total_seconds()
        return elapsed >= self.recovery_timeout


class AdaptiveRetry:
    """
    Adaptive retry with exponential backoff and jitter.
    
    Automatically adjusts retry strategy based on failure patterns.
    """

    def __init__(
        self,
        max_retries: int = 5,
        initial_delay: float = 1.0,
        max_delay: float = 300.0,
        exponential_base: float = 2.0,
        jitter: bool = True
    ):
        """
        Initialize adaptive retry.
        
        Args:
            max_retries: Maximum retry attempts
            initial_delay: Initial delay in seconds
            max_delay: Maximum delay cap
            exponential_base: Exponential backoff multiplier
            jitter: Add random jitter to avoid thundering herd
        """
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.attempt = 0

    def execute(
        self,
        func: Callable,
        *args,
        retryable_exceptions: tuple = (Exception,),
        **kwargs
    ) -> Any:
        """
        Execute function with adaptive retry.
        
        Args:
            func: Callable to execute
            retryable_exceptions: Tuple of exceptions to retry on
            
        Returns:
            Function result
        """
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                return func(*args, **kwargs)
            except retryable_exceptions as e:
                last_exception = e
                
                if attempt >= self.max_retries:
                    log.error(f"[AdaptiveRetry] Max retries ({self.max_retries}) exceeded: {e}")
                    raise
                
                delay = self._calculate_backoff(attempt)
                log.warning(f"[AdaptiveRetry] Attempt {attempt + 1}/{self.max_retries + 1} failed, retrying in {delay:.2f}s: {e}")
                time.sleep(delay)
        
        raise last_exception

    def _calculate_backoff(self, attempt: int) -> float:
        """Calculate exponential backoff with optional jitter."""
        delay = self.initial_delay * (self.exponential_base ** attempt)
        delay = min(delay, self.max_delay)  # Cap at max_delay
        
        if self.jitter:
            jitter_amount = delay * 0.1 * random.random()
            delay += jitter_amount
        
        return delay


class Bulkhead:
    """
    Bulkhead pattern for resource isolation.
    
    Limits concurrent calls to prevent resource exhaustion.
    """

    def __init__(self, name: str, max_concurrent: int = 10, queue_size: int = 100):
        """
        Initialize bulkhead.
        
        Args:
            name: Bulkhead name
            max_concurrent: Max concurrent calls
            queue_size: Max queued requests
        """
        self.name = name
        self.max_concurrent = max_concurrent
        self.queue_size = queue_size
        self.current_count = 0
        self.rejected_count = 0

    def acquire(self) -> bool:
        """Try to acquire bulkhead slot."""
        if self.current_count >= self.max_concurrent:
            self.rejected_count += 1
            log.warning(f"[Bulkhead] {self.name}: Rejected (max {self.max_concurrent} concurrent)")
            return False
        
        self.current_count += 1
        return True

    def release(self):
        """Release bulkhead slot."""
        self.current_count = max(0, self.current_count - 1)

    def __enter__(self):
        if not self.acquire():
            raise Exception(f"Bulkhead {self.name} exhausted")
        return self

    def __exit__(self, *args):
        self.release()


# Global resilience registry
_circuit_breakers = {}
_retry_policies = {}


def get_circuit_breaker(service_name: str) -> CircuitBreaker:
    """Get or create circuit breaker for service."""
    if service_name not in _circuit_breakers:
        _circuit_breakers[service_name] = CircuitBreaker(service_name)
    return _circuit_breakers[service_name]


def get_retry_policy() -> AdaptiveRetry:
    """Get or create default retry policy."""
    if "default" not in _retry_policies:
        _retry_policies["default"] = AdaptiveRetry()
    return _retry_policies["default"]
