"""Hosted deployments must not silently use development cryptographic secrets."""

from types import SimpleNamespace

import pytest

from webapp.auth_routes import get_oidc_manager
from webapp.middleware import DEFAULT_DEV_SECRET, get_app_secret_key


def test_app_secret_allows_explicit_local_fallback(monkeypatch):
    monkeypatch.delenv("UNTANGLE_SECRET_KEY", raising=False)
    monkeypatch.setenv("UNTANGLE_ENV", "local")
    assert get_app_secret_key() == DEFAULT_DEV_SECRET


def test_app_secret_requires_configuration_when_hosted(monkeypatch):
    monkeypatch.delenv("UNTANGLE_SECRET_KEY", raising=False)
    monkeypatch.delenv("UNTANGLE_ENV", raising=False)
    monkeypatch.delenv("UNTANGLE_DEV_MODE", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/app")
    with pytest.raises(RuntimeError, match="UNTANGLE_SECRET_KEY"):
        get_app_secret_key()


def test_app_secret_rejects_committed_default_when_hosted(monkeypatch):
    monkeypatch.setenv("UNTANGLE_SECRET_KEY", DEFAULT_DEV_SECRET)
    monkeypatch.delenv("UNTANGLE_ENV", raising=False)
    monkeypatch.delenv("UNTANGLE_DEV_MODE", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/app")
    with pytest.raises(RuntimeError, match="UNTANGLE_SECRET_KEY"):
        get_app_secret_key()


def test_oidc_secret_requires_configuration_when_hosted(monkeypatch):
    monkeypatch.delenv("OIDC_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("UNTANGLE_ENV", raising=False)
    monkeypatch.delenv("UNTANGLE_DEV_MODE", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/app")
    with pytest.raises(RuntimeError, match="OIDC_CLIENT_SECRET"):
        get_oidc_manager(SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())))


def test_oidc_rejects_committed_default_secret_when_hosted(monkeypatch):
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "dev_secret")
    monkeypatch.setenv("UNTANGLE_SECRET_KEY", "a-real-app-secret-for-this-test")
    monkeypatch.delenv("UNTANGLE_ENV", raising=False)
    monkeypatch.delenv("UNTANGLE_DEV_MODE", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/app")
    with pytest.raises(RuntimeError, match="OIDC_CLIENT_SECRET"):
        get_oidc_manager(SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())))
