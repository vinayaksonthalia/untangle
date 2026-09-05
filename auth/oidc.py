"""OpenID Connect (OIDC) client and transaction handling using Authlib.

Enforces PKCE S256, atomic single-use state transactions, and strict token validation.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from authlib.jose import JsonWebKey, jwt
from authlib.oauth2.rfc7636 import create_s256_code_challenge
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from auth.audit import record_security_event
from auth.crypto import (
    decrypt_code_verifier,
    derive_encryption_key,
    encrypt_code_verifier,
    hash_ip,
    hash_token,
    truncate_user_agent,
)
from persistence.ids import (
    PREFIX_FEDERATED_IDENTITY,
    PREFIX_OIDC_TX,
    PREFIX_PRINCIPAL,
    generate_public_id,
)
from persistence.models import FederatedIdentity, OidcAuthTransaction, Principal, TrustedAuthIssuer


class OidcError(Exception):
    """Base exception for OIDC errors."""


class OidcStateError(OidcError):
    """Invalid, expired, or replayed state."""


class OidcTokenError(OidcError):
    """ID token verification failed."""


class UnverifiedEmailError(OidcError):
    """Email is not marked verified by the IdP."""


class IdentityCollisionError(OidcError):
    """Email already belongs to another principal."""


class OidcManager:
    """Manages OIDC flows, discovery, and token verification."""

    def __init__(
        self,
        issuer_url: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        secret_key: str,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.issuer_url = issuer_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.secret_key = secret_key
        self.enc_key = derive_encryption_key(secret_key)
        self._http = http_client or httpx.Client(timeout=10.0)
        self._metadata: dict[str, Any] | None = None
        self._jwks: dict[str, Any] | None = None

    def get_metadata(self) -> dict[str, Any]:
        """Fetch and cache OpenID Connect configuration discovery document."""
        if self._metadata is not None:
            return self._metadata
        well_known = f"{self.issuer_url}/.well-known/openid-configuration"
        resp = self._http.get(well_known)
        resp.raise_for_status()
        self._metadata = resp.json()
        return self._metadata

    def get_jwks(self) -> dict[str, Any]:
        """Fetch and cache JSON Web Key Set (JWKS) from IdP."""
        if self._jwks is not None:
            return self._jwks
        metadata = self.get_metadata()
        jwks_uri = metadata.get("jwks_uri")
        if not jwks_uri:
            raise OidcError("Discovery document missing jwks_uri")
        resp = self._http.get(jwks_uri)
        resp.raise_for_status()
        self._jwks = resp.json()
        return self._jwks

    def create_authorization_flow(
        self,
        auth_session: Session,
        return_to: str = "/",
        ip_address: str = "127.0.0.1",
        user_agent: str | None = None,
    ) -> tuple[str, str]:
        """Initiate OIDC PKCE flow.

        Returns:
            tuple[str, str]: (authorization_url, raw_state)
        """
        metadata = self.get_metadata()
        authorization_endpoint = metadata.get("authorization_endpoint")
        if not authorization_endpoint:
            raise OidcError("Discovery document missing authorization_endpoint")

        raw_state = secrets.token_urlsafe(32)
        raw_nonce = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(48)
        code_challenge = create_s256_code_challenge(code_verifier)

        state_hash = hash_token(raw_state)
        nonce_hash = hash_token(raw_nonce)
        code_verifier_encrypted = encrypt_code_verifier(code_verifier, self.enc_key)
        public_id = generate_public_id(PREFIX_OIDC_TX)
        expires_at = datetime.now(UTC) + timedelta(minutes=10)

        bind = auth_session.get_bind()
        is_postgres = bind.dialect.name == "postgresql"

        if is_postgres:
            auth_session.execute(
                text(
                    """
                    SELECT public.fn_oidc_create_transaction(
                        :public_id, :state_hash, :nonce_hash,
                        :code_verifier_encrypted, :return_to, :expires_at
                    )
                    """
                ),
                {
                    "public_id": public_id,
                    "state_hash": state_hash,
                    "nonce_hash": nonce_hash,
                    "code_verifier_encrypted": code_verifier_encrypted,
                    "return_to": return_to,
                    "expires_at": expires_at,
                },
            )
        else:
            tx = OidcAuthTransaction(
                public_id=public_id,
                state_hash=state_hash,
                nonce_hash=nonce_hash,
                code_verifier_encrypted=code_verifier_encrypted,
                return_to=return_to,
                expires_at=expires_at,
            )
            auth_session.add(tx)

        # Audit security event
        record_security_event(
            auth_session,
            event_type="auth.oidc.initiated",
            subject_type="oidc_transaction",
            subject_identifier=public_id,
            ip_hash=hash_ip(ip_address),
            user_agent_truncated=truncate_user_agent(user_agent),
            details={"issuer": self.issuer_url, "return_to": return_to},
        )
        auth_session.commit()

        # Build Authorization URL
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": "openid email profile",
            "state": raw_state,
            "nonce": raw_nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        req = httpx.Request("GET", authorization_endpoint, params=params)
        return str(req.url), raw_state

    def process_callback(
        self,
        auth_session: Session,
        code: str,
        state: str,
        ip_address: str = "127.0.0.1",
        user_agent: str | None = None,
    ) -> tuple[int, str, str]:
        """Process OIDC callback code exchange, verification, and principal resolution.

        Returns:
            tuple[int, str, str]: (principal_id, principal_public_id, return_to)
        """
        state_hash = hash_token(state)
        bind = auth_session.get_bind()
        is_postgres = bind.dialect.name == "postgresql"

        # 1. Atomically consume transaction
        if is_postgres:
            row = auth_session.execute(
                text(
                    """
                    SELECT nonce_hash, code_verifier_encrypted, return_to
                    FROM public.fn_oidc_consume_transaction(:state_hash)
                    """
                ),
                {"state_hash": state_hash},
            ).first()
            if not row:
                record_security_event(
                    auth_session,
                    event_type="auth.oidc.callback_failed",
                    subject_type="oidc_transaction",
                    subject_identifier=state_hash[:16],
                    ip_hash=hash_ip(ip_address),
                    user_agent_truncated=truncate_user_agent(user_agent),
                    details={"error": "invalid_or_replayed_state"},
                )
                auth_session.commit()
                raise OidcStateError("Invalid, expired, or previously consumed OIDC state")
            nonce_hash = row.nonce_hash
            code_verifier_encrypted = row.code_verifier_encrypted
            return_to = row.return_to
        else:
            now = datetime.now(UTC)
            tx = auth_session.scalar(
                select(OidcAuthTransaction).where(
                    OidcAuthTransaction.state_hash == state_hash,
                    OidcAuthTransaction.consumed_at.is_(None),
                    OidcAuthTransaction.expires_at > now,
                )
            )
            if not tx:
                record_security_event(
                    auth_session,
                    event_type="auth.oidc.callback_failed",
                    subject_type="oidc_transaction",
                    subject_identifier=state_hash[:16],
                    ip_hash=hash_ip(ip_address),
                    user_agent_truncated=truncate_user_agent(user_agent),
                    details={"error": "invalid_or_replayed_state"},
                )
                auth_session.commit()
                raise OidcStateError("Invalid, expired, or previously consumed OIDC state")
            tx.consumed_at = now
            nonce_hash = tx.nonce_hash
            code_verifier_encrypted = tx.code_verifier_encrypted
            return_to = tx.return_to
            auth_session.flush()

        code_verifier = decrypt_code_verifier(code_verifier_encrypted, self.enc_key)

        # 2. Token endpoint code exchange
        metadata = self.get_metadata()
        token_endpoint = metadata.get("token_endpoint")
        if not token_endpoint:
            raise OidcError("Discovery document missing token_endpoint")

        token_payload = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": self.redirect_uri,
            "code_verifier": code_verifier,
        }
        token_resp = self._http.post(token_endpoint, data=token_payload)
        if token_resp.status_code != 200:
            record_security_event(
                auth_session,
                event_type="auth.oidc.callback_failed",
                subject_type="oidc_transaction",
                subject_identifier=state_hash[:16],
                ip_hash=hash_ip(ip_address),
                user_agent_truncated=truncate_user_agent(user_agent),
                details={"error": "token_endpoint_error", "status": token_resp.status_code},
            )
            auth_session.commit()
            raise OidcTokenError(f"IdP token endpoint returned {token_resp.status_code}")

        tokens = token_resp.json()
        id_token_raw = tokens.get("id_token")
        if not id_token_raw:
            raise OidcTokenError("Missing id_token in token response")

        # 3. Verify ID Token
        jwks = self.get_jwks()
        key_set = JsonWebKey.import_key_set(jwks)
        try:
            claims = jwt.decode(id_token_raw, key_set)
            claims.validate()
        except Exception as exc:
            record_security_event(
                auth_session,
                event_type="auth.oidc.callback_failed",
                subject_type="id_token",
                subject_identifier="jwt_validation",
                ip_hash=hash_ip(ip_address),
                user_agent_truncated=truncate_user_agent(user_agent),
                details={"error": "jwt_decode_error"},
            )
            auth_session.commit()
            raise OidcTokenError("Invalid ID Token signature or claims") from exc

        # Claims verification
        if claims.get("iss") != self.issuer_url:
            raise OidcTokenError(
                f"Issuer mismatch: expected {self.issuer_url}, got {claims.get('iss')}"
            )
        aud = claims.get("aud")
        if aud != self.client_id and (isinstance(aud, list) and self.client_id not in aud):
            raise OidcTokenError(f"Audience mismatch: expected {self.client_id}, got {aud}")

        token_nonce = claims.get("nonce")
        if not token_nonce or hash_token(token_nonce) != nonce_hash:
            raise OidcTokenError("Nonce mismatch in ID token")

        # Verified Email enforcement
        email_verified = claims.get("email_verified")
        if not email_verified:
            record_security_event(
                auth_session,
                event_type="auth.oidc.callback_failed",
                subject_type="id_token",
                subject_identifier=claims.get("sub", "")[:64],
                ip_hash=hash_ip(ip_address),
                user_agent_truncated=truncate_user_agent(user_agent),
                details={"error": "unverified_email"},
            )
            auth_session.commit()
            raise UnverifiedEmailError("IdP account email must be verified")

        email = claims.get("email")
        if not email:
            raise OidcTokenError("Missing email claim in ID token")

        subject = str(claims.get("sub"))
        display_name = claims.get("name") or claims.get("preferred_username") or email

        # 4. Resolve Federated Identity via untangle_auth connection
        principal_pub_id = generate_public_id(PREFIX_PRINCIPAL)
        fed_pub_id = generate_public_id(PREFIX_FEDERATED_IDENTITY)

        if is_postgres:
            try:
                fed_row = auth_session.execute(
                    text(
                        """
                        SELECT principal_id, principal_public_id, is_new
                        FROM public.fn_auth_resolve_federated_identity(
                            :issuer, :subject, :email, :display_name,
                            :principal_public_id, :fed_public_id
                        )
                        """
                    ),
                    {
                        "issuer": self.issuer_url,
                        "subject": subject,
                        "email": email,
                        "display_name": display_name,
                        "principal_public_id": principal_pub_id,
                        "fed_public_id": fed_pub_id,
                    },
                ).first()
            except Exception as exc:
                auth_session.rollback()
                if "identity collision" in str(exc).lower() or "p0004" in str(exc).lower():
                    record_security_event(
                        auth_session,
                        event_type="auth.identity.collision",
                        subject_type="principal",
                        subject_identifier=email[:64],
                        ip_hash=hash_ip(ip_address),
                        user_agent_truncated=truncate_user_agent(user_agent),
                        details={"issuer": self.issuer_url, "subject": subject},
                    )
                    auth_session.commit()
                    raise IdentityCollisionError(
                        f"Email {email} already belongs to an existing principal"
                    ) from exc
                raise
            if not fed_row:
                raise OidcError("Failed to resolve federated identity")
            principal_id = fed_row.principal_id
            principal_public_id = fed_row.principal_public_id
        else:
            # SQLite fallback logic
            norm_email = email.lower().strip()
            # Verify issuer is trusted
            trusted = auth_session.scalar(
                select(TrustedAuthIssuer).where(
                    TrustedAuthIssuer.issuer_url == self.issuer_url,
                    TrustedAuthIssuer.is_active.is_(True),
                )
            )
            if not trusted:
                raise OidcError(f"Untrusted or inactive identity provider: {self.issuer_url}")

            fed = auth_session.scalar(
                select(FederatedIdentity).where(
                    FederatedIdentity.issuer == self.issuer_url,
                    FederatedIdentity.subject == subject,
                )
            )
            if fed:
                p = auth_session.scalar(select(Principal).where(Principal.id == fed.principal_id))
                if not p or not p.is_active:
                    raise OidcError("Principal account is deactivated")
                fed.email_at_auth = norm_email
                p.display_name = display_name
                principal_id = p.id
                principal_public_id = p.public_id
            else:
                collision = auth_session.scalar(
                    select(Principal).where(Principal.email == norm_email)
                )
                if collision:
                    record_security_event(
                        auth_session,
                        event_type="auth.identity.collision",
                        subject_type="principal",
                        subject_identifier=norm_email[:64],
                        ip_hash=hash_ip(ip_address),
                        user_agent_truncated=truncate_user_agent(user_agent),
                        details={"issuer": self.issuer_url, "subject": subject},
                    )
                    auth_session.commit()
                    raise IdentityCollisionError(
                        f"Email {email} already belongs to an existing principal"
                    )

                new_p = Principal(
                    public_id=principal_pub_id,
                    email=norm_email,
                    display_name=display_name,
                    is_active=True,
                )
                auth_session.add(new_p)
                auth_session.flush()

                new_fed = FederatedIdentity(
                    public_id=fed_pub_id,
                    principal_id=new_p.id,
                    issuer=self.issuer_url,
                    subject=subject,
                    email_at_auth=norm_email,
                    email_verified=True,
                )
                auth_session.add(new_fed)
                auth_session.flush()
                principal_id = new_p.id
                principal_public_id = new_p.public_id

        record_security_event(
            auth_session,
            event_type="auth.oidc.callback_success",
            subject_type="principal",
            subject_identifier=principal_public_id,
            ip_hash=hash_ip(ip_address),
            user_agent_truncated=truncate_user_agent(user_agent),
            actor_principal_id=principal_id,
            details={"issuer": self.issuer_url, "email": email},
        )
        auth_session.commit()

        return principal_id, principal_public_id, return_to
