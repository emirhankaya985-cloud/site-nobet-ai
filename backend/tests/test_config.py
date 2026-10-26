import pytest

from app.config import Settings, validate_production_settings


def production(**overrides):
    values = {
        "environment": "production",
        "database_url": "postgresql://user:password@db/sitenobet",
        "session_secret": "long-random-production-test-secret-at-least-32",
        "cors_origins": ["https://dashboard.example.org"],
        "telegram_bot_token": "",
        "telegram_webhook_secret": "",
        "ntfy_base_url": "https://ntfy.sh",
    }
    values.update(overrides)
    return Settings(**values)


def test_production_settings_accept_explicit_https():
    validate_production_settings(production())


@pytest.mark.parametrize("overrides", [
    {"session_secret": "weak"},
    {"database_url": "sqlite:///tmp.db"},
    {"cors_origins": []},
    {"cors_origins": ["*"]},
    {"cors_origins": ["http://public.example.org"]},
    {"cors_origins": ["https://public.example.org/path"]},
    {"ntfy_base_url": "http://ntfy.example.org"},
    {"telegram_bot_token": "test-token", "telegram_webhook_secret": ""},
])
def test_production_settings_reject_unsafe_config(overrides):
    with pytest.raises(RuntimeError):
        validate_production_settings(production(**overrides))
