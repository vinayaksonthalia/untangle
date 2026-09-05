"""Control-plane repository for organisations, principals, and memberships.

Handles identity resolution and membership validation prior to constructing
a TenantContext and entering the tenant data-plane.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from persistence.context import Role, TenantContext, TenantContextError
from persistence.ids import (
    PREFIX_MEMBERSHIP,
    PREFIX_ORGANISATION,
    PREFIX_PRINCIPAL,
    generate_public_id,
)
from persistence.models import Organisation, OrganisationMembership, Principal
from persistence.uow import insert_with_public_id_retry


class ControlPlaneError(Exception):
    """Raised when control-plane identity resolution or validation fails."""


def get_principal(session: Session, principal_id: int) -> Principal | None:
    """Retrieve a principal by internal ID."""
    return session.scalar(
        select(Principal).where(Principal.id == principal_id, Principal.is_active.is_(True))
    )


def get_principal_by_public_id(session: Session, public_id: str) -> Principal | None:
    """Retrieve a principal by public ID."""
    return session.scalar(
        select(Principal).where(Principal.public_id == public_id, Principal.is_active.is_(True))
    )


def get_organisation(session: Session, organisation_id: int) -> Organisation | None:
    """Retrieve an organisation by internal ID."""
    return session.scalar(
        select(Organisation).where(
            Organisation.id == organisation_id, Organisation.is_active.is_(True)
        )
    )


def get_organisation_by_public_id(session: Session, public_id: str) -> Organisation | None:
    """Retrieve an organisation by public ID."""
    return session.scalar(
        select(Organisation).where(
            Organisation.public_id == public_id, Organisation.is_active.is_(True)
        )
    )


def get_active_membership(
    session: Session, organisation_id: int, principal_id: int
) -> OrganisationMembership | None:
    """Retrieve an active membership binding between a principal and an organisation."""
    return session.scalar(
        select(OrganisationMembership).where(
            OrganisationMembership.organisation_id == organisation_id,
            OrganisationMembership.principal_id == principal_id,
            OrganisationMembership.status == "active",
        )
    )


def issue_tenant_context(
    session: Session,
    principal_id: int,
    organisation_id: int,
    request_id: str = "",
) -> TenantContext:
    """Validate active principal, active organisation, and active membership before issuing TenantContext.

    Note on Security Architecture:
    The resulting TenantContext contains trusted inputs for application queries and PostgreSQL
    `set_config('app.current_tenant_id', ...)` session settings. PostgreSQL RLS relies on the
    application to provide a verified organisation ID; RLS acts as defence in depth against
    omitted query filters, not as an independent authentication provider.
    """
    principal = get_principal(session, principal_id)
    if principal is None or not principal.is_active:
        raise ControlPlaneError(f"Principal {principal_id} does not exist or is inactive")

    organisation = get_organisation(session, organisation_id)
    if organisation is None or not organisation.is_active:
        raise ControlPlaneError(f"Organisation {organisation_id} does not exist or is inactive")

    membership = get_active_membership(session, organisation_id, principal_id)
    if membership is None or membership.status != "active":
        raise ControlPlaneError(
            f"Principal {principal_id} does not hold an active membership in organisation {organisation_id}"
        )

    try:
        role = Role(membership.role_code)
    except ValueError as exc:
        raise TenantContextError(
            f"Membership has invalid role code {membership.role_code!r}"
        ) from exc

    return TenantContext(
        organisation_id=organisation.id,
        principal_id=principal.id,
        role=role,
        request_id=request_id,
    )


# ---------------------------------------------------------------------------
# Administrative / Provisioning Helpers (Used by tests & admin setup)
# ---------------------------------------------------------------------------


def create_organisation(session: Session, name: str) -> Organisation:
    """Create a new active organisation with collision retry."""
    return insert_with_public_id_retry(
        session,
        lambda: Organisation(
            public_id=generate_public_id(PREFIX_ORGANISATION),
            name=name,
            is_active=True,
        ),
        expected_constraint="organisations_public_id_key",
    )


def create_principal(
    session: Session, email: str, display_name: str, external_subject_id: str | None = None
) -> Principal:
    """Create a new active principal with collision retry."""
    return insert_with_public_id_retry(
        session,
        lambda: Principal(
            public_id=generate_public_id(PREFIX_PRINCIPAL),
            email=email,
            display_name=display_name,
            external_subject_id=external_subject_id,
            is_active=True,
        ),
        expected_constraint="principals_public_id_key",
    )


def create_membership(
    session: Session, organisation_id: int, principal_id: int, role: Role
) -> OrganisationMembership:
    """Create a new active organisation membership."""
    return insert_with_public_id_retry(
        session,
        lambda: OrganisationMembership(
            public_id=generate_public_id(PREFIX_MEMBERSHIP),
            organisation_id=organisation_id,
            principal_id=principal_id,
            role_code=role.value,
            status="active",
        ),
        expected_constraint="organisation_memberships_public_id_key",
    )
