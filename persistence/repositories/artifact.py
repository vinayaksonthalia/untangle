"""Artifact and uploaded file metadata repository.

Tracks file inputs and downloadable output artifacts bound to runs.
Does not persist raw user uploads or object bodies in Phase 1 (reserved for Phase 4).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from persistence.context import TenantContext
from persistence.ids import PREFIX_ARTIFACT, PREFIX_FILE, generate_public_id
from persistence.models import ArtifactMetadata, UploadedFileMetadata
from persistence.repositories.base import scoped_select
from persistence.uow import insert_with_public_id_retry


def save_uploaded_file_metadata(
    session: Session,
    context: TenantContext,
    run_id: int,
    *,
    file_role: str,
    original_filename: str,
    content_type: str,
    size_bytes: int,
    sha256_checksum: str,
    backend: str = "s3",
    object_key: str = "",
    lifecycle_state: str = "active",
    etag: str | None = None,
    version_id: str | None = None,
    encryption_algorithm: str | None = None,
) -> UploadedFileMetadata:
    """Persist metadata and content hash for an uploaded input file."""
    context.require_run_mutation("create")
    # Sanitize original_filename (prevent control characters, limit length)
    clean_filename = (
        "".join(c for c in original_filename if c.isprintable())[:255] or "unnamed_file"
    )

    return insert_with_public_id_retry(
        session,
        lambda: UploadedFileMetadata(
            public_id=generate_public_id(PREFIX_FILE),
            organisation_id=context.organisation_id,
            run_id=run_id,
            file_role=file_role,
            original_filename=clean_filename,
            content_type=content_type[:128],
            size_bytes=size_bytes,
            sha256_checksum=sha256_checksum,
            backend=backend,
            object_key=object_key,
            lifecycle_state=lifecycle_state,
            etag=etag,
            version_id=version_id,
            encryption_algorithm=encryption_algorithm,
        ),
        expected_constraint="uploaded_file_metadata_public_id_key",
    )


def list_uploaded_files_for_run(
    session: Session, context: TenantContext, run_id: int
) -> list[UploadedFileMetadata]:
    """List uploaded file metadata records for a run within the tenant scope."""
    stmt = scoped_select(UploadedFileMetadata, context).where(UploadedFileMetadata.run_id == run_id)
    return list(session.scalars(stmt).all())


def save_artifact_metadata(
    session: Session,
    context: TenantContext,
    run_id: int,
    *,
    artifact_type: str,
    filename: str,
    media_type: str,
    size_bytes: int,
    content_sha256: str,
    backend: str = "s3",
    object_key: str = "",
    lifecycle_state: str = "active",
    etag: str | None = None,
    version_id: str | None = None,
    encryption_algorithm: str | None = None,
) -> ArtifactMetadata:
    """Persist metadata and content hash for a generated output artifact."""
    context.require_run_mutation("complete")
    clean_filename = "".join(c for c in filename if c.isprintable())[:255] or "artifact"

    return insert_with_public_id_retry(
        session,
        lambda: ArtifactMetadata(
            public_id=generate_public_id(PREFIX_ARTIFACT),
            organisation_id=context.organisation_id,
            run_id=run_id,
            artifact_type=artifact_type,
            filename=clean_filename,
            media_type=media_type[:128],
            size_bytes=size_bytes,
            content_sha256=content_sha256,
            backend=backend,
            object_key=object_key,
            lifecycle_state=lifecycle_state,
            etag=etag,
            version_id=version_id,
            encryption_algorithm=encryption_algorithm,
        ),
        expected_constraint="artifact_metadata_public_id_key",
    )


def list_artifacts_for_run(
    session: Session, context: TenantContext, run_id: int
) -> list[ArtifactMetadata]:
    """List generated artifact metadata records for a run within the tenant scope."""
    stmt = scoped_select(ArtifactMetadata, context).where(ArtifactMetadata.run_id == run_id)
    return list(session.scalars(stmt).all())


def get_artifact_for_run_by_type(
    session: Session, context: TenantContext, run_id: int, artifact_type: str
) -> ArtifactMetadata | None:
    """Retrieve an artifact metadata record for a run by artifact type within the tenant scope."""
    stmt = (
        scoped_select(ArtifactMetadata, context)
        .where(ArtifactMetadata.run_id == run_id)
        .where(ArtifactMetadata.artifact_type == artifact_type)
    )
    return session.scalar(stmt)
