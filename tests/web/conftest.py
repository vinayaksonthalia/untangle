"""Web test fixtures and TestClient configuration."""

import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from persistence.config import create_db_engine, create_session_factory
from persistence.context import Role, TenantContext
from persistence.migrate import upgrade_head
from persistence.models import RoleModel, TrustedAuthIssuer
from tests.fixtures.mock_oidc import MockOidcServer
from webapp.app import app


@pytest.fixture(scope="session")
def mock_idp() -> MockOidcServer:
    return MockOidcServer(
        issuer_url="https://auth.untangle.internal",
        client_id="untangle_client",
        client_secret="dev_secret",
    )


@pytest.fixture(scope="session")
def web_db_url(tmp_path_factory: pytest.TempPathFactory) -> Generator[str, None, None]:
    postgres_url = os.environ.get("POSTGRES_TEST_URL", "").strip()
    if postgres_url:
        yield postgres_url
        return

    db_dir = tmp_path_factory.mktemp("web_db")
    db_file = db_dir / "web_test.db"
    url = f"sqlite:///{db_file}"
    upgrade_head(url)

    engine = create_db_engine(url)
    with Session(engine) as session:
        for code, desc in [
            ("owner", "Owner"),
            ("admin", "Admin"),
            ("operator", "Operator"),
            ("reviewer", "Reviewer"),
            ("auditor", "Auditor"),
        ]:
            if not session.query(RoleModel).filter_by(code=code).first():
                session.add(RoleModel(code=code, description=desc))
        session.commit()
    engine.dispose()

    yield url


@pytest.fixture(autouse=True)
def configure_auth_env(
    web_db_url: str, mock_idp: MockOidcServer, monkeypatch
) -> Generator[None, None, None]:
    """Ensure environment points to the active test database and mock IdP."""
    from webapp.auth_routes import set_oidc_http_client

    monkeypatch.setenv("DATABASE_URL", web_db_url)
    monkeypatch.setenv("AUTH_DATABASE_URL", web_db_url)
    monkeypatch.setenv("MAINTENANCE_DATABASE_URL", web_db_url)
    monkeypatch.setenv("OIDC_ISSUER_URL", mock_idp.issuer_url)
    monkeypatch.setenv("OIDC_CLIENT_ID", mock_idp.client_id)
    monkeypatch.setenv("OIDC_CLIENT_SECRET", mock_idp.client_secret)
    monkeypatch.setenv("UNTANGLE_DEV_MODE", "1")
    monkeypatch.setenv("UNTANGLE_SECRET_KEY", "test-secret-key-12345678901234567890")

    set_oidc_http_client(mock_idp.create_mock_client())
    yield
    set_oidc_http_client(None)


@pytest.fixture(scope="session")
def web_engine(web_db_url: str) -> Generator[Engine, None, None]:
    eng = create_db_engine(web_db_url)
    yield eng
    eng.dispose()


@pytest.fixture(scope="session")
def web_session_factory(web_engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(web_engine)


@pytest.fixture
def session(web_session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    sess = web_session_factory()
    yield sess
    sess.rollback()
    sess.close()


@pytest.fixture
def seed_issuer(session: Session, mock_idp: MockOidcServer) -> TrustedAuthIssuer:
    issuer = session.query(TrustedAuthIssuer).filter_by(issuer_url=mock_idp.issuer_url).first()
    if not issuer:
        issuer = TrustedAuthIssuer(
            issuer_url=mock_idp.issuer_url,
            client_id=mock_idp.client_id,
            description="Mock Test IdP",
            is_active=True,
        )
        session.add(issuer)
        session.commit()
    return issuer


@pytest.fixture
def tenant_a(session: Session) -> tuple[TenantContext, int]:
    from persistence.repositories.control_plane import (
        create_membership,
        create_organisation,
        create_principal,
        issue_tenant_context,
    )

    org = create_organisation(session, "Organisation Alpha Web")
    user = create_principal(session, "alice@alpha.test", "Alice Alpha")
    create_membership(session, org.id, user.id, Role.OWNER)
    session.commit()

    ctx = issue_tenant_context(session, user.id, org.id, request_id="req_alpha_web_001")
    return ctx, org.id


@pytest.fixture(scope="session")
def client() -> Generator[TestClient, None, None]:
    with TestClient(app, base_url="http://localhost:8080") as c:
        yield c


@pytest.fixture(autouse=True)
def reset_client_cookies(client: TestClient) -> None:
    client.cookies.clear()
