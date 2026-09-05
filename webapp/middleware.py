"""Web authentication, CSRF protection, and tenant route guard middleware."""

from __future__ import annotations

import os
from typing import Any, Final
from urllib.parse import urlparse

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from auth.crypto import hash_token, verify_csrf_token
from auth.sessions import SessionInfo, lookup_session, touch_session_throttled
from persistence.config import (
    create_db_engine,
    create_session_factory,
    get_database_url,
)
from persistence.context import Role, TenantContext

ENV_ALLOWED_ORIGINS: Final[str] = "UNTANGLE_ALLOWED_ORIGINS"
ENV_SECRET_KEY: Final[str] = "UNTANGLE_SECRET_KEY"
DEFAULT_DEV_SECRET: Final[str] = "dev-insecure-secret-key-change-in-production-12345678"

COOKIE_NAME_PROD: Final[str] = "__Host-untangle_session"
COOKIE_NAME_DEV: Final[str] = "untangle_session"


def get_allowed_origins() -> set[str]:
    """Parse configured allowed origins strictly without proxy inference."""
    raw = os.environ.get(ENV_ALLOWED_ORIGINS, "").strip()
    if not raw:
        # Default local origins for dev/test
        return {
            "http://localhost:8080",
            "http://127.0.0.1:8080",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://testserver",
        }
    return {origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()}


def get_app_secret_key() -> str:
    """Return configured application secret key."""
    return os.environ.get(ENV_SECRET_KEY, DEFAULT_DEV_SECRET)


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """Resolves authenticated session and constructs TenantContext if active organisation selected."""

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self._engine = None
        self._factory = None

    def _get_session_factory(self):
        if self._factory is None:
            url = get_database_url()
            if not url:
                return None
            self._engine = create_db_engine(url)
            self._factory = create_session_factory(self._engine)
        return self._factory

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        request.state.session = None
        request.state.raw_token = None
        request.state.tenant_context = None

        # Look for session cookie (__Host- or fallback)
        raw_token = request.cookies.get(COOKIE_NAME_PROD) or request.cookies.get(COOKIE_NAME_DEV)

        factory = self._get_session_factory()
        if raw_token and factory:
            try:
                with factory() as db_session:
                    session_info: SessionInfo | None = lookup_session(db_session, raw_token)
                    if session_info and not session_info.is_revoked and not session_info.is_stale:
                        request.state.session = session_info
                        request.state.raw_token = raw_token

                        # Background activity touch with write throttling
                        touch_session_throttled(db_session, raw_token)

                        # Construct TenantContext if active organisation is chosen
                        if (
                            session_info.active_organisation_id is not None
                            and session_info.active_role_code is not None
                        ):
                            req_id = getattr(request.state, "request_id", "")
                            try:
                                role = Role(session_info.active_role_code)
                                request.state.tenant_context = TenantContext(
                                    organisation_id=session_info.active_organisation_id,
                                    principal_id=session_info.principal_id,
                                    role=role,
                                    request_id=req_id,
                                )
                            except ValueError:
                                pass
            except Exception:
                # Database error or unavailable: do not crash public endpoints
                pass

        return await call_next(request)


class CsrfMiddleware(BaseHTTPMiddleware):
    """Enforces strict origin allowlist validation and double-submit CSRF token checks."""

    CONTROL_PLANE_PREFIXES: Final[tuple[str, ...]] = (
        "/api/auth/",
        "/api/orgs/",
        "/api/invitations/",
    )

    def __init__(self, app: Any, exempt_paths: set[str] | None = None) -> None:
        super().__init__(app)
        self.exempt_paths = exempt_paths or {
            "/api/auth/callback",
            "/api/docs",
            "/openapi.json",
        }

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        # Safe methods do not mutate state
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return await call_next(request)

        # Explicitly exempt endpoints (e.g. OIDC callback from external identity provider)
        if request.url.path in self.exempt_paths:
            return await call_next(request)

        is_control_plane = any(
            request.url.path.startswith(prefix) for prefix in self.CONTROL_PLANE_PREFIXES
        )
        has_session_cookie = bool(
            request.cookies.get(COOKIE_NAME_PROD) or request.cookies.get(COOKIE_NAME_DEV)
        )

        # CSRF defense applies to control plane and all authenticated mutating requests
        if is_control_plane or has_session_cookie:
            # 1. Validate Origin / Referer against explicit allowlist
            allowed_origins = get_allowed_origins()
            origin_header = request.headers.get("origin")
            referer_header = request.headers.get("referer")

            request_origin: str | None = None
            if origin_header:
                parsed = urlparse(origin_header)
                request_origin = f"{parsed.scheme}://{parsed.netloc}"
            elif referer_header:
                parsed = urlparse(referer_header)
                request_origin = f"{parsed.scheme}://{parsed.netloc}"

            if not request_origin:
                return JSONResponse(
                    {
                        "error": "CSRF_ORIGIN_MISSING",
                        "detail": "Missing Origin and Referer headers on mutating request.",
                    },
                    status_code=403,
                )

            if request_origin.rstrip("/") not in allowed_origins:
                return JSONResponse(
                    {
                        "error": "CSRF_ORIGIN_DENIED",
                        "detail": f"Origin {request_origin!r} is not in the allowed origins list.",
                    },
                    status_code=403,
                )

            # 2. If caller is authenticated, verify session-bound CSRF token
            session: SessionInfo | None = getattr(request.state, "session", None)
            if session is not None or has_session_cookie:
                csrf_header = request.headers.get("x-csrf-token")
                if not csrf_header:
                    return JSONResponse(
                        {
                            "error": "CSRF_TOKEN_MISSING",
                            "detail": "Missing X-CSRF-Token header on authenticated mutating request.",
                        },
                        status_code=403,
                    )
                raw_token = (
                    getattr(request.state, "raw_token", "")
                    or request.cookies.get(COOKIE_NAME_PROD)
                    or request.cookies.get(COOKIE_NAME_DEV)
                    or ""
                )
                token_hash = hash_token(raw_token)
                secret_key = get_app_secret_key()
                if not verify_csrf_token(secret_key, token_hash, csrf_header):
                    return JSONResponse(
                        {
                            "error": "CSRF_TOKEN_INVALID",
                            "detail": "Invalid or mismatched CSRF token.",
                        },
                        status_code=403,
                    )

        return await call_next(request)


class TenantRouteGuard(BaseHTTPMiddleware):
    """Guards tenant-isolated data-plane routes, failing closed when active organisation is null."""

    TENANT_PREFIXES = ("/api/tenant/",)

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        path = request.url.path
        is_tenant_path = any(path.startswith(prefix) for prefix in self.TENANT_PREFIXES)

        if is_tenant_path:
            session: SessionInfo | None = getattr(request.state, "session", None)
            if not session:
                return JSONResponse(
                    {
                        "error": "UNAUTHENTICATED",
                        "detail": "Authentication required to access tenant resource.",
                    },
                    status_code=401,
                )

            tenant_ctx: TenantContext | None = getattr(request.state, "tenant_context", None)
            if not tenant_ctx or session.active_organisation_id is None:
                return JSONResponse(
                    {
                        "error": "NO_ACTIVE_ORGANISATION",
                        "detail": "An active organisation must be selected to access this resource.",
                    },
                    status_code=403,
                )

        return await call_next(request)
