# Authentication, Organisations, Memberships, and Server-Enforced Permissions (Phase 2)

Status: **Implemented and independently verifiable.** This document details the identity federation, session lifecycle, organisation management, 5-role authorization matrix, and least-privilege PostgreSQL control plane established in Phase 2 of Untangle's product-completion roadmap.

---

## 1. Product Boundary & Security Model

Phase 2 builds upon the Phase 1 persistence architecture to provide an enterprise-grade, cryptographically bound authentication and authorization boundary:

- **Single Configured Trusted OIDC Issuer**: Authentication is federated exclusively through an OpenID Connect identity provider specified in `public.trusted_auth_issuers`. Zero local password authentication or Argon2id credential storage.
- **Zero Caller-Supplied Identity in Control-Plane Functions**: Privileged PL/pgSQL functions derive actor authority strictly from the high-entropy session token hash (`p_session_token_hash`). Callers cannot supply or forge principal IDs, organisation IDs, or actor roles.
- **Strict Role Separation in PostgreSQL**: Dedicated database roles partition administrative migration (`untangle_migrator`), function execution (`untangle_fn_owner`), authentication transactions (`untangle_auth`), application runtime (`untangle_app`), and retention routines (`untangle_maintenance`).
- **Session Timers & Strict Timestamp Invariants**: Sessions enforce a 30-minute idle sliding window capped at a 12-hour absolute maximum lifetime, checked at both schema and function levels (`last_active_at <= idle_expires_at <= absolute_expires_at`).
- **5-Role Capability Matrix**: Enforces explicit permissions across `owner`, `admin`, `operator`, `reviewer`, and `auditor`, backed by pessimistic organisation row locks to prevent concurrent zero-owner states.
- **Immutable Audit Ledger & Forced-RLS Conformance**: Control-plane mutations emit immutable audit records under PostgreSQL Row-Level Security (`fn_owner_audit_insert_policy`), cleanly managing and restoring `app.current_tenant_id`.
- **Public Demo Route Independence**: Public demo routes (`/`, `/app`, `/reconcile`, `/dashboard`) remain completely database-independent and functional without authentication or active database connections.

---

## 2. Database Roles & Schema Hardening

The database privilege topology isolates sensitive operations across five roles:

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                             untangle_migrator                               │
│  - DDL Owner: Owns schema public, runs Alembic migrations                   │
│  - Owns public.trusted_auth_issuers (only role permitted to configure IdPs) │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ Grants exact privileges
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                             untangle_fn_owner                               │
│  - NOLOGIN Execution Role: Owns all 23 SECURITY DEFINER control-plane funcs │
│  - Granted exact DML on control-plane tables and exact sequence access      │
│  - Has explicit INSERT policy on public.audit_events                        │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ Grants EXECUTE ONLY
                    ┌──────────────────┴──────────────────┐
                    ▼                                     ▼
┌──────────────────────────────────────┐ ┌────────────────────────────────────┐
│             untangle_app             │ │        untangle_maintenance        │
│  - Runtime Application Role          │ │  - Maintenance Role: CLI runner    │
│  - NOSUPERUSER NOBYPASSRLS           │ │  - Granted EXECUTE ONLY on 4 purge │
│  - Tenant Data: Scoped CRUD under RLS│ │    and redact functions            │
│  - Control Plane: EXECUTE on 15 funcs│ └────────────────────────────────────┘
└──────────────────────────────────────┘
                    ▲
                    │ Grants EXECUTE ONLY
┌──────────────────────────────────────┐
│            untangle_auth             │
│  - Authentication Connection Role    │
│  - Granted EXECUTE ONLY on 5 auth    │
│    and session creation functions    │
└──────────────────────────────────────┘
```

### Schema Hardening Guarantees
1. `REVOKE CREATE ON SCHEMA public FROM PUBLIC, untangle_app;` prevents unauthorized schema creation.
2. `REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;` prevents default execute privileges.
3. No table grants on `organisations`, `principals`, `organisation_memberships`, `user_sessions`, `organisation_invitations`, `oidc_auth_transactions`, or `control_plane_security_events` are granted to `untangle_app`.
4. Sequence usage is granted strictly for the 8 specific sequences used by control-plane tables.

---

## 3. Authoritative Manifest of All 23 Privileged Functions

All 23 functions execute with `SECURITY DEFINER` and a pinned `SET search_path = public, pg_temp`.

### Category 1: OIDC & Pre-Authentication (`untangle_auth`)
1. `public.fn_oidc_create_transaction(p_public_id, p_state_hash, p_nonce_hash, p_code_verifier_encrypted, p_return_to, p_expires_at)`
2. `public.fn_oidc_consume_transaction(p_state_hash)`
3. `public.fn_auth_resolve_federated_identity(p_issuer, p_subject, p_email, p_display_name, p_principal_public_id, p_fed_public_id)`
4. `public.fn_auth_create_session(p_public_id, p_principal_id, p_session_token_hash, p_active_org_id, p_ip_hash, p_user_agent_truncated, p_idle_exp, p_abs_exp)`
5. `public.fn_sec_event_record(p_public_id, p_event_type, p_actor_principal_id, p_subject_type, p_subject_identifier, p_ip_hash, p_user_agent_truncated, p_details_json)` *(Shared with `untangle_app`)*

### Category 2: Authenticated Sessions & Control Plane (`untangle_app`)
6. `public.fn_auth_lookup_session(p_session_token_hash)`
7. `public.fn_auth_touch_session_throttled(p_session_token_hash, p_idle_window_seconds, p_throttle_seconds)`
8. `public.fn_auth_revoke_session(p_session_token_hash)`
9. `public.fn_auth_revoke_all_sessions(p_session_token_hash)`
10. `public.fn_auth_switch_organisation(p_session_token_hash, p_target_org_id, p_new_token_hash, p_idle_exp, p_abs_exp, p_audit_public_id)`
11. `public.fn_org_create(p_session_token_hash, p_org_name, p_org_public_id, p_membership_public_id, p_audit_public_id_1, p_audit_public_id_2)`
12. `public.fn_org_list(p_session_token_hash)`
13. `public.fn_membership_list(p_session_token_hash)`
14. `public.fn_membership_mutate_with_mutex(p_session_token_hash, p_target_principal_id, p_new_role_code, p_new_status, p_audit_public_id)`
15. `public.fn_invitation_create(p_session_token_hash, p_email, p_role_code, p_token_hash, p_invitation_public_id, p_audit_public_id, p_expires_at)`
16. `public.fn_invitation_lookup(p_token_hash)`
17. `public.fn_invitation_accept_with_mutex(p_session_token_hash, p_token_hash, p_membership_public_id, p_audit_public_id_1, p_audit_public_id_2)`
18. `public.fn_invitation_revoke(p_session_token_hash, p_invitation_public_id, p_audit_public_id)`
19. `public.fn_invitation_list(p_session_token_hash)`

### Category 3: Data Retention & Purge (`untangle_maintenance`)
20. `public.fn_maintenance_purge_security_events(p_retention_days INT DEFAULT 90)`
21. `public.fn_maintenance_purge_oidc_transactions(p_retention_hours INT DEFAULT 1)`
22. `public.fn_maintenance_purge_expired_sessions(p_retention_days INT DEFAULT 30)`
23. `public.fn_maintenance_redact_accepted_invitations(p_retention_days INT DEFAULT 14)`

---

## 4. OpenID Connect (OIDC) Authentication Flow

Identity federation implements RFC 7636 Proof Key for Code Exchange (PKCE) via Authlib:

```text
User Browser              Untangle WebApp                     Trusted IdP
     │                           │                                 │
     │ 1. GET /api/auth/login    │                                 │
     ├──────────────────────────►│                                 │
     │                           │ 2. Generate PKCE verifier/state │
     │                           │    Derive AES key via HKDF      │
     │                           │    Store encrypted transaction  │
     │ 3. 302 Redirect to IdP    │    Set __Host-untangle_oidc_state
     │◄──────────────────────────┤                                 │
     │                                                             │
     │ 4. User authenticates & consents                            │
     ├────────────────────────────────────────────────────────────►│
     │                                                             │
     │ 5. 302 Redirect to callback with code & state               │
     │◄────────────────────────────────────────────────────────────┤
     │                                                             │
     │ 6. GET /api/auth/callback?code=...&state=...                │
     ├──────────────────────────►│                                 │
     │                           │ 7. Verify state HMAC & cookie   │
     │                           │    Consume transaction (1-time) │
     │                           │    Exchange code with PKCE      │
     │                           ├────────────────────────────────►│
     │                           │ 8. Return tokens (ID token)     │
     │                           │◄────────────────────────────────┤
     │                           │ 9. Verify JWKS signature        │
     │                           │    Validate email_verified=TRUE │
     │                           │    Resolve federated identity   │
     │                           │    Issue session & CSRF cookie  │
     │ 10. 302 Redirect return_to│                                 │
     │◄──────────────────────────┤                                 │
```

### Security Defenses:
- **State Single-Use & Expiry**: `fn_oidc_consume_transaction` atomically sets `consumed_at = NOW()` and returns 0 rows if already consumed or expired.
- **Identity Collision Protection**: If an incoming federated identity claims an email belonging to an existing principal with a different subject/issuer, login is rejected with `IdentityCollisionError` and logged to security audit.
- **PKCE Encryption**: Code verifiers are encrypted with AES-256-GCM using keys derived via HKDF-SHA256 from `UNTANGLE_SECRET_KEY`.

---

## 5. Session Lifecycle & Expiry Math

### Invariant Equation
The schema and application strictly enforce:
$$\text{last\_active\_at} \le \text{idle\_expires\_at} \le \text{absolute\_expires\_at}$$

- **Idle Window**: 30 minutes (`timedelta(minutes=30)`).
- **Absolute Lifetime**: 12 hours (`timedelta(hours=12)`).
- **Sliding Window Capping**: Each session touch extends `idle_expires_at` to $\min(\text{now} + 30\text{m}, \text{absolute\_expires\_at})$.
- **Touch Throttling**: Updates to `last_active_at` are throttled to once every 60 seconds to prevent write exhaustion on the database.
- **Token Rotation**: Switching organisations via `fn_auth_switch_organisation` revokes the old session token and issues a new cryptographically random token.

### Stale Session Invalidation via `membership_auth_version`
Each `organisation_memberships` record carries an integer `auth_version` (starting at 1).
When an owner or admin modifies a member's role or status:
1. `fn_membership_mutate_with_mutex` atomically increments `auth_version`.
2. Existing sessions for the target user in that organisation are revoked.
3. If an active session token is presented with `session.membership_auth_version < membership.auth_version`, `fn_auth_lookup_session` flags `is_stale = TRUE`.
4. The authentication middleware immediately invalidates the session and returns HTTP 401 Unauthorized (`SESSION_REVOKED`).

---

## 6. 5-Role Capability & Permission Matrix

The five roles enforce precision boundaries:

| Action / Capability | Owner | Admin | Operator | Reviewer | Auditor |
|---|:---:|:---:|:---:|:---:|:---:|
| **Reconciliation Runs** | | | | | |
| Initiate / Complete / Fail Run | Yes | Yes | Yes | No | No |
| Delete Run | Yes | Yes | No | No | No |
| View Runs, Results & Artifacts | Yes | Yes | Yes | Yes | Yes |
| **Certificates & Investigations** | | | | | |
| Issue Certificate | Yes | Yes | Yes | No | No |
| Close Investigation | Yes | Yes | Yes | No | No |
| View Certificates & Close Records | Yes | Yes | Yes | Yes | Yes |
| **Audit Ledger** | | | | | |
| View Organisation Audit Events | Yes | Yes | Yes | Yes | Yes |
| **Organisation & Membership Management** | | | | | |
| Create Invitations | Yes | Yes | No | No | No |
| Revoke Invitations | Yes | Yes | No | No | No |
| Invite or Promote to Admin | Yes | Yes | No | No | No |
| Invite or Promote to Owner | Yes | No | No | No | No |
| Demote or Remove Admin | Yes | Yes | No | No | No |
| Demote or Remove Owner | Yes | No | No | No | No |
| Modify Own Role or Status | No | No | No | No | No |
| Update Organisation Settings | Yes | Yes | No | No | No |
| Delete Organisation | Yes | No | No | No | No |

### Last-Owner Invariant Protection
`fn_membership_mutate_with_mutex` acquires a row lock (`FOR UPDATE`) on `organisations` and asserts that active owners count remains $\ge 1$. Concurrently attempting to demote or remove the final active owner raises SQLSTATE `P0003`, guaranteeing that an organisation can never become ownerless.

---

## 7. CSRF & Cookie Security

1. **RFC 6265bis Conforming Cookies**:
   - Session Cookie: `__Host-untangle_session` (`HttpOnly=True`, `Secure=True`, `SameSite=Lax`, `Path=/`).
   - OIDC Cookie: `__Host-untangle_oidc_state` (`HttpOnly=True`, `Secure=True`, `SameSite=Lax`, `Path=/`).
2. **Double-Submit HMAC-SHA256 CSRF Token**:
   - Cookie `untangle_csrf` is issued with value:
     $$\text{HMAC-SHA256}(\text{UNTANGLE\_SECRET\_KEY}, \text{session\_token\_hash} \parallel \text{":csrf"})$$
   - Header `X-CSRF-Token` is checked via `hmac.compare_digest` in constant time for all mutating methods (`POST`, `PUT`, `PATCH`, `DELETE`).
3. **Fail-Closed Origin Verification**:
   - Validates `Origin` / `Referer` against configured `UNTANGLE_ALLOWED_ORIGINS`.
   - Rejects missing headers with HTTP 403 `CSRF_ORIGIN_MISSING`.

---

## 8. Multi-Tenant Route Guard & Public Demo Isolation

- **Tenant Guard Middleware**: All mutating and tenant data endpoints require a valid session with a non-null `active_organisation_id`. Requests with `active_organisation_id IS NULL` are rejected with HTTP 403 Forbidden (`NO_ACTIVE_ORGANISATION`), guiding the user to select or create an organisation.
- **Exempt Routes**: `/api/auth/*` and public demo endpoints (`/`, `/app`, `/reconcile`, `/dashboard`, `/presentation`) bypass the tenant guard and run in-memory without database credentials.

---

## 9. Data Retention & Maintenance Operations

Retention automation runs offline via the CLI command using the `untangle_maintenance` role:
```bash
python -m persistence.maintenance purge \
    --sessions-days 30 \
    --invites-days 14 \
    --sec-events-days 90 \
    --oidc-hours 1
```

- Acquires PostgreSQL advisory lock `pg_try_advisory_lock(hashtext('untangle_maintenance_purge'))`.
- Purges security events older than 90 days.
- Purges consumed or expired OIDC transactions older than 1 hour.
- Purges revoked or expired sessions older than 30 days.
- Redacts email addresses in accepted/revoked invitations older than 14 days to `redacted@untangle.internal`.
