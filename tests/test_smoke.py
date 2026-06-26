"""Smoke tests: the server must boot and honor the async job contract even with
NO GMI/Respan keys present (AgentBox injects keys only at runtime). These run in
CI before the container image is published.
"""
import sys
from pathlib import Path

from starlette.testclient import TestClient

# Make src/ and repo root importable (mirrors the Dockerfile's PYTHONPATH).
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from web.server import app  # noqa: E402

client = TestClient(app)


def test_health_ok():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_index_serves():
    r = client.get("/")
    assert r.status_code == 200
    assert "<!DOCTYPE html>" in r.text


def test_jobs_async_contract():
    # POST returns 202 + job_id immediately (does not block on the audit).
    r = client.post("/api/jobs")
    assert r.status_code == 202
    body = r.json()
    assert "job_id" in body and body["status"] == "pending"
    # The job is pollable.
    s = client.get(f"/api/jobs/{body['job_id']}")
    assert s.status_code == 200
    assert s.json()["status"] in {"pending", "running", "done", "error"}


def test_unknown_job_404():
    assert client.get("/api/jobs/does-not-exist").status_code == 404


def test_config_normalizes_maas_base_url(monkeypatch):
    # AgentBox injects GMI_MAAS_BASE_URL without /v1; config must append it.
    monkeypatch.setenv("GMI_MAAS_BASE_URL", "https://api.gmi-serving.com")
    monkeypatch.setenv("GMI_MAAS_API_KEY", "test-key")
    import importlib
    import auditor.config as cfg
    importlib.reload(cfg)
    assert cfg.GMI_BASE_URL == "https://api.gmi-serving.com/v1"
    assert cfg.GMI_API_KEY == "test-key"
