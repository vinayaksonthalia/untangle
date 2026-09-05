"""Maintenance CLI runner and retention automation.

Executes control-plane data retention and redaction policies using the
least-privileged untangle_maintenance database role.

Usage:
    python -m persistence.maintenance purge --sessions-days 30 --invites-days 14 --sec-events-days 90 --oidc-hours 1
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select, text
from sqlalchemy.orm import Session

from persistence.config import (
    create_db_engine,
    create_session_factory,
    get_maintenance_database_url,
)
from persistence.models import (
    ControlPlaneSecurityEvent,
    OidcAuthTransaction,
    OrganisationInvitation,
    UserSession,
)

MAX_RETENTION_DAYS = 3650
MAX_RETENTION_HOURS = 87600


def _validate_retention(name: str, value: int, maximum: int) -> int:
    """Validate retention before acquiring locks or performing any deletion."""
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f"{name} must be an integer from 1 to {maximum}")
    return value


def run_maintenance_purge(
    session: Session,
    sessions_days: int = 30,
    invites_days: int = 14,
    sec_events_days: int = 90,
    oidc_hours: int = 1,
) -> dict[str, int]:
    """Execute retention purge and redaction operations under advisory locking."""
    sessions_days = _validate_retention("sessions_days", sessions_days, MAX_RETENTION_DAYS)
    invites_days = _validate_retention("invites_days", invites_days, MAX_RETENTION_DAYS)
    sec_events_days = _validate_retention("sec_events_days", sec_events_days, MAX_RETENTION_DAYS)
    oidc_hours = _validate_retention("oidc_hours", oidc_hours, MAX_RETENTION_HOURS)
    bind = session.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        # Acquire advisory lock
        lock_acquired = session.execute(
            text("SELECT pg_try_advisory_lock(hashtext('untangle_maintenance_purge'))")
        ).scalar()
        if not lock_acquired:
            return {"status": "skipped", "reason": "lock_held"}

        try:
            sec_purged = (
                session.execute(
                    text("SELECT public.fn_maintenance_purge_security_events(:days)"),
                    {"days": sec_events_days},
                ).scalar()
                or 0
            )

            oidc_purged = (
                session.execute(
                    text("SELECT public.fn_maintenance_purge_oidc_transactions(:hours)"),
                    {"hours": oidc_hours},
                ).scalar()
                or 0
            )

            sessions_purged = (
                session.execute(
                    text("SELECT public.fn_maintenance_purge_expired_sessions(:days)"),
                    {"days": sessions_days},
                ).scalar()
                or 0
            )

            invites_redacted = (
                session.execute(
                    text("SELECT public.fn_maintenance_redact_accepted_invitations(:days)"),
                    {"days": invites_days},
                ).scalar()
                or 0
            )

            session.commit()
            return {
                "security_events_purged": sec_purged,
                "oidc_transactions_purged": oidc_purged,
                "sessions_purged": sessions_purged,
                "invitations_redacted": invites_redacted,
            }
        finally:
            session.execute(
                text("SELECT pg_advisory_unlock(hashtext('untangle_maintenance_purge'))")
            )
            session.commit()

    # SQLite fallback
    now = datetime.now(UTC)

    # 1. Security events
    sec_cutoff = now - timedelta(days=sec_events_days)
    sec_events = session.scalars(
        select(ControlPlaneSecurityEvent).where(ControlPlaneSecurityEvent.created_at < sec_cutoff)
    ).all()
    sec_purged = len(sec_events)
    for e in sec_events:
        session.delete(e)

    # 2. OIDC transactions
    oidc_cutoff = now - timedelta(hours=oidc_hours)
    oidc_txs = session.scalars(
        select(OidcAuthTransaction).where(
            or_(
                OidcAuthTransaction.created_at < oidc_cutoff,
                OidcAuthTransaction.consumed_at.is_not(None),
            )
        )
    ).all()
    oidc_purged = len(oidc_txs)
    for tx in oidc_txs:
        session.delete(tx)

    # 3. Sessions
    sess_cutoff = now - timedelta(days=sessions_days)
    expired_sess = session.scalars(
        select(UserSession).where(
            or_(
                and_(UserSession.revoked_at.is_not(None), UserSession.revoked_at < sess_cutoff),
                UserSession.absolute_expires_at < sess_cutoff,
            )
        )
    ).all()
    sessions_purged = len(expired_sess)
    for s in expired_sess:
        session.delete(s)

    # 4. Redact invitations
    inv_cutoff = now - timedelta(days=invites_days)
    invs = session.scalars(
        select(OrganisationInvitation).where(
            OrganisationInvitation.status.in_(["accepted", "revoked"]),
            or_(
                and_(
                    OrganisationInvitation.accepted_at.is_not(None),
                    OrganisationInvitation.accepted_at < inv_cutoff,
                ),
                and_(
                    OrganisationInvitation.revoked_at.is_not(None),
                    OrganisationInvitation.revoked_at < inv_cutoff,
                ),
            ),
            OrganisationInvitation.email != "redacted@untangle.internal",
        )
    ).all()
    invites_redacted = len(invs)
    for inv in invs:
        inv.email = "redacted@untangle.internal"

    session.commit()
    return {
        "security_events_purged": sec_purged,
        "oidc_transactions_purged": oidc_purged,
        "sessions_purged": sessions_purged,
        "invitations_redacted": invites_redacted,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Untangle maintenance and retention runner")
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    purge_parser = subparsers.add_parser(
        "purge", help="Purge expired records and redact sensitive data"
    )

    def retention_arg(maximum: int):
        def parse(value: str) -> int:
            try:
                parsed = int(value)
            except ValueError as exc:
                raise argparse.ArgumentTypeError("must be an integer") from exc
            if not 1 <= parsed <= maximum:
                raise argparse.ArgumentTypeError(f"must be between 1 and {maximum}")
            return parsed

        return parse

    purge_parser.add_argument(
        "--sessions-days",
        type=retention_arg(MAX_RETENTION_DAYS),
        default=30,
        help="Purge sessions older than N days (default: 30)",
    )
    purge_parser.add_argument(
        "--invites-days",
        type=retention_arg(MAX_RETENTION_DAYS),
        default=14,
        help="Redact accepted/revoked invites older than N days (default: 14)",
    )
    purge_parser.add_argument(
        "--sec-events-days",
        type=retention_arg(MAX_RETENTION_DAYS),
        default=90,
        help="Purge security events older than N days (default: 90)",
    )
    purge_parser.add_argument(
        "--oidc-hours",
        type=retention_arg(MAX_RETENTION_HOURS),
        default=1,
        help="Purge consumed OIDC transactions older than N hours (default: 1)",
    )

    args = parser.parse_args()

    try:
        url = get_maintenance_database_url()
        engine = create_db_engine(url)
        factory = create_session_factory(engine)
        with factory() as session:
            results = run_maintenance_purge(
                session,
                sessions_days=args.sessions_days,
                invites_days=args.invites_days,
                sec_events_days=args.sec_events_days,
                oidc_hours=args.oidc_hours,
            )
            print(json.dumps(results, indent=2))
        return 0
    except Exception as exc:
        print(f"Maintenance runner failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
