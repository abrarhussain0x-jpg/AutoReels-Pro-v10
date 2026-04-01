"""Runtime smoke tests for core API and CLI entrypoints."""

from pathlib import Path
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def api_client():
    from src.api import app

    with TestClient(app) as client:
        yield client


@pytest.mark.smoke
def test_api_health_endpoint_smoke(api_client):
    """API app should boot and serve health endpoint."""
    response = api_client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload.get("status") == "alive"


@pytest.mark.smoke
def test_api_ready_endpoint_smoke(api_client):
    """Readiness endpoint should be available after startup."""
    response = api_client.get("/ready")
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("status") == "ready"


@pytest.mark.smoke
def test_api_status_endpoint_smoke(api_client):
    """Status endpoint should return operational payload."""
    response = api_client.get("/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("status") == "operational"


@pytest.mark.smoke
def test_api_admin_queue_requires_key(api_client):
    """Admin queue endpoint must reject unauthenticated requests."""
    response = api_client.get("/api/v1/admin/queue")
    assert response.status_code in (403, 503)


@pytest.mark.smoke
def test_main_help_smoke():
    """CLI should render help successfully."""
    result = subprocess.run(
        [sys.executable, "main.py", "--help"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0
    assert "AUTO-REELS PRO" in result.stdout


@pytest.mark.smoke
def test_main_queue_status_smoke():
    """CLI queue status command should run without crashing."""
    result = subprocess.run(
        [sys.executable, "main.py", "--queue-status"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0
    assert "JOB QUEUE STATUS" in result.stdout


@pytest.mark.smoke
def test_main_preflight_smoke():
    """Strict preflight should pass with required env vars set."""
    env = dict(**__import__("os").environ)
    env["FB_PAGE_ID"] = "123456789"
    env["FB_PAGE_ACCESS_TOKEN"] = "test_token"

    result = subprocess.run(
        [sys.executable, "main.py", "--preflight"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )

    assert result.returncode == 0
    assert "PREFLIGHT CHECK" in result.stdout
    assert "Result: OK" in result.stdout


@pytest.mark.smoke
def test_validate_env_dry_run_smoke():
    """Env validator should pass dry-run mode with minimal required vars."""
    env = dict(**__import__("os").environ)
    env["ENVIRONMENT"] = "testing"

    result = subprocess.run(
        [sys.executable, "validate_env.py", "--mode", "dry-run"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )

    assert result.returncode == 0
    assert "Result: OK" in result.stdout


@pytest.mark.smoke
def test_validate_env_real_run_smoke():
    """Env validator should pass real-run mode when required vars are present."""
    env = dict(**__import__("os").environ)
    env["ENVIRONMENT"] = "testing"
    env["FB_PAGE_ID"] = "123456789"
    env["FB_PAGE_ACCESS_TOKEN"] = "test_token"

    result = subprocess.run(
        [sys.executable, "validate_env.py", "--mode", "real-run"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )

    assert result.returncode == 0
    assert "Result: OK" in result.stdout
