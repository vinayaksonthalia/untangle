"""Tests for OpenID Connect (OIDC) PKCE flow and identity resolution."""

from __future__ import annotations

import urllib.parse

import pytest
from sqlalchemy.orm import Session

from auth.oidc import (
    IdentityCollisionError,
    OidcManager,
    OidcStateError,
    OidcTokenError,
    UnverifiedEmailError,
)
from persistence.models import Principal, TrustedAuthIssuer
from tests.fixtures.mock_oidc import MockOidcServer


def _extract_nonce(auth_url: str) -> str:
    parsed = urllib.parse.urlparse(auth_url)
    return urllib.parse.parse_qs(parsed.query)["nonce"][0]


@pytest.fixture
def mock_idp() -> MockOidcServer:
    return MockOidcServer(
        issuer_url="https://auth.untangle.internal",
        client_id="untangle_client",
        client_secret="dev_secret",
    )


@pytest.fixture
def oidc_manager(mock_idp: MockOidcServer) -> OidcManager:
    return OidcManager(
        issuer_url=mock_idp.issuer_url,
        client_id=mock_idp.client_id,
        client_secret=mock_idp.client_secret,
        redirect_uri="http://localhost:8080/api/auth/callback",
        secret_key="super-secret-encryption-key-for-test-12345",
        http_client=mock_idp.create_mock_client(),
    )


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


def test_oidc_authorization_flow_initiation(
    session: Session,
    oidc_manager: OidcManager,
    seed_issuer: TrustedAuthIssuer,
) -> None:
    auth_url, state = oidc_manager.create_authorization_flow(
        session, return_to="/dashboard", ip_address="127.0.0.1", user_agent="TestBrowser/1.0"
    )
    assert auth_url.startswith("https://auth.untangle.internal/authorize?")
    assert "state=" in auth_url
    assert "code_challenge=" in auth_url
    assert "code_challenge_method=S256" in auth_url
    assert "response_type=code" in auth_url
    assert len(state) >= 32


def test_oidc_callback_successful_new_principal(
    session: Session,
    oidc_manager: OidcManager,
    mock_idp: MockOidcServer,
    seed_issuer: TrustedAuthIssuer,
) -> None:
    auth_url, state = oidc_manager.create_authorization_flow(session, return_to="/dashboard")
    nonce = _extract_nonce(auth_url)
    code = "test_auth_code_123"
    mock_idp.register_code(
        code=code,
        sub="idp_sub_alpha",
        email="alice_oidc@alpha.test",
        email_verified=True,
        name="Alice Alpha",
        nonce=nonce,
    )

    principal_id, principal_pub_id, return_to = oidc_manager.process_callback(
        session, code=code, state=state
    )
    assert principal_id > 0
    assert principal_pub_id.startswith("usr_")
    assert return_to == "/dashboard"

    principal = session.get(Principal, principal_id)
    assert principal is not None
    assert principal.email == "alice_oidc@alpha.test"
    assert principal.display_name == "Alice Alpha"


@pytest.mark.parametrize(
    ("aud", "azp", "sub", "error"),
    [
        ("other_client", None, "scalar-mismatch", "Audience mismatch"),
        ("untangle_client", "other_client", "scalar-wrong-azp", "azp claim"),
        (["untangle_client", "other_client"], None, "multi-missing-azp", "azp claim"),
        (["untangle_client", "other_client"], "other_client", "multi-wrong-azp", "azp claim"),
        ("untangle_client", None, None, "Missing subject"),
        ("untangle_client", None, "", "Missing subject"),
    ],
)
def test_oidc_callback_rejects_invalid_claim_combinations(
    session: Session,
    oidc_manager: OidcManager,
    mock_idp: MockOidcServer,
    seed_issuer: TrustedAuthIssuer,
    aud: str | list[str],
    azp: str | None,
    sub: str | None,
    error: str,
) -> None:
    auth_url, state = oidc_manager.create_authorization_flow(session)
    nonce = _extract_nonce(auth_url)
    claims = {"aud": aud, "sub": sub}
    if azp is not None:
        claims["azp"] = azp
    mock_idp.register_code(
        code=f"invalid-{error}-{str(aud)}-{sub}",
        sub="fallback-sub",
        email="claims@test.com",
        email_verified=True,
        nonce=nonce,
        custom_claims=claims,
    )
    with pytest.raises(OidcTokenError, match=error):
        oidc_manager.process_callback(
            session, code=f"invalid-{error}-{str(aud)}-{sub}", state=state
        )


@pytest.mark.parametrize(
    ("aud", "azp"),
    [
        ("untangle_client", None),
        (["untangle_client"], None),
        (["untangle_client", "other"], "untangle_client"),
    ],
)
def test_oidc_callback_accepts_valid_audience_and_authorized_party(
    session: Session,
    oidc_manager: OidcManager,
    mock_idp: MockOidcServer,
    seed_issuer: TrustedAuthIssuer,
    aud: str | list[str],
    azp: str | None,
) -> None:
    auth_url, state = oidc_manager.create_authorization_flow(session)
    nonce = _extract_nonce(auth_url)
    claims: dict[str, object] = {"aud": aud, "sub": f"valid-{str(aud)}"}
    if azp is not None:
        claims["azp"] = azp
    code = f"valid-{len(mock_idp.issued_codes)}-{id(session)}"
    mock_idp.register_code(
        code=code,
        sub="fallback",
        email=f"{code}-{id(aud)}@test.com",
        email_verified=True,
        nonce=nonce,
        custom_claims=claims,
    )
    principal_id, _, _ = oidc_manager.process_callback(session, code=code, state=state)
    assert principal_id > 0


def test_oidc_callback_existing_principal_login(
    session: Session,
    oidc_manager: OidcManager,
    mock_idp: MockOidcServer,
    seed_issuer: TrustedAuthIssuer,
) -> None:
    # First login
    auth_url1, state1 = oidc_manager.create_authorization_flow(session)
    nonce1 = _extract_nonce(auth_url1)
    mock_idp.register_code(
        code="code_1",
        sub="idp_sub_bob",
        email="bob_oidc@beta.test",
        email_verified=True,
        name="Bob Beta",
        nonce=nonce1,
    )
    pid1, pub_id1, _ = oidc_manager.process_callback(session, code="code_1", state=state1)

    # Second login with same IdP subject
    auth_url2, state2 = oidc_manager.create_authorization_flow(session)
    nonce2 = _extract_nonce(auth_url2)
    mock_idp.register_code(
        code="code_2",
        sub="idp_sub_bob",
        email="bob_oidc@beta.test",
        email_verified=True,
        name="Bob Updated",
        nonce=nonce2,
    )
    pid2, pub_id2, _ = oidc_manager.process_callback(session, code="code_2", state=state2)

    assert pid1 == pid2
    assert pub_id1 == pub_id2


def test_oidc_callback_invalid_or_replayed_state(
    session: Session,
    oidc_manager: OidcManager,
    mock_idp: MockOidcServer,
    seed_issuer: TrustedAuthIssuer,
) -> None:
    with pytest.raises(OidcStateError, match="Invalid, expired, or previously consumed"):
        oidc_manager.process_callback(session, code="some_code", state="non_existent_state")


def test_oidc_callback_state_single_use(
    session: Session,
    oidc_manager: OidcManager,
    mock_idp: MockOidcServer,
    seed_issuer: TrustedAuthIssuer,
) -> None:
    auth_url, state = oidc_manager.create_authorization_flow(session)
    nonce = _extract_nonce(auth_url)
    mock_idp.register_code(code="code_once", sub="sub_once", email="once@test.com", nonce=nonce)

    oidc_manager.process_callback(session, code="code_once", state=state)

    # Replaying same state must fail
    with pytest.raises(OidcStateError):
        oidc_manager.process_callback(session, code="code_once", state=state)


def test_oidc_callback_unverified_email_rejected(
    session: Session,
    oidc_manager: OidcManager,
    mock_idp: MockOidcServer,
    seed_issuer: TrustedAuthIssuer,
) -> None:
    auth_url, state = oidc_manager.create_authorization_flow(session)
    nonce = _extract_nonce(auth_url)
    mock_idp.register_code(
        code="code_unverified",
        sub="sub_unverified",
        email="unverified@test.com",
        email_verified=False,
        nonce=nonce,
    )
    with pytest.raises(UnverifiedEmailError, match="verified"):
        oidc_manager.process_callback(session, code="code_unverified", state=state)


def test_oidc_callback_identity_collision_rejected(
    session: Session,
    oidc_manager: OidcManager,
    mock_idp: MockOidcServer,
    seed_issuer: TrustedAuthIssuer,
) -> None:
    # Pre-create a principal with email charlie@test.com manually
    from persistence.ids import PREFIX_PRINCIPAL, generate_public_id

    existing = Principal(
        public_id=generate_public_id(PREFIX_PRINCIPAL),
        email="charlie@test.com",
        display_name="Charlie Manual",
        is_active=True,
    )
    session.add(existing)
    session.commit()

    # Now attempt OIDC login with a NEW sub claiming charlie@test.com
    auth_url, state = oidc_manager.create_authorization_flow(session)
    nonce = _extract_nonce(auth_url)
    mock_idp.register_code(
        code="code_collision",
        sub="sub_different_charlie",
        email="charlie@test.com",
        email_verified=True,
        nonce=nonce,
    )

    with pytest.raises(IdentityCollisionError, match="already belongs"):
        oidc_manager.process_callback(session, code="code_collision", state=state)


def test_oidc_callback_token_endpoint_error(
    session: Session,
    oidc_manager: OidcManager,
    mock_idp: MockOidcServer,
    seed_issuer: TrustedAuthIssuer,
) -> None:
    _, state = oidc_manager.create_authorization_flow(session)
    mock_idp.token_endpoint_status = 502

    with pytest.raises(OidcTokenError, match="502"):
        oidc_manager.process_callback(session, code="any_code", state=state)
