import os
from functools import lru_cache

from pydantic import BaseModel


class Settings(BaseModel):
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./sitenobet.db")
    session_secret: str = os.getenv("SESSION_SECRET", "development-only-change-this-secret")
    cors_origins: list[str] = [x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if x.strip()]
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_webhook_secret: str = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    ntfy_base_url: str = os.getenv("NTFY_BASE_URL", "https://ntfy.sh")
    environment: str = os.getenv("APP_ENV", "development")
    check_timeout: int = 10


def validate_production_settings(settings: Settings) -> None:
    """Fail closed before the server starts if runtime config is unsafe."""
    if settings.environment != "production":
        return
    if settings.session_secret == "development-only-change-this-secret" or len(settings.session_secret) < 32:
        raise RuntimeError("SESSION_SECRET must be strong (32+ characters) in production")
    if not settings.database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise RuntimeError("PostgreSQL DATABASE_URL required in production")
    if not settings.cors_origins:
        raise RuntimeError("Set explicit HTTPS CORS_ORIGINS in production")
    from urllib.parse import urlsplit
    for origin in settings.cors_origins:
        parsed = urlsplit(origin)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment
                or "*" in origin):
            raise RuntimeError("Production CORS_ORIGINS must be explicit HTTPS origins")
    target = urlsplit(settings.ntfy_base_url)
    if target.scheme != "https" or not target.hostname or target.username or target.password or target.query or target.fragment:
        raise RuntimeError("Production NTFY_BASE_URL must be an HTTPS endpoint without credentials")
    if settings.telegram_bot_token and len(settings.telegram_webhook_secret) < 16:
        raise RuntimeError("TELEGRAM_WEBHOOK_SECRET required when Telegram is enabled")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    validate_production_settings(settings)
    return settings
