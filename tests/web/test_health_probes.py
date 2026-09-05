"""Tests for /livez and /readyz fail-closed health probes."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_livez_probe(client: TestClient) -> None:
    resp = client.get("/livez")
    assert resp.status_code == 200
    assert resp.json() == {"status": "live"}


def test_readyz_probe_demo_mode(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("UNTANGLE_DEPLOY_MODE", "demo")
    resp = client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready", "mode": "demo"}


def test_readyz_probe_private_mode_unconfigured_db(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("UNTANGLE_DEPLOY_MODE", "private")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    resp = client.get("/readyz")
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "unready"
    assert data["mode"] == "private"
    assert "DATABASE_URL not configured" in data["detail"]


def test_readyz_probe_private_mode_healthy_local_storage(
    client: TestClient, web_db_url: str, tmp_path, monkeypatch
) -> None:
    storage_dir = tmp_path / "probe_storage"
    storage_dir.mkdir()
    monkeypatch.setenv("UNTANGLE_DEPLOY_MODE", "private")
    monkeypatch.setenv("DATABASE_URL", web_db_url)
    monkeypatch.setenv("UNTANGLE_STORAGE_BACKEND", "local")
    monkeypatch.setenv("UNTANGLE_STORAGE_DIR", str(storage_dir))

    resp = client.get("/readyz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ready"
    assert data["database"] == "connected"
    assert data["schema"] == "current"


def test_readyz_probe_private_mode_s3_unready(
    client: TestClient, web_db_url: str, monkeypatch
) -> None:
    monkeypatch.setenv("UNTANGLE_DEPLOY_MODE", "private")
    monkeypatch.setenv("DATABASE_URL", web_db_url)
    monkeypatch.setenv("UNTANGLE_STORAGE_BACKEND", "s3")
    monkeypatch.setenv("UNTANGLE_S3_BUCKET", "nonexistent-bucket-probe-12345")
    monkeypatch.setenv("UNTANGLE_S3_ENDPOINT_URL", "http://127.0.0.1:9")  # Unreachable port
    monkeypatch.setenv("UNTANGLE_S3_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("UNTANGLE_S3_SECRET_ACCESS_KEY", "test")

    resp = client.get("/readyz")
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "unready"
    assert data["mode"] == "private"
