"""Structured logging, metrics collection, and health checks."""

import logging
import json
import time
from datetime import datetime
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from enum import Enum
import traceback

log = logging.getLogger(__name__)


class Severity(Enum):
    """Log severity levels."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class StructuredLog:
    """Structured log entry in JSON format."""
    timestamp: str
    severity: str
    service: str
    component: str
    message: str
    context: Dict[str, Any]
    trace_id: Optional[str] = None
    duration_ms: Optional[float] = None
    error: Optional[str] = None
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(asdict(self))


class StructuredLogger:
    """Logger with JSON output for aggregation systems."""

    def __init__(self, service: str, component: str):
        self.service = service
        self.component = component
        self.logger = logging.getLogger(f"{service}.{component}")

    def log(
        self,
        severity: Severity,
        message: str,
        context: Optional[Dict] = None,
        trace_id: Optional[str] = None,
        duration_ms: Optional[float] = None,
        error: Optional[Exception] = None
    ):
        """Log structured message."""
        log_entry = StructuredLog(
            timestamp=datetime.utcnow().isoformat(),
            severity=severity.value,
            service=self.service,
            component=self.component,
            message=message,
            context=context or {},
            trace_id=trace_id,
            duration_ms=duration_ms,
            error=traceback.format_exc() if error else None
        )
        
        # Output as JSON
        json_str = log_entry.to_json()
        
        if severity == Severity.DEBUG:
            self.logger.debug(json_str)
        elif severity == Severity.INFO:
            self.logger.info(json_str)
        elif severity == Severity.WARNING:
            self.logger.warning(json_str)
        elif severity == Severity.ERROR:
            self.logger.error(json_str)
        else:  # CRITICAL
            self.logger.critical(json_str)

    def info(self, msg: str, **context):
        """Log info with context."""
        self.log(Severity.INFO, msg, context)

    def error(self, msg: str, exc: Optional[Exception] = None, **context):
        """Log error with optional exception."""
        self.log(Severity.ERROR, msg, context, error=exc)

    def warning(self, msg: str, **context):
        """Log warning with context."""
        self.log(Severity.WARNING, msg, context)


@dataclass
class Metric:
    """Performance metric."""
    name: str
    value: float
    unit: str
    timestamp: str
    component: str
    tags: Dict[str, str]


class MetricsCollector:
    """Collect and aggregate performance metrics."""

    def __init__(self):
        self.metrics: List[Metric] = []
        self.start_times: Dict[str, float] = {}
        self.counters: Dict[str, int] = {}

    def start_timer(self, operation: str):
        """Start timing an operation."""
        self.start_times[operation] = time.time()

    def end_timer(self, operation: str, component: str = "", tags: Optional[Dict] = None) -> float:
        """End timing and record metric."""
        if operation not in self.start_times:
            return 0.0
        
        elapsed_ms = (time.time() - self.start_times[operation]) * 1000
        
        metric = Metric(
            name=operation,
            value=elapsed_ms,
            unit="ms",
            timestamp=datetime.utcnow().isoformat(),
            component=component,
            tags=tags or {}
        )
        
        self.metrics.append(metric)
        del self.start_times[operation]
        
        return elapsed_ms

    def increment_counter(self, name: str, amount: int = 1):
        """Increment a counter metric."""
        self.counters[name] = self.counters.get(name, 0) + amount

    def get_summary(self) -> Dict[str, Any]:
        """Get metrics summary."""
        return {
            "total_metrics": len(self.metrics),
            "counters": self.counters,
            "latest_metrics": self.metrics[-10:] if self.metrics else []
        }

    def to_json(self) -> str:
        """Export metrics as JSON."""
        return json.dumps([asdict(m) for m in self.metrics])


class HealthCheck:
    """Service health status."""

    def __init__(self):
        self.checks: Dict[str, bool] = {}
        self.errors: Dict[str, str] = {}

    def register_check(self, name: str, handler: callable):
        """Register a health check."""
        try:
            result = handler()
            self.checks[name] = result
            if not result:
                self.errors[name] = "Check returned False"
        except Exception as e:
            self.checks[name] = False
            self.errors[name] = str(e)

    def is_healthy(self) -> bool:
        """Check overall health."""
        return all(self.checks.values()) if self.checks else True

    def status(self) -> Dict[str, Any]:
        """Get health status as dict."""
        return {
            "healthy": self.is_healthy(),
            "checks": self.checks,
            "errors": self.errors,
            "timestamp": datetime.utcnow().isoformat()
        }

    def status_json(self) -> str:
        """Get health status as JSON."""
        return json.dumps(self.status())


# Global singletons
_metrics = MetricsCollector()
_health = HealthCheck()


def get_metrics() -> MetricsCollector:
    """Get global metrics collector."""
    return _metrics


def get_health_check() -> HealthCheck:
    """Get global health check."""
    return _health


def structured_logger(service: str, component: str) -> StructuredLogger:
    """Create a structured logger."""
    return StructuredLogger(service, component)
