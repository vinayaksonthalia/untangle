"""Authentication, Organisation, Membership, and Invitation API routes."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth.crypto import (
    generate_csrf_token,
    hash_token,
)
from auth.oidc import (
    IdentityCollisionError,
    OidcError,
    OidcManager,
    OidcStateError,
    OidcTokenError,
    UnverifiedEmailError,
)
from auth.permissions import (
    Action,
    can_manage_target_role,
    check_permission,
    require_permission,
)
from auth.service import ControlPlaneService
from auth.sessions import (
    SessionInfo,
    create_session,
    revoke_all_sessions,
    revoke_session,
    switch_organisation,
)
from persistence.config import (
    create_db_engine,
    create_session_factory,
    get_auth_database_url,
    get_database_url,
    is_local_or_test_mode,
)
from webapp.middleware import (
    COOKIE_NAME_DEV,
    COOKIE_NAME_PROD,
    get_app_secret_key,
)

router = APIRouter(prefix="/api", tags=["auth"])

OIDC_STATE_COOKIE_PROD = "__Host-untangle_oidc_state"
OIDC_STATE_COOKIE_DEV = "untangle_oidc_state"
CSRF_COOKIE_NAME = "untangle_csrf"
# Local/test-only sentinel; hosted mode rejects it before OIDC initialization.
DEFAULT_OIDC_CLIENT_SECRET = "dev_secret"  # nosec B105


def is_secure_connection(request: Request) -> bool:
    """Determine if cookies should have the Secure flag."""
    if request.url.scheme == "https":
        return True
    # Production always sets Secure
    env = os.environ.get("UNTANGLE_ENV", "").lower()
    return (
        env not in ("development", "local", "test") and os.environ.get("UNTANGLE_DEV_MODE") != "1"
    )


def get_cookie_name(request: Request, prod_name: str, dev_name: str) -> str:
    """Select __Host- prefix only when connection is Secure."""
    return prod_name if is_secure_connection(request) else dev_name


def safe_return_to(candidate: str) -> str:
    """Allow only same-site absolute paths for post-auth redirects."""
    if candidate and candidate.startswith("/") and not candidate.startswith(("//", "/\\")):
        return candidate
    return "/dashboard"


def get_app_session():
    url = get_database_url()
    if not url:
        raise HTTPException(503, "Database unconfigured")
    engine = create_db_engine(url)
    factory = create_session_factory(engine)
    return factory()


def get_auth_session():
    url = get_auth_database_url()
    if not url:
        raise HTTPException(503, "Authentication database unconfigured")
    engine = create_db_engine(url)
    factory = create_session_factory(engine)
    return factory()


def create_session_with_default_organisation(
    auth_session: Session,
    app_session: Session,
    *,
    principal_id: int,
    ip_address: str,
    user_agent: str | None,
) -> str:
    """Mint a session and select its sole active organisation, if one exists."""
    raw_token, _ = create_session(
        auth_session,
        principal_id=principal_id,
        active_org_id=None,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    active_memberships = [
        item
        for item in ControlPlaneService.list_organisations(app_session, raw_token)
        if item.membership_status == "active"
    ]
    if len(active_memberships) == 1:
        raw_token, _, _ = switch_organisation(app_session, raw_token, active_memberships[0].org_id)
    return raw_token


def get_oidc_manager(request: Request) -> OidcManager:
    issuer = os.environ.get("OIDC_ISSUER_URL", "https://auth.untangle.internal")
    client_id = os.environ.get("OIDC_CLIENT_ID", "untangle_client")
    client_secret = os.environ.get("OIDC_CLIENT_SECRET", "").strip()
    if (
        not client_secret or client_secret == DEFAULT_OIDC_CLIENT_SECRET
    ) and not is_local_or_test_mode():
        raise RuntimeError(
            "OIDC_CLIENT_SECRET must be explicitly configured to a non-development value "
            "outside local/test mode"
        )
    client_secret = client_secret or DEFAULT_OIDC_CLIENT_SECRET
    redirect_uri = os.environ.get("OIDC_REDIRECT_URI", "http://localhost:8080/api/auth/callback")
    secret_key = get_app_secret_key()
    return OidcManager(
        issuer_url=issuer,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        secret_key=secret_key,
        http_client=getattr(request.app.state, "oidc_http_client", None),
    )


# ---- Request / Response Models ---------------------------------------------


class SwitchOrgRequest(BaseModel):
    organisation_id: int


class CreateOrgRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)


class MutateMemberRequest(BaseModel):
    target_principal_id: int
    role_code: str = Field(..., pattern="^(owner|admin|operator|reviewer|auditor)$")
    status: str = Field(..., pattern="^(active|suspended)$")


class CreateInvitationRequest(BaseModel):
    email: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    role_code: str = Field(..., pattern="^(owner|admin|operator|reviewer|auditor)$")


class RevokeInvitationRequest(BaseModel):
    invitation_public_id: str


class AcceptInvitationRequest(BaseModel):
    token: str


# ---- Auth Routes -----------------------------------------------------------


@router.get("/auth/login")
def auth_login(
    request: Request,
    return_to: str = Query("/", max_length=255),
) -> Response:
    """Initiate OIDC authentication flow with PKCE."""
    mgr = get_oidc_manager(request)
    ip = request.client.host if request.client else "127.0.0.1"
    ua = request.headers.get("user-agent")

    with get_auth_session() as auth_sess:
        auth_url, raw_state = mgr.create_authorization_flow(
            auth_sess, return_to=return_to, ip_address=ip, user_agent=ua
        )

    secure = is_secure_connection(request)
    state_cookie_name = get_cookie_name(request, OIDC_STATE_COOKIE_PROD, OIDC_STATE_COOKIE_DEV)

    # Return redirect or JSON depending on Accept header
    accept = request.headers.get("accept", "")
    if "application/json" in accept and "text/html" not in accept:
        response = JSONResponse({"authorization_url": auth_url, "state": raw_state})
    else:
        response = RedirectResponse(url=auth_url, status_code=302)

    response.set_cookie(
        key=state_cookie_name,
        value=raw_state,
        max_age=600,  # 10 minutes
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    return response


@router.get("/auth/callback")
def auth_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
) -> Response:
    """Process OIDC callback, exchange code, verify ID token, and mint session."""
    state_cookie_name = get_cookie_name(request, OIDC_STATE_COOKIE_PROD, OIDC_STATE_COOKIE_DEV)
    cookie_state = request.cookies.get(state_cookie_name)

    if not cookie_state or cookie_state != state:
        raise HTTPException(400, "Invalid or missing OIDC state cookie")

    mgr = get_oidc_manager(request)
    ip = request.client.host if request.client else "127.0.0.1"
    ua = request.headers.get("user-agent")

    try:
        with get_auth_session() as auth_sess:
            principal_id, principal_pub_id, return_to = mgr.process_callback(
                auth_sess, code=code, state=state, ip_address=ip, user_agent=ua
            )

            # Mint a short-lived session first so the control-plane lookup can
            # authenticate normally.  Calling list_organisations with an empty
            # token would always fail (and bypasses the tenant boundary).
            with get_app_session() as app_sess:
                raw_session_token = create_session_with_default_organisation(
                    auth_sess,
                    app_sess,
                    principal_id=principal_id,
                    ip_address=ip,
                    user_agent=ua,
                )
    except OidcStateError as exc:
        raise HTTPException(400, str(exc)) from exc
    except UnverifiedEmailError as exc:
        raise HTTPException(403, str(exc)) from exc
    except IdentityCollisionError as exc:
        raise HTTPException(409, str(exc)) from exc
    except (OidcTokenError, OidcError) as exc:
        raise HTTPException(401, str(exc)) from exc

    secure = is_secure_connection(request)
    session_cookie_name = get_cookie_name(request, COOKIE_NAME_PROD, COOKIE_NAME_DEV)
    secret_key = get_app_secret_key()
    token_hash = hash_token(raw_session_token)
    csrf_token = generate_csrf_token(secret_key, token_hash)

    # Only accept a same-site absolute path. Reject scheme-relative ("//host") and
    # backslash-tricked ("/\\host") targets, which browsers resolve to an external origin —
    # otherwise the callback is an open redirect to an attacker site (Qodo #9).
    target_redirect = safe_return_to(return_to)
    response = RedirectResponse(url=target_redirect, status_code=302)

    # Set session cookie (__Host- compliant)
    response.set_cookie(
        key=session_cookie_name,
        value=raw_session_token,
        max_age=43200,  # 12 hours max
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    # Set double-submit CSRF cookie (HttpOnly=False so JS can read and send in header)
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        max_age=43200,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
    )
    # Clear OIDC state cookie
    response.delete_cookie(key=state_cookie_name, path="/")
    return response


@router.post("/auth/logout")
def auth_logout(request: Request) -> Response:
    """Revoke current session and clear authentication cookies."""
    raw_token = getattr(request.state, "raw_token", None)
    ip = request.client.host if request.client else "127.0.0.1"
    ua = request.headers.get("user-agent")

    if raw_token:
        with get_app_session() as sess:
            revoke_session(sess, raw_token, ip_address=ip, user_agent=ua)

    session_cookie_name = get_cookie_name(request, COOKIE_NAME_PROD, COOKIE_NAME_DEV)
    response = JSONResponse({"status": "logged_out"})
    response.delete_cookie(key=session_cookie_name, path="/")
    response.delete_cookie(key=CSRF_COOKIE_NAME, path="/")
    return response


@router.get("/auth/me")
def auth_me(request: Request) -> JSONResponse:
    """Return current authenticated principal, active organization, and capabilities."""
    session: SessionInfo | None = getattr(request.state, "session", None)
    if not session:
        return JSONResponse({"authenticated": False})

    role = session.active_role_code
    capabilities = [act.value for act in Action if role and check_permission(role, act)]

    return JSONResponse(
        {
            "authenticated": True,
            "principal": {
                "public_id": session.principal_public_id,
                "email": session.principal_email,
                "display_name": session.principal_display_name,
            },
            "organisation": {
                "id": session.active_organisation_id,
                "public_id": session.active_org_public_id,
                "role": role,
            }
            if session.active_organisation_id
            else None,
            "capabilities": capabilities,
            "session": {
                "public_id": session.public_id,
                "idle_expires_at": session.idle_expires_at.isoformat(),
                "absolute_expires_at": session.absolute_expires_at.isoformat(),
            },
        }
    )


@router.post("/auth/switch-org")
def auth_switch_org(payload: SwitchOrgRequest, request: Request) -> Response:
    """Switch active organisation for the session, rotating the session token."""
    raw_token = getattr(request.state, "raw_token", None)
    if not raw_token:
        raise HTTPException(401, "Authentication required")

    with get_app_session() as sess:
        try:
            new_raw_token, new_auth_ver, role_code = switch_organisation(
                sess, raw_token, payload.organisation_id
            )
        except Exception as exc:
            raise HTTPException(403, str(exc)) from exc

    secure = is_secure_connection(request)
    session_cookie_name = get_cookie_name(request, COOKIE_NAME_PROD, COOKIE_NAME_DEV)
    secret_key = get_app_secret_key()
    token_hash = hash_token(new_raw_token)
    csrf_token = generate_csrf_token(secret_key, token_hash)

    response = JSONResponse(
        {
            "status": "switched",
            "active_organisation_id": payload.organisation_id,
            "role": role_code,
            "auth_version": new_auth_ver,
        }
    )
    response.set_cookie(
        key=session_cookie_name,
        value=new_raw_token,
        max_age=43200,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        max_age=43200,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
    )
    return response


@router.post("/auth/sessions/revoke-all")
def auth_revoke_all(request: Request) -> Response:
    """Revoke all active sessions for the authenticated principal."""
    raw_token = getattr(request.state, "raw_token", None)
    if not raw_token:
        raise HTTPException(401, "Authentication required")

    ip = request.client.host if request.client else "127.0.0.1"
    ua = request.headers.get("user-agent")

    with get_app_session() as sess:
        count = revoke_all_sessions(sess, raw_token, ip_address=ip, user_agent=ua)

    session_cookie_name = get_cookie_name(request, COOKIE_NAME_PROD, COOKIE_NAME_DEV)
    response = JSONResponse({"status": "all_sessions_revoked", "count": count})
    response.delete_cookie(key=session_cookie_name, path="/")
    response.delete_cookie(key=CSRF_COOKIE_NAME, path="/")
    return response


# ---- Organisation Management -----------------------------------------------


@router.get("/orgs")
def list_organisations(request: Request) -> JSONResponse:
    """List all organisations in which the authenticated principal holds membership."""
    raw_token = getattr(request.state, "raw_token", None)
    if not raw_token:
        raise HTTPException(401, "Authentication required")

    with get_app_session() as sess:
        orgs = ControlPlaneService.list_organisations(sess, raw_token)

    return JSONResponse(
        [
            {
                "org_id": o.org_id,
                "public_id": o.org_public_id,
                "name": o.org_name,
                "role": o.role_code,
                "status": o.membership_status,
            }
            for o in orgs
        ]
    )


@router.post("/orgs/create")
def create_organisation(payload: CreateOrgRequest, request: Request) -> Response:
    """Create a new organisation and automatically switch active context to it."""
    raw_token = getattr(request.state, "raw_token", None)
    if not raw_token:
        raise HTTPException(401, "Authentication required")

    with get_app_session() as sess:
        org_id, org_public_id = ControlPlaneService.create_organisation(
            sess, raw_token, payload.name
        )
        new_raw_token, new_auth_ver, role_code = switch_organisation(sess, raw_token, org_id)

    secure = is_secure_connection(request)
    session_cookie_name = get_cookie_name(request, COOKIE_NAME_PROD, COOKIE_NAME_DEV)
    secret_key = get_app_secret_key()
    token_hash = hash_token(new_raw_token)
    csrf_token = generate_csrf_token(secret_key, token_hash)

    response = JSONResponse(
        {
            "status": "created",
            "org_id": org_id,
            "public_id": org_public_id,
            "name": payload.name,
            "role": role_code,
        }
    )
    response.set_cookie(
        key=session_cookie_name,
        value=new_raw_token,
        max_age=43200,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        max_age=43200,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
    )
    return response


# ---- Memberships -----------------------------------------------------------


@router.get("/orgs/members")
def list_organisation_members(request: Request) -> JSONResponse:
    """List all members of the caller's active organisation."""
    raw_token = getattr(request.state, "raw_token", None)
    session: SessionInfo | None = getattr(request.state, "session", None)
    if not raw_token or not session:
        raise HTTPException(401, "Authentication required")

    require_permission(session.active_role_code, Action.MEMBERSHIP_LIST)

    with get_app_session() as sess:
        members = ControlPlaneService.list_memberships(sess, raw_token)

    return JSONResponse(
        [
            {
                "public_id": m.membership_public_id,
                "principal_public_id": m.principal_public_id,
                "email": m.email,
                "display_name": m.display_name,
                "role": m.role_code,
                "status": m.status,
                "auth_version": m.auth_version,
                "created_at": m.created_at.isoformat(),
            }
            for m in members
        ]
    )


@router.post("/orgs/members/mutate")
def mutate_organisation_member(payload: MutateMemberRequest, request: Request) -> JSONResponse:
    """Mutate role or status of an organisation member with mutex locking."""
    raw_token = getattr(request.state, "raw_token", None)
    session: SessionInfo | None = getattr(request.state, "session", None)
    if not raw_token or not session:
        raise HTTPException(401, "Authentication required")

    require_permission(session.active_role_code, Action.MEMBERSHIP_MUTATE)

    if not can_manage_target_role(session.active_role_code or "", payload.role_code):
        raise HTTPException(403, "Administrator cannot assign or modify owner role")

    with get_app_session() as sess:
        try:
            mem_id, updated_role, updated_status, new_ver = ControlPlaneService.mutate_membership(
                sess,
                raw_session_token=raw_token,
                target_principal_id=payload.target_principal_id,
                new_role_code=payload.role_code,
                new_status=payload.status,
            )
        except Exception as exc:
            msg = str(exc)
            if "last active owner" in msg.lower():
                raise HTTPException(409, "Cannot remove or demote the last active owner") from exc
            if "unauthorized" in msg.lower() or "forbidden" in msg.lower():
                raise HTTPException(403, msg) from exc
            raise HTTPException(400, msg) from exc

    return JSONResponse(
        {
            "status": "updated",
            "membership_id": mem_id,
            "role": updated_role,
            "membership_status": updated_status,
            "auth_version": new_ver,
        }
    )


# ---- Invitations -----------------------------------------------------------


@router.get("/orgs/invitations")
def list_organisation_invitations(request: Request) -> JSONResponse:
    """List pending invitations in caller's active organisation."""
    raw_token = getattr(request.state, "raw_token", None)
    session: SessionInfo | None = getattr(request.state, "session", None)
    if not raw_token or not session:
        raise HTTPException(401, "Authentication required")

    require_permission(session.active_role_code, Action.INVITATION_LIST)

    with get_app_session() as sess:
        invites = ControlPlaneService.list_invitations(sess, raw_token)

    return JSONResponse(
        [
            {
                "public_id": i.invitation_public_id,
                "email": i.email,
                "role": i.role_code,
                "status": i.status,
                "expires_at": i.expires_at.isoformat(),
                "created_at": i.created_at.isoformat(),
            }
            for i in invites
        ]
    )


@router.post("/orgs/invitations")
def create_organisation_invitation(
    payload: CreateInvitationRequest, request: Request
) -> JSONResponse:
    """Create a single-use organisation invitation."""
    raw_token = getattr(request.state, "raw_token", None)
    session: SessionInfo | None = getattr(request.state, "session", None)
    if not raw_token or not session:
        raise HTTPException(401, "Authentication required")

    require_permission(session.active_role_code, Action.INVITATION_CREATE)

    if not can_manage_target_role(session.active_role_code or "", payload.role_code):
        raise HTTPException(403, "Administrator cannot invite owners")

    with get_app_session() as sess:
        try:
            raw_inv_token, inv_pub_id, norm_email = ControlPlaneService.create_invitation(
                sess,
                raw_session_token=raw_token,
                email=str(payload.email),
                role_code=payload.role_code,
            )
        except Exception as exc:
            msg = str(exc)
            if "already an active member" in msg.lower():
                raise HTTPException(409, msg) from exc
            raise HTTPException(400, msg) from exc

    # Development-only invitation link exposure on loopback
    is_dev = os.environ.get("UNTANGLE_DEV_MODE") == "1"
    host = request.url.hostname or ""
    is_loopback = host in ("localhost", "127.0.0.1")

    invite_url = None
    if is_dev and is_loopback:
        invite_url = f"{request.base_url}invite?token={raw_inv_token}"

    resp_data: dict[str, Any] = {
        "status": "invited",
        "public_id": inv_pub_id,
        "email": norm_email,
        "role": payload.role_code,
    }
    if invite_url:
        resp_data["invitation_link"] = invite_url

    return JSONResponse(resp_data)


@router.post("/orgs/invitations/revoke")
def revoke_organisation_invitation(
    payload: RevokeInvitationRequest, request: Request
) -> JSONResponse:
    """Revoke a pending organisation invitation."""
    raw_token = getattr(request.state, "raw_token", None)
    session: SessionInfo | None = getattr(request.state, "session", None)
    if not raw_token or not session:
        raise HTTPException(401, "Authentication required")

    require_permission(session.active_role_code, Action.INVITATION_REVOKE)

    with get_app_session() as sess:
        revoked = ControlPlaneService.revoke_invitation(
            sess, raw_session_token=raw_token, invitation_public_id=payload.invitation_public_id
        )

    if not revoked:
        raise HTTPException(404, "Invitation not found or not pending")

    return JSONResponse({"status": "revoked", "public_id": payload.invitation_public_id})


@router.get("/invitations/lookup")
def lookup_invitation(token: str = Query(..., min_length=16)) -> JSONResponse:
    """Public lookup of invitation details by raw token."""
    with get_app_session() as sess:
        details = ControlPlaneService.lookup_invitation(sess, token)

    if not details:
        raise HTTPException(404, "Invitation not found")

    return JSONResponse(
        {
            "public_id": details.invitation_public_id,
            "organisation_name": details.organisation_name,
            "email": details.email,
            "role": details.role_code,
            "status": details.status,
            "is_expired": details.is_expired,
        }
    )


@router.post("/invitations/accept")
def accept_invitation(payload: AcceptInvitationRequest, request: Request) -> Response:
    """Accept an invitation bound to caller's authenticated account and switch into org."""
    raw_token = getattr(request.state, "raw_token", None)
    session: SessionInfo | None = getattr(request.state, "session", None)
    if not raw_token or not session:
        raise HTTPException(401, "Authentication required to accept invitation")

    with get_app_session() as sess:
        try:
            mem_id, org_id, role_code = ControlPlaneService.accept_invitation(
                sess, raw_session_token=raw_token, raw_invitation_token=payload.token
            )
            new_raw_token, new_auth_ver, role_code = switch_organisation(sess, raw_token, org_id)
        except Exception as exc:
            msg = str(exc)
            if "email does not match" in msg.lower():
                raise HTTPException(
                    403, "Invitation email does not match authenticated account"
                ) from exc
            raise HTTPException(400, msg) from exc

    secure = is_secure_connection(request)
    session_cookie_name = get_cookie_name(request, COOKIE_NAME_PROD, COOKIE_NAME_DEV)
    secret_key = get_app_secret_key()
    token_hash = hash_token(new_raw_token)
    csrf_token = generate_csrf_token(secret_key, token_hash)

    response = JSONResponse(
        {
            "status": "accepted",
            "membership_id": mem_id,
            "organisation_id": org_id,
            "role": role_code,
        }
    )
    response.set_cookie(
        key=session_cookie_name,
        value=new_raw_token,
        max_age=43200,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        max_age=43200,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
    )
    return response
