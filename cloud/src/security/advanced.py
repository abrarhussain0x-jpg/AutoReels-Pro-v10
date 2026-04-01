"""Security utilities: input validation, token refresh, secrets management."""

import re
import hmac
import hashlib
import logging
from typing import Any, Optional, Dict, List, Pattern
from datetime import datetime, timedelta
from urllib.parse import quote

log = logging.getLogger(__name__)


class InputValidator:
    """Validate and sanitize user inputs."""

    # Common patterns
    URL_PATTERN: Pattern = re.compile(
        r'^https?://[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&/=]*)$'
    )
    
    EMAIL_PATTERN: Pattern = re.compile(
        r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    )
    
    YOUTUBE_ID_PATTERN: Pattern = re.compile(
        r'^[a-zA-Z0-9_-]{11}$'  # YouTube video IDs are always 11 chars
    )
    
    FILENAME_PATTERN: Pattern = re.compile(
        r'^[a-zA-Z0-9._\-]+$'  # Safe filenames only
    )

    @staticmethod
    def is_valid_url(url: str, allowed_domains: Optional[List[str]] = None) -> bool:
        """Validate URL format and optionally check domain whitelist."""
        if not InputValidator.URL_PATTERN.match(url):
            return False
        
        if allowed_domains:
            for domain in allowed_domains:
                if domain in url:
                    return True
            return False
        
        return True

    @staticmethod
    def is_valid_email(email: str) -> bool:
        """Validate email format."""
        return bool(InputValidator.EMAIL_PATTERN.match(email))

    @staticmethod
    def is_valid_youtube_id(video_id: str) -> bool:
        """Validate YouTube video ID."""
        return bool(InputValidator.YOUTUBE_ID_PATTERN.match(video_id))

    @staticmethod
    def is_safe_filename(filename: str, max_length: int = 255) -> bool:
        """Validate filename safety."""
        if len(filename) > max_length or len(filename) == 0:
            return False
        return bool(InputValidator.FILENAME_PATTERN.match(filename))

    @staticmethod
    def sanitize_string(value: str, max_length: int = 1000, allowed_chars: Optional[str] = None) -> str:
        """Sanitize string input."""
        if not isinstance(value, str):
            return ""
        
        # Limit length
        value = value[:max_length]
        
        # Remove control characters
        value = ''.join(char for char in value if ord(char) >= 32 or char in '\n\r\t')
        
        # Optionally filter to allowed chars
        if allowed_chars:
            value = ''.join(char for char in value if char in allowed_chars)
        
        return value

    @staticmethod
    def escape_html(value: str) -> str:
        """Escape HTML special characters."""
        escapes = {
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#x27;"
        }
        return ''.join(escapes.get(char, char) for char in value)

    @staticmethod
    def validate_dict(data: Dict, schema: Dict[str, type]) -> bool:
        """Validate dictionary against schema."""
        for key, expected_type in schema.items():
            if key not in data:
                log.warning(f"Missing required field: {key}")
                return False
            if not isinstance(data[key], expected_type):
                log.warning(f"Field {key} has wrong type: expected {expected_type}, got {type(data[key])}")
                return False
        return True


class SecretManager:
    """Manage API tokens and secret rotation."""

    def __init__(self):
        self.tokens: Dict[str, Dict[str, Any]] = {}

    def register_token(
        self,
        service: str,
        token: str,
        expires_in: Optional[int] = None,
        refresh_token: Optional[str] = None
    ):
        """Register a token with expiry tracking."""
        expires_at = None
        if expires_in:
            expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
        
        self.tokens[service] = {
            "token": token,
            "expires_at": expires_at,
            "refresh_token": refresh_token,
            "created_at": datetime.utcnow()
        }

    def get_token(self, service: str) -> Optional[str]:
        """Get token, checking if expired."""
        if service not in self.tokens:
            return None
        
        token_data = self.tokens[service]
        
        # Check expiry with 5 min buffer
        if token_data.get("expires_at"):
            if datetime.utcnow() >= token_data["expires_at"] - timedelta(minutes=5):
                log.warning(f"Token for {service} expired or expiring soon")
                return None
        
        return token_data.get("token")

    def is_token_expired(self, service: str) -> bool:
        """Check if token is expired."""
        if service not in self.tokens:
            return True
        
        token_data = self.tokens[service]
        if not token_data.get("expires_at"):
            return False
        
        return datetime.utcnow() >= token_data["expires_at"]

    def get_refresh_token(self, service: str) -> Optional[str]:
        """Get refresh token for service."""
        if service not in self.tokens:
            return None
        return self.tokens[service].get("refresh_token")


class RateLimiter:
    """Simple token bucket rate limiter."""

    def __init__(self, rate: int, per_seconds: int = 1):
        """
        Initialize rate limiter.
        
        Args:
            rate: Number of requests allowed
            per_seconds: Time window in seconds
        """
        self.rate = rate
        self.per_seconds = per_seconds
        self.tokens = rate
        self.last_update = datetime.utcnow()

    def is_allowed(self, tokens_needed: int = 1) -> bool:
        """Check if request is allowed."""
        now = datetime.utcnow()
        elapsed = (now - self.last_update).total_seconds()
        
        # Refill tokens based on elapsed time
        self.tokens = min(
            self.rate,
            self.tokens + (elapsed * self.rate / self.per_seconds)
        )
        self.last_update = now
        
        if self.tokens >= tokens_needed:
            self.tokens -= tokens_needed
            return True
        
        return False

    def wait_until_allowed(self, tokens_needed: int = 1) -> float:
        """Calculate wait time until request allowed."""
        if self.is_allowed(tokens_needed):
            return 0.0
        
        tokens_deficit = tokens_needed - self.tokens
        return (tokens_deficit / self.rate) * self.per_seconds


class SignatureValidator:
    """Validate webhook signatures and API request integrity."""

    @staticmethod
    def validate_signature(
        payload: str,
        signature: str,
        secret: str,
        algorithm: str = "sha256"
    ) -> bool:
        """Validate HMAC signature."""
        expected_signature = hmac.new(
            secret.encode(),
            payload.encode(),
            getattr(hashlib, algorithm)
        ).hexdigest()
        
        # Use constant time comparison to prevent timing attacks
        return hmac.compare_digest(signature, expected_signature)

    @staticmethod
    def generate_signature(payload: str, secret: str, algorithm: str = "sha256") -> str:
        """Generate HMAC signature."""
        return hmac.new(
            secret.encode(),
            payload.encode(),
            getattr(hashlib, algorithm)
        ).hexdigest()


# Global instances
_validator = InputValidator()
_secrets = SecretManager()


def get_validator() -> InputValidator:
    """Get input validator."""
    return _validator


def get_secret_manager() -> SecretManager:
    """Get secret manager."""
    return _secrets
