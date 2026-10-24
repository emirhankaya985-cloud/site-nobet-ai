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


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.environment == "production" and (settings.session_secret == "development-only-change-this-secret" or len(settings.session_secret) < 32):
        raise RuntimeError("SESSION_SECRET must be at least 32 characters in production")
    if settings.environment == "production" and not settings.database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise RuntimeError("PostgreSQL DATABASE_URL required in production")
    return settings
