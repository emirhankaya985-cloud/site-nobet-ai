"""The strict zero-TL policy is machine-checked during every CI run."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_render_blueprint_has_only_free_web_services():
    yaml = (ROOT / "render.yaml").read_text(encoding="utf-8")
    plan_lines = [line.strip() for line in yaml.splitlines() if line.lstrip().startswith("plan:")]
    assert plan_lines == ["plan: free", "plan: free"]
    assert "  - type: worker" not in yaml
    assert "\ndatabases:" not in yaml


def test_free_scheduler_requires_explicit_enable_and_secrets():
    yaml = (ROOT / ".github/workflows/free-monitor.yml").read_text(encoding="utf-8")
    assert "vars.SITENOBET_FREE_MONITOR_ENABLED == 'true'" in yaml
    assert "secrets.SITENOBET_DATABASE_URL" in yaml
    assert "secrets.SITENOBET_SESSION_SECRET" in yaml
    assert "python -m app.worker --once" in yaml
    assert "cancel-in-progress: false" in yaml
