"""Mock OIDC Identity Provider with RSA key generation and httpx mock transport."""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import parse_qs

import httpx
from authlib.jose import JsonWebKey, jwt
from cryptography.hazmat.primitives.asymmetric import rsa


class MockOidcServer:
    """Mock OpenID Connect Identity Provider for offline protocol testing."""

    def __init__(
        self,
        issuer_url: str = "https://auth.untangle.internal",
        client_id: str = "untangle_client",
        client_secret: str = "dev_secret",
        kid: str = "test-key-1",
    ) -> None:
        self.issuer_url = issuer_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.kid = kid

        # Generate RSA keypair
        self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk_obj = JsonWebKey.import_key(
            self.private_key, {"kty": "RSA", "kid": self.kid, "use": "sig"}
        )
        self.public_jwk = jwk_obj.as_dict(is_crv=False)
        self.jwks = {"keys": [self.public_jwk]}

        self.openid_config = {
            "issuer": self.issuer_url,
            "authorization_endpoint": f"{self.issuer_url}/authorize",
            "token_endpoint": f"{self.issuer_url}/token",
            "jwks_uri": f"{self.issuer_url}/jwks.json",
            "userinfo_endpoint": f"{self.issuer_url}/userinfo",
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "scopes_supported": ["openid", "email", "profile"],
            "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
            "claims_supported": [
                "sub",
                "iss",
                "aud",
                "exp",
                "iat",
                "email",
                "email_verified",
                "name",
            ],
        }

        self.issued_codes: dict[str, dict[str, Any]] = {}
        self.token_endpoint_status: int = 200
        self.token_response_override: dict[str, Any] | None = None

    def register_code(
        self,
        code: str,
        sub: str = "usr_subject_123",
        email: str = "alice@example.com",
        email_verified: bool = True,
        name: str = "Alice Test",
        nonce: str | None = None,
        custom_claims: dict[str, Any] | None = None,
    ) -> None:
        self.issued_codes[code] = {
            "sub": sub,
            "email": email,
            "email_verified": email_verified,
            "name": name,
            "nonce": nonce,
            "custom": custom_claims or {},
        }

    def issue_id_token(
        self,
        sub: str = "usr_subject_123",
        email: str = "alice@example.com",
        email_verified: bool = True,
        name: str = "Alice Test",
        nonce: str | None = None,
        expires_in: int = 3600,
        custom_claims: dict[str, Any] | None = None,
    ) -> str:
        now = int(time.time())
        claims = {
            "iss": self.issuer_url,
            "sub": sub,
            "aud": self.client_id,
            "exp": now + expires_in,
            "iat": now,
            "email": email,
            "email_verified": email_verified,
            "name": name,
        }
        if nonce is not None:
            claims["nonce"] = nonce
        if custom_claims:
            claims.update(custom_claims)

        header = {"alg": "RS256", "kid": self.kid}
        raw = jwt.encode(header, claims, self.private_key)
        return raw.decode("utf-8") if isinstance(raw, bytes) else raw

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)

        if url_str.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200, json=self.openid_config, headers={"content-type": "application/json"}
            )

        if url_str.endswith("/jwks.json"):
            return httpx.Response(200, json=self.jwks, headers={"content-type": "application/json"})

        if url_str.endswith("/token"):
            if self.token_endpoint_status != 200:
                return httpx.Response(self.token_endpoint_status, json={"error": "invalid_grant"})

            if self.token_response_override is not None:
                return httpx.Response(200, json=self.token_response_override)

            body_bytes = request.content
            parsed = parse_qs(body_bytes.decode("utf-8"))
            code = parsed.get("code", [""])[0]

            code_data = self.issued_codes.pop(code, None)
            if not code_data:
                id_token = self.issue_id_token()
            else:
                id_token = self.issue_id_token(
                    sub=code_data["sub"],
                    email=code_data["email"],
                    email_verified=code_data["email_verified"],
                    name=code_data["name"],
                    nonce=code_data["nonce"],
                    custom_claims=code_data["custom"],
                )

            resp_data = {
                "access_token": "mock_access_token_xyz",
                "token_type": "Bearer",
                "id_token": id_token,
                "expires_in": 3600,
            }
            return httpx.Response(200, json=resp_data, headers={"content-type": "application/json"})

        return httpx.Response(404, json={"error": "not_found"})

    def create_mock_client(self) -> httpx.Client:
        transport = httpx.MockTransport(self.handle_request)
        return httpx.Client(transport=transport, base_url=self.issuer_url)
