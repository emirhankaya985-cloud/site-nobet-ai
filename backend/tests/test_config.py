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


def test_production_worker_does_not_need_browser_cors_or_webhook_secret():
    validate_production_settings(production(
        app_role="worker", cors_origins=[], telegram_bot_token="test-token",
        telegram_webhook_secret="",
    ))


def test_production_rejects_unknown_app_role():
    with pytest.raises(RuntimeError):
        validate_production_settings(production(app_role="unknown"))


def test_production_cron_mode_is_valid():
    validate_production_settings(production(
        app_role="worker", scheduler_mode="cron", cors_origins=[],
    ))


def test_production_rejects_unknown_scheduler():
    with pytest.raises(RuntimeError):
        validate_production_settings(production(scheduler_mode="magic"))
