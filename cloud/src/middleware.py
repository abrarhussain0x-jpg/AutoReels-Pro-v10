"""AutoReels Pro v10 — Rate Limiting & Security"""

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from datetime import datetime, timedelta
import hashlib
import redis
import os
import logging

logger = logging.getLogger(__name__)

class RateLimiter:
    """Token bucket rate limiter using Redis"""
    
    def __init__(self, redis_url: str = None):
        self.redis_url = redis_url or os.getenv('REDIS_URL', 'redis://localhost:6379')
        self.client = redis.from_url(self.redis_url)
    
    async def is_allowed(self, key: str, limit: int = 100, window: int = 60) -> bool:
        """Check if request is within rate limit"""
        try:
            current = self.client.incr(key)
            if current == 1:
                self.client.expire(key, window)
            return current <= limit
        except Exception as e:
            logger.warning(f"Redis rate limiter unavailable ({e}) — using in-process fallback")
            return self._in_process_check(key, limit, window)

    def _in_process_check(self, key: str, limit: int, window: int) -> bool:
        """In-process fallback rate limiter used when Redis is down (fail safe, not open)."""
        import time
        from collections import deque
        now = time.monotonic()
        if not hasattr(self, "_local_buckets"):
            self._local_buckets = {}
        bucket = self._local_buckets.setdefault(key, deque())
        # Remove entries outside the window
        while bucket and now - bucket[0] > window:
            bucket.popleft()
        if len(bucket) >= limit:
            return False  # fail CLOSED — deny request
        bucket.append(now)
        return True
    
    async def get_remaining(self, key: str, limit: int = 100) -> int:
        """Get remaining requests for key"""
        try:
            current = self.client.get(key)
            if current is None:
                return limit
            return max(0, limit - int(current))
        except:
            return limit

# ── MIDDLEWARE ──────────────────────────────────────────────

async def rate_limit_middleware(request: Request, call_next):
    """FastAPI middleware for rate limiting"""
    
    # Get client IP
    client_ip = request.client.host
    
    # Get API key from header if present
    api_key = request.headers.get("X-API-Key", "")
    
    # Create rate limit key
    if api_key:
        key = f"rate_limit:api:{hashlib.sha256(api_key.encode()).hexdigest()}"
        limit = 10000  # 10k/min for API key
    else:
        key = f"rate_limit:ip:{client_ip}"
        limit = 100  # 100/min for anonymous
    
    limiter = RateLimiter()
    
    if not await limiter.is_allowed(key, limit=limit, window=60):
        return JSONResponse(
            status_code=429,
            content={
                "error": "Rate limit exceeded",
                "retry_after": 60,
                "timestamp": datetime.utcnow().isoformat()
            }
        )
    
    response = await call_next(request)
    
    remaining = await limiter.get_remaining(key, limit=limit)
    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    response.headers["X-RateLimit-Reset"] = str(int((datetime.utcnow() + timedelta(minutes=1)).timestamp()))
    
    return response

# ── CACHE DECORATOR ────────────────────────────────────────

# ── REDIS SINGLETON FOR CACHING ──────────────────────────────────────────────
_redis_client = None

def _get_redis():
    """Return a module-level Redis client (created once)."""
    global _redis_client
    if _redis_client is None:
        try:
            _redis_client = redis.from_url(
                os.getenv("REDIS_URL", "redis://localhost:6379"),
                decode_responses=True,
                socket_connect_timeout=2,
            )
        except Exception as e:
            logger.warning("Redis unavailable for caching: %s", e)
    return _redis_client


def cache_response(ttl: int = 300):
    """
    Decorator to cache FastAPI endpoint responses in Redis.

    Usage:
        @app.get("/api/v1/analytics/summary")
        @cache_response(ttl=60)
        async def analytics_summary(request, ...):
            ...

    The cache key is derived from the function name + request path + query string.
    Cache is skipped silently if Redis is unavailable.
    """
    import functools, json

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Build a stable cache key from function name + relevant kwargs
            key_parts = [func.__name__]
            # Include request path if present
            for arg in args:
                if hasattr(arg, "url"):      # FastAPI Request object
                    key_parts.append(str(arg.url))
                    break
            for k, v in sorted(kwargs.items()):
                if k != "db":               # skip SQLAlchemy sessions
                    key_parts.append(f"{k}={v}")
            cache_key = "cache:" + ":".join(key_parts)

            r = _get_redis()
            if r:
                try:
                    cached = r.get(cache_key)
                    if cached:
                        return json.loads(cached)
                except Exception as e:
                    logger.debug("Cache lookup failed: %s", e)

            result = await func(*args, **kwargs)

            if r:
                try:
                    r.setex(cache_key, ttl, json.dumps(result, default=str))
                except Exception as e:
                    logger.debug("Cache set failed: %s", e)

            return result

        return wrapper
    return decorator

# ── SECURITY HEADERS ────────────────────────────────────────

async def security_headers_middleware(request: Request, call_next):
    """Add security headers to all responses"""
    response = await call_next(request)
    
    # CORS
    response.headers["Access-Control-Allow-Origin"] = "*"
    
    # Security
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    
    # CSP
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline';"
    
    return response

# ── INPUT VALIDATION ────────────────────────────────────────

class InputValidator:
    """Validate user input to prevent injection attacks"""
    
    ALLOWED_CHARS_URL = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~:/?#[]@!$&\'()*+,;=')
    ALLOWED_CHARS_TEXT = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -.,!?\'"()[]{}')
    
    @staticmethod
    def validate_url(url: str) -> bool:
        """Validate URL safety"""
        if not url or len(url) > 2048:
            return False
        
        # Check for valid URL format
        if not (url.startswith('http://') or url.startswith('https://')):
            return False
        
        # Check character set
        return all(c in InputValidator.ALLOWED_CHARS_URL for c in url)
    
    @staticmethod
    def validate_text(text: str, max_length: int = 5000) -> bool:
        """Validate text input"""
        if not text or len(text) > max_length:
            return False
        
        # Check character set
        return all(c in InputValidator.ALLOWED_CHARS_TEXT or ord(c) > 127 for c in text)
    
    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """Remove dangerous characters from filename"""
        import re
        # Keep only alphanumeric, dash, underscore, dot
        filename = re.sub(r'[^a-zA-Z0-9._-]', '', filename)
        # Prevent directory traversal
        filename = filename.replace('..', '')
        return filename[:255]  # Max filename length

# ── REQUEST SIGNING ────────────────────────────────────────

import hashlib
import hmac

class RequestSigner:
    """Sign and verify webhook requests"""
    
    def __init__(self, secret: str):
        self.secret = secret.encode()
    
    def sign_request(self, body: bytes) -> str:
        """Generate signature for request body"""
        return hmac.new(self.secret, body, hashlib.sha256).hexdigest()
    
    def verify_signature(self, body: bytes, signature: str) -> bool:
        """Verify request signature"""
        expected = self.sign_request(body)
        return hmac.compare_digest(expected, signature)

# ── AUDIT LOGGING ──────────────────────────────────────────

class AuditLogger:
    """Log important actions for compliance.

    Call AuditLogger.init_schema(engine) once at application startup
    to create the audit_log table. After that, instantiate per-request
    with AuditLogger(db_session).
    """

    # Table reference shared across all instances (set by init_schema)
    _audit_table = None

    def __init__(self, db_session):
        self.db = db_session

    @classmethod
    def init_schema(cls, engine):
        """Create the audit_log table. Call ONCE at application startup."""
        from sqlalchemy import (
            Table, Column, String, DateTime, Boolean, JSON, MetaData, text
        )
        import uuid

        metadata = MetaData()
        cls._audit_table = Table(
            "audit_log",
            metadata,
            Column("id",            String,   primary_key=True),
            Column("action",        String,   nullable=False),
            Column("user_id",       String),
            Column("resource_type", String),
            Column("resource_id",   String),
            Column("details",       JSON),
            Column("success",       Boolean,  default=True),
            Column("timestamp",     DateTime, default=datetime.utcnow),
        )
        metadata.create_all(engine)
        logger.info("AuditLogger: audit_log table ready")

    async def log_action(
        self,
        action: str,
        user_id: str,
        resource_type: str,
        resource_id: str,
        details: dict = None,
        success: bool = True,
    ):
        """Log a single auditable action."""
        import uuid
        if self._audit_table is None:
            logger.warning("AuditLogger: schema not initialised — call init_schema(engine) at startup")
            return
        try:
            self.db.execute(
                self._audit_table.insert().values(
                    id=str(uuid.uuid4()),
                    action=action,
                    user_id=user_id,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    details=details or {},
                    success=success,
                    timestamp=datetime.utcnow(),
                )
            )
            self.db.commit()
        except Exception as e:
            logger.error("Audit logging failed: %s", e)
