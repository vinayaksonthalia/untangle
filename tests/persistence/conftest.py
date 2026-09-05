"""Pytest fixtures for persistence and tenant isolation tests.

Provides isolated test database instances (PostgreSQL if POSTGRES_TEST_URL is set;
otherwise SQLite in-memory with foreign keys enabled).
"""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from persistence.config import create_db_engine, create_session_factory
from persistence.context import Role, TenantContext
from persistence.models import Base
from persistence.repositories.control_plane import (
    create_membership,
    create_organisation,
    create_principal,
    issue_tenant_context,
)


@pytest.fixture(scope="session")
def db_url() -> str:
    """Return the database URL for testing."""
    postgres_url = os.environ.get("POSTGRES_TEST_URL", "").strip()
    if postgres_url:
        return postgres_url
    return "sqlite:///:memory:"


@pytest.fixture(scope="session")
def migration_db_url(db_url: str) -> str:
    """Return the privileged URL used for migrations and control-plane fixtures."""
    return os.environ.get("POSTGRES_MIGRATION_TEST_URL", "").strip() or db_url


@pytest.fixture(scope="session")
def control_db_url(migration_db_url: str) -> str:
    """Return the test-only administrative URL used to seed control-plane records."""
    return os.environ.get("POSTGRES_CONTROL_TEST_URL", "").strip() or migration_db_url


@pytest.fixture(scope="session")
def auth_db_url(db_url: str) -> str:
    """Return the URL for untangle_auth restricted connection."""
    return os.environ.get("POSTGRES_AUTH_TEST_URL", "").strip() or db_url


@pytest.fixture(scope="session")
def maintenance_db_url(db_url: str) -> str:
    """Return the URL for untangle_maintenance restricted connection."""
    return os.environ.get("POSTGRES_MAINTENANCE_TEST_URL", "").strip() or db_url


@pytest.fixture(scope="session")
def worker_db_url(db_url: str) -> str:
    """Return the URL for untangle_worker restricted connection."""
    return os.environ.get("POSTGRES_WORKER_TEST_URL", "").strip() or db_url


@pytest.fixture(scope="session")
def is_postgres(db_url: str) -> bool:
    """Return True if testing against PostgreSQL."""
    return db_url.startswith("postgresql")


@pytest.fixture(scope="session")
def engine(db_url: str, migration_db_url: str, is_postgres: bool) -> Generator[Engine, None, None]:
    """Create and prepare test database schema."""
    test_engine = create_db_engine(db_url)

    if is_postgres:
        from persistence.migrate import upgrade_head

        # Run full Alembic migrations on PostgreSQL
        upgrade_head(migration_db_url)
    else:
        # Create all tables on SQLite
        Base.metadata.create_all(test_engine)

        # Seed roles on SQLite
        from persistence.models import RoleModel

        with Session(test_engine) as session:
            for code, desc in [
                ("owner", "Owner"),
                ("admin", "Admin"),
                ("operator", "Operator"),
                ("reviewer", "Reviewer"),
                ("auditor", "Auditor"),
            ]:
                session.add(RoleModel(code=code, description=desc))
            session.commit()

    yield test_engine

    if not is_postgres:
        Base.metadata.drop_all(test_engine)
    test_engine.dispose()


@pytest.fixture(scope="session")
def control_engine(
    engine: Engine, control_db_url: str, is_postgres: bool
) -> Generator[Engine, None, None]:
    """Use the privileged connection only to seed the unauthenticated control plane."""
    if not is_postgres:
        yield engine
        return
    privileged_engine = create_db_engine(control_db_url)
    yield privileged_engine
    privileged_engine.dispose()


@pytest.fixture(scope="session")
def auth_engine(
    engine: Engine, auth_db_url: str, is_postgres: bool
) -> Generator[Engine, None, None]:
    """Engine using untangle_auth role."""
    if not is_postgres:
        yield engine
        return
    role_engine = create_db_engine(auth_db_url)
    yield role_engine
    role_engine.dispose()


@pytest.fixture(scope="session")
def maintenance_engine(
    engine: Engine, maintenance_db_url: str, is_postgres: bool
) -> Generator[Engine, None, None]:
    """Engine using untangle_maintenance role."""
    if not is_postgres:
        yield engine
        return
    role_engine = create_db_engine(maintenance_db_url)
    yield role_engine
    role_engine.dispose()


@pytest.fixture(scope="session")
def worker_engine(
    engine: Engine, worker_db_url: str, is_postgres: bool
) -> Generator[Engine, None, None]:
    """Engine using untangle_worker role."""
    if not is_postgres:
        yield engine
        return
    role_engine = create_db_engine(worker_db_url)
    yield role_engine
    role_engine.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return session factory bound to the test engine."""
    return create_session_factory(engine)


@pytest.fixture
def control_session_factory(control_engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(control_engine)


@pytest.fixture
def auth_session_factory(auth_engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(auth_engine)


@pytest.fixture
def maintenance_session_factory(maintenance_engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(maintenance_engine)


@pytest.fixture
def worker_session_factory(worker_engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(worker_engine)


@pytest.fixture
def session(control_session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    """Provide a clean session wrapped in an outer transaction for isolation."""
    sess = control_session_factory()
    yield sess
    sess.rollback()
    sess.close()


@pytest.fixture
def auth_session(auth_session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    sess = auth_session_factory()
    yield sess
    sess.rollback()
    sess.close()


@pytest.fixture
def maintenance_session(
    maintenance_session_factory: sessionmaker[Session],
) -> Generator[Session, None, None]:
    sess = maintenance_session_factory()
    yield sess
    sess.rollback()
    sess.close()


@pytest.fixture
def tenant_a(session: Session) -> tuple[TenantContext, int]:
    """Create Organisation A with an owner principal and return its TenantContext."""
    org = create_organisation(session, "Organisation Alpha")
    user = create_principal(session, "alice@alpha.test", "Alice Alpha")
    create_membership(session, org.id, user.id, Role.OWNER)
    session.commit()

    ctx = issue_tenant_context(session, user.id, org.id, request_id="req_alpha_001")
    return ctx, org.id


@pytest.fixture
def tenant_b(session: Session) -> tuple[TenantContext, int]:
    """Create Organisation B with an owner principal and return its TenantContext."""
    org = create_organisation(session, "Organisation Beta")
    user = create_principal(session, "bob@beta.test", "Bob Beta")
    create_membership(session, org.id, user.id, Role.OWNER)
    session.commit()

    ctx = issue_tenant_context(session, user.id, org.id, request_id="req_beta_001")
    return ctx, org.id


@pytest.fixture
def sample_file_bytes() -> tuple[bytes, bytes, bytes]:
    """Load sample dataset files for testing."""
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
