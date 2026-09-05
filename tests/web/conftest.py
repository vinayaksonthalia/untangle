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
    auth_url = os.environ.get("POSTGRES_AUTH_TEST_URL", "").strip() or web_db_url
    maintenance_url = os.environ.get("POSTGRES_MAINTENANCE_TEST_URL", "").strip() or web_db_url
    monkeypatch.setenv("DATABASE_URL", web_db_url)
    monkeypatch.setenv("AUTH_DATABASE_URL", auth_url)
    monkeypatch.setenv("MAINTENANCE_DATABASE_URL", maintenance_url)
    monkeypatch.setenv("OIDC_ISSUER_URL", mock_idp.issuer_url)
    monkeypatch.setenv("OIDC_CLIENT_ID", mock_idp.client_id)
    monkeypatch.setenv("OIDC_CLIENT_SECRET", mock_idp.client_secret)
    monkeypatch.setenv("UNTANGLE_DEV_MODE", "1")
    monkeypatch.setenv("UNTANGLE_SECRET_KEY", "test-secret-key-12345678901234567890")

    app.state.oidc_http_client = mock_idp.create_mock_client()
    yield
    del app.state.oidc_http_client


@pytest.fixture(scope="session")
def web_engine(web_db_url: str) -> Generator[Engine, None, None]:
    eng = create_db_engine(web_db_url)
    yield eng
    eng.dispose()


@pytest.fixture(scope="session")
def web_session_factory(web_engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(web_engine)


@pytest.fixture(scope="session")
def web_auth_session_factory(web_db_url: str) -> Generator[sessionmaker[Session], None, None]:
    """Factory bound to the auth role, which owns EXECUTE on the pre-auth
    session functions (fn_auth_create_session, ...). The runtime app role is
    denied those, so tests must mint session tokens through this factory."""
    auth_url = os.environ.get("POSTGRES_AUTH_TEST_URL", "").strip() or web_db_url
    eng = create_db_engine(auth_url)
    yield create_session_factory(eng)
    eng.dispose()


@pytest.fixture
def session(web_auth_session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    sess = web_auth_session_factory()
    yield sess
    sess.rollback()
    sess.close()


@pytest.fixture(scope="session")
def seed_session_factory(web_db_url: str) -> Generator[sessionmaker[Session], None, None]:
    """Privileged factory for seeding control-plane rows in tests.

    The runtime app role (POSTGRES_TEST_URL) is intentionally denied direct
    INSERTs into control-plane tables, so test setup must seed as the schema
    owner (POSTGRES_MIGRATION_TEST_URL). SQLite has no role separation, so it
    falls back to the same database URL.
    """
    seed_url = os.environ.get("POSTGRES_MIGRATION_TEST_URL", "").strip() or web_db_url
    eng = create_db_engine(seed_url)
    yield create_session_factory(eng)
    eng.dispose()


@pytest.fixture
def seed_issuer(
    seed_session_factory: sessionmaker[Session], mock_idp: MockOidcServer
) -> TrustedAuthIssuer:
    with seed_session_factory() as seed:
        issuer = seed.query(TrustedAuthIssuer).filter_by(issuer_url=mock_idp.issuer_url).first()
        if not issuer:
            issuer = TrustedAuthIssuer(
                issuer_url=mock_idp.issuer_url,
                client_id=mock_idp.client_id,
                description="Mock Test IdP",
                is_active=True,
            )
            seed.add(issuer)
            seed.commit()
        seed.refresh(issuer)
        seed.expunge(issuer)
    return issuer


@pytest.fixture
def tenant_a(seed_session_factory: sessionmaker[Session]) -> tuple[TenantContext, int]:
    from persistence.repositories.control_plane import (
        create_membership,
        create_organisation,
        create_principal,
        issue_tenant_context,
    )

    with seed_session_factory() as seed:
        org = create_organisation(seed, "Organisation Alpha Web")
        user = create_principal(seed, "alice@alpha.test", "Alice Alpha")
        create_membership(seed, org.id, user.id, Role.OWNER)
        seed.commit()

        ctx = issue_tenant_context(seed, user.id, org.id, request_id="req_alpha_web_001")
        org_id = org.id
    return ctx, org_id


@pytest.fixture
def tenant_b(seed_session_factory: sessionmaker[Session]) -> tuple[TenantContext, int]:
    from persistence.repositories.control_plane import (
        create_membership,
        create_organisation,
        create_principal,
        issue_tenant_context,
    )

    with seed_session_factory() as seed:
        org = create_organisation(seed, "Organisation Beta Web")
        user = create_principal(seed, "bob@beta.test", "Bob Beta")
        create_membership(seed, org.id, user.id, Role.OWNER)
        seed.commit()

        ctx = issue_tenant_context(seed, user.id, org.id, request_id="req_beta_web_001")
        org_id = org.id
    return ctx, org_id


@pytest.fixture
def sample_file_bytes() -> tuple[bytes, bytes, bytes]:
    """Load sample dataset files for web testing."""
    data_dir = "data"
    bank_p = os.path.join(data_dir, "bank_statement.csv")
    recon_p = os.path.join(data_dir, "recon_report.json")
    ledger_p = os.path.join(data_dir, "order_ledger.csv")

    if not (os.path.exists(bank_p) and os.path.exists(recon_p) and os.path.exists(ledger_p)):
        import tempfile

        from generator.config import Config
        from generator.demo_dataset import write_demo_dataset

        tmp = tempfile.mkdtemp()
        base = write_demo_dataset(tmp, Config())
        bank_p = os.path.join(base, "bank_statement.csv")
        recon_p = os.path.join(base, "recon_report.json")
        ledger_p = os.path.join(base, "order_ledger.csv")

    with open(bank_p, "rb") as f:
        b_data = f.read()
    with open(recon_p, "rb") as f:
        r_data = f.read()
    with open(ledger_p, "rb") as f:
        l_data = f.read()
    return b_data, r_data, l_data


def auth_headers(
    raw_token: str, secret_key: str = "test-secret-key-12345678901234567890"
) -> dict[str, str]:
    from auth.crypto import generate_csrf_token, hash_token

    token_hash = hash_token(raw_token)
    csrf_token = generate_csrf_token(secret_key, token_hash)
    return {
        "Origin": "http://localhost:8080",
        "X-CSRF-Token": csrf_token,
    }


@pytest.fixture(scope="session")
def client() -> Generator[TestClient, None, None]:
    with TestClient(app, base_url="http://localhost:8080") as c:
        yield c


@pytest.fixture(autouse=True)
def reset_client_cookies(client: TestClient) -> None:
    client.cookies.clear()
