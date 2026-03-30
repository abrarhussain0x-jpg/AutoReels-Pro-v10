"""AutoReels Pro v10 — Production Configuration"""

from pydantic_settings import BaseSettings
from pydantic import Field, validator
from typing import Optional, List
import os

class DatabaseSettings(BaseSettings):
    """PostgreSQL/Supabase configuration"""
    url: str = Field(default="postgresql://localhost/autoreels", env="DATABASE_URL")
    pool_size: int = Field(default=10, env="DB_POOL_SIZE")
    max_overflow: int = Field(default=20, env="DB_MAX_OVERFLOW")
    
    class Config:
        env_prefix = "DB_"

class RedisSettings(BaseSettings):
    """Redis for caching + Celery broker"""
    url: str = Field(default="redis://localhost:6379/0", env="REDIS_URL")
    cache_ttl: int = Field(default=3600, env="REDIS_TTL")
    
    class Config:
        env_prefix = "REDIS_"

class AnthropicSettings(BaseSettings):
    """Claude API configuration"""
    api_key: str = Field(default="", env="ANTHROPIC_API_KEY")
    model: str = Field(default="claude-haiku-4-5-20251001", env="ANTHROPIC_MODEL")
    timeout: int = Field(default=120, env="ANTHROPIC_TIMEOUT")
    max_tokens: int = Field(default=1024, env="ANTHROPIC_MAX_TOKENS")
    
    class Config:
        env_prefix = "ANTHROPIC_"

class FacebookSettings(BaseSettings):
    """Facebook/Instagram configuration"""
    page_ids: List[str] = Field(default=[], env="FB_PAGE_IDS")
    access_tokens: dict = Field(default={}, env="FB_ACCESS_TOKENS")
    api_version: str = Field(default="v18.0", env="FB_API_VERSION")
    daily_limit: int = Field(default=5, env="FB_DAILY_LIMIT")
    
    @validator('page_ids', pre=True)
    def parse_page_ids(cls, v):
        if isinstance(v, str):
            return v.split(',')
        return v
    
    class Config:
        env_prefix = "FB_"

class TikTokSettings(BaseSettings):
    """TikTok configuration"""
    access_token: str = Field(default="", env="TIKTOK_ACCESS_TOKEN")
    client_key: str = Field(default="", env="TIKTOK_CLIENT_KEY")
    client_secret: str = Field(default="", env="TIKTOK_CLIENT_SECRET")
    daily_limit: int = Field(default=3, env="TIKTOK_DAILY_LIMIT")
    
    class Config:
        env_prefix = "TIKTOK_"

class InstagramSettings(BaseSettings):
    """Instagram configuration"""
    user_ids: List[str] = Field(default=[], env="IG_USER_IDS")
    access_tokens: dict = Field(default={}, env="IG_ACCESS_TOKENS")
    daily_limit: int = Field(default=3, env="IG_DAILY_LIMIT")
    
    @validator('user_ids', pre=True)
    def parse_user_ids(cls, v):
        if isinstance(v, str):
            return v.split(',')
        return v
    
    class Config:
        env_prefix = "IG_"

class YouTubeSettings(BaseSettings):
    """YouTube Shorts configuration"""
    client_id: str = Field(default="", env="YOUTUBE_CLIENT_ID")
    client_secret: str = Field(default="", env="YOUTUBE_CLIENT_SECRET")
    refresh_token: str = Field(default="", env="YOUTUBE_REFRESH_TOKEN")
    daily_limit: int = Field(default=3, env="YOUTUBE_DAILY_LIMIT")
    
    class Config:
        env_prefix = "YOUTUBE_"

class NotificationSettings(BaseSettings):
    """Slack, Discord, Telegram, Email"""
    slack_webhook: Optional[str] = Field(default=None, env="SLACK_WEBHOOK")
    discord_webhook: Optional[str] = Field(default=None, env="DISCORD_WEBHOOK")
    telegram_token: Optional[str] = Field(default=None, env="TELEGRAM_TOKEN")
    telegram_chat_id: Optional[str] = Field(default=None, env="TELEGRAM_CHAT_ID")
    email_smtp: Optional[str] = Field(default=None, env="EMAIL_SMTP")
    email_from: Optional[str] = Field(default=None, env="EMAIL_FROM")
    email_password: Optional[str] = Field(default=None, env="EMAIL_PASSWORD")
    
    class Config:
        env_prefix = "NOTIF_"

class SentrySettings(BaseSettings):
    """Error tracking with Sentry"""
    dsn: Optional[str] = Field(default=None, env="SENTRY_DSN")
    environment: str = Field(default="production", env="SENTRY_ENV")
    traces_sample_rate: float = Field(default=0.1, env="SENTRY_TRACES_RATE")
    profiles_sample_rate: float = Field(default=0.1, env="SENTRY_PROFILES_RATE")
    
    class Config:
        env_prefix = "SENTRY_"

class Settings(BaseSettings):
    """Root configuration"""
    # Application
    app_name: str = Field(default="AutoReels Pro v10", env="APP_NAME")
    environment: str = Field(default="production", env="ENVIRONMENT")
    debug: bool = Field(default=False, env="DEBUG")
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    
    # Features
    dry_run: bool = Field(default=False, env="DRY_RUN")
    force_run: bool = Field(default=False, env="FORCE_RUN")
    no_web: bool = Field(default=False, env="NO_WEB")
    
    # Processing
    video_cache_dir: str = Field(default="/tmp/autoreels-cache", env="VIDEO_CACHE_DIR")
    max_workers: int = Field(default=4, env="MAX_WORKERS")
    
    # Sub-configurations
    database: DatabaseSettings = DatabaseSettings()
    redis: RedisSettings = RedisSettings()
    anthropic: AnthropicSettings = AnthropicSettings()
    facebook: FacebookSettings = FacebookSettings()
    tiktok: TikTokSettings = TikTokSettings()
    instagram: InstagramSettings = InstagramSettings()
    youtube: YouTubeSettings = YouTubeSettings()
    notifications: NotificationSettings = NotificationSettings()
    sentry: SentrySettings = SentrySettings()
    
    class Config:
        env_file = '.env'
        case_sensitive = False

# ── SINGLETON INSTANCE ──────────────────────────────

_settings = None

def get_settings() -> Settings:
    """Get or create settings singleton"""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings

def validate_settings() -> dict:
    """Validate required settings are present"""
    settings = get_settings()
    errors = []
    
    if not settings.anthropic.api_key:
        errors.append("ANTHROPIC_API_KEY is required")
    
    if settings.environment == "production":
        if not settings.database.url:
            errors.append("DATABASE_URL is required in production")
        if not settings.sentry.dsn:
            errors.append("SENTRY_DSN is required in production")
    
    if not settings.facebook.page_ids and not settings.tiktok.access_token:
        errors.append("At least one platform must be configured")
    
    return {
        'valid': len(errors) == 0,
        'errors': errors,
        'warnings': [
            "DRY_RUN mode enabled" if settings.dry_run else None,
            "Debug mode enabled" if settings.debug else None,
        ]
    }
