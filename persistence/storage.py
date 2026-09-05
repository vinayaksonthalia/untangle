"""Durable object storage abstraction supporting S3-compatible backends and local development.

Provides streaming uploads, in-flight SHA-256 calculation, provider checksum verification,
bounded read-back validation, and opaque tenant-isolated keys.
"""

from __future__ import annotations

import base64
import hashlib
import io
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Protocol


class StorageError(Exception):
    """Base exception for storage backend failures."""


class StorageConfigurationError(StorageError):
    """Raised when required storage configuration is missing or invalid."""


class SecurityViolationError(StorageError):
    """Raised when path traversal or unauthorized object access is detected."""


class ChecksumMismatchError(StorageError):
    """Raised when an object's calculated digest does not match the stored checksum."""


class PayloadTooLargeError(StorageError):
    """Raised when an upload exceeds the maximum permitted byte size."""


class ObjectNotFoundError(StorageError, KeyError):
    """Raised when a requested object is not found."""


@dataclass(frozen=True)
class StoredObjectMetadata:
    """Metadata for a durably stored object."""

    key: str
    size_bytes: int
    sha256_checksum: str
    content_type: str
    etag: str | None
    version_id: str | None
    backend: str


class ObjectStorageBackend(Protocol):
    """Protocol defining the object storage operations."""

    def store_bytes(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> StoredObjectMetadata: ...

    def store_stream(
        self,
        key: str,
        stream: BinaryIO,
        max_bytes: int = 15 * 1024 * 1024,
        content_type: str = "application/octet-stream",
    ) -> StoredObjectMetadata: ...

    def retrieve_bytes(self, key: str) -> bytes: ...

    def retrieve_stream(self, key: str) -> BinaryIO: ...

    def copy_object(self, source_key: str, dest_key: str) -> StoredObjectMetadata: ...

    def delete_object(self, key: str) -> bool: ...

    def delete_prefix(self, prefix: str) -> int: ...

    def exists(self, key: str) -> bool: ...

    def head_bucket(self) -> bool: ...


def sanitize_filename(filename: str) -> str:
    """Strip path traversal elements and unsafe characters from filenames."""
    name = Path(filename).name
    clean = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return clean[:128] or "file"


def generate_input_object_key(
    tenant_public_id: str,
    run_public_id: str,
    file_role: str,
    content_sha256: str,
    original_filename: str,
) -> str:
    """Generate an opaque, tenant-isolated key for an uploaded input file."""
    safe_name = sanitize_filename(original_filename)
    hash_prefix = content_sha256[:16]
    return f"tenants/{tenant_public_id}/runs/{run_public_id}/inputs/{file_role}_{hash_prefix}_{safe_name}"


def generate_artifact_object_key(
    tenant_public_id: str,
    run_public_id: str,
    artifact_type: str,
    content_sha256: str,
    ext: str,
) -> str:
    """Generate an opaque key for a published reconciliation artifact."""
    clean_ext = re.sub(r"[^A-Za-z0-9]", "", ext)
    hash_prefix = content_sha256[:16]
    return f"tenants/{tenant_public_id}/runs/{run_public_id}/artifacts/{artifact_type}_{hash_prefix}.{clean_ext}"


def generate_staging_upload_key(
    tenant_public_id: str,
    upload_token: str,
    file_role: str,
) -> str:
    """Generate a temporary staging key for an in-flight file upload."""
    return f"tenants/{tenant_public_id}/staging/uploads/{upload_token}/{file_role}"


def generate_attempt_artifact_key(
    tenant_public_id: str,
    run_public_id: str,
    attempt_token: str,
    artifact_type: str,
    ext: str,
) -> str:
    """Generate an attempt-scoped staging key for worker artifacts prior to promotion."""
    clean_ext = re.sub(r"[^A-Za-z0-9]", "", ext)
    return f"tenants/{tenant_public_id}/runs/{run_public_id}/staging/attempts/{attempt_token}/{artifact_type}.{clean_ext}"


class S3StorageBackend:
    """Shared S3-compatible object storage implementation using boto3."""

    def __init__(
        self,
        bucket_name: str,
        *,
        endpoint_url: str | None = None,
        region_name: str = "ap-south-1",
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        use_ssl: bool = True,
        force_path_style: bool = False,
        server_side_encryption: str | None = None,
    ) -> None:
        import boto3
        from botocore.config import Config

        self.bucket_name = bucket_name
        self.server_side_encryption = server_side_encryption
        s3_config = Config(
            signature_version="s3v4",
            s3={"addressing_style": "path" if force_path_style else "auto"},
        )
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region_name,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            use_ssl=use_ssl,
            config=s3_config,
        )

    def store_bytes(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> StoredObjectMetadata:
        return self.store_stream(
            key, io.BytesIO(data), max_bytes=len(data) + 1, content_type=content_type
        )

    def store_stream(
        self,
        key: str,
        stream: BinaryIO,
        max_bytes: int = 15 * 1024 * 1024,
        content_type: str = "application/octet-stream",
    ) -> StoredObjectMetadata:
        hasher = hashlib.sha256()
        buffer = io.BytesIO()
        total_bytes = 0

        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                break
            total_bytes += len(chunk)
            if total_bytes > max_bytes:
                raise PayloadTooLargeError(f"Uploaded stream exceeded limit of {max_bytes} bytes")
            hasher.update(chunk)
            buffer.write(chunk)

        computed_sha256 = hasher.hexdigest()
        buffer.seek(0)

        put_kwargs: dict[str, Any] = {
            "Bucket": self.bucket_name,
            "Key": key,
            "Body": buffer,
            "ContentType": content_type,
            "Metadata": {
                "sha256": computed_sha256,
            },
        }
        if self.server_side_encryption:
            put_kwargs["ServerSideEncryption"] = self.server_side_encryption

        response = self.client.put_object(**put_kwargs)
        etag = response.get("ETag")
        version_id = response.get("VersionId")

        # Provider ChecksumSHA256 assertion if returned (note: boto3 returns base64 string)
        if "ChecksumSHA256" in response:
            provider_b64 = response["ChecksumSHA256"]
            expected_bytes = bytes.fromhex(computed_sha256)
            if base64.b64decode(provider_b64) != expected_bytes:
                raise ChecksumMismatchError(f"Provider SHA256 checksum mismatch for key {key}")
        else:
            # Bounded read-back verification
            read_back = self.retrieve_bytes(key)
            if hashlib.sha256(read_back).hexdigest() != computed_sha256:
                raise ChecksumMismatchError(f"Read-back SHA256 verification failed for key {key}")

        return StoredObjectMetadata(
            key=key,
            size_bytes=total_bytes,
            sha256_checksum=computed_sha256,
            content_type=content_type,
            etag=etag,
            version_id=version_id,
            backend="s3",
        )

    def retrieve_bytes(self, key: str) -> bytes:
        from botocore.exceptions import ClientError

        try:
            response = self.client.get_object(Bucket=self.bucket_name, Key=key)
            return response["Body"].read()
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in ("NoSuchKey", "404", "NotFound"):
                raise ObjectNotFoundError(f"Object not found: {key}") from exc
            raise StorageError(f"Failed to retrieve object {key}: {exc}") from exc

    def retrieve_stream(self, key: str) -> BinaryIO:
        data = self.retrieve_bytes(key)
        return io.BytesIO(data)

    def copy_object(self, source_key: str, dest_key: str) -> StoredObjectMetadata:
        copy_source = {"Bucket": self.bucket_name, "Key": source_key}
        copy_kwargs: dict[str, Any] = {
            "Bucket": self.bucket_name,
            "CopySource": copy_source,
            "Key": dest_key,
        }
        if self.server_side_encryption:
            copy_kwargs["ServerSideEncryption"] = self.server_side_encryption

        self.client.copy_object(**copy_kwargs)
        head = self.client.head_object(Bucket=self.bucket_name, Key=dest_key)
        sha256_checksum = head.get("Metadata", {}).get("sha256", "")
        if not sha256_checksum:
            # Re-read to compute if metadata was not preserved
            data = self.retrieve_bytes(dest_key)
            sha256_checksum = hashlib.sha256(data).hexdigest()

        return StoredObjectMetadata(
            key=dest_key,
            size_bytes=head["ContentLength"],
            sha256_checksum=sha256_checksum,
            content_type=head.get("ContentType", "application/octet-stream"),
            etag=head.get("ETag"),
            version_id=head.get("VersionId"),
            backend="s3",
        )

    def delete_object(self, key: str) -> bool:
        self.client.delete_object(Bucket=self.bucket_name, Key=key)
        return True

    def delete_prefix(self, prefix: str) -> int:
        paginator = self.client.get_paginator("list_objects_v2")
        deleted_count = 0
        for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
            objects = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
            if objects:
                self.client.delete_objects(Bucket=self.bucket_name, Delete={"Objects": objects})
                deleted_count += len(objects)
        return deleted_count

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket_name, Key=key)
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey"):
                return False
            raise

    def head_bucket(self) -> bool:
        self.client.head_bucket(Bucket=self.bucket_name)
        return True


class LocalStorageBackend:
    """Local filesystem storage backend restricted to offline development and unit tests."""

    def __init__(self, base_dir: Path | str) -> None:
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _resolve_safe_path(self, key: str) -> Path:
        target = (self.base_dir / key).resolve()
        if not target.is_relative_to(self.base_dir):
            raise SecurityViolationError(f"Path traversal detected: {key}")
        return target

    def store_bytes(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> StoredObjectMetadata:
        return self.store_stream(
            key, io.BytesIO(data), max_bytes=len(data) + 1, content_type=content_type
        )

    def store_stream(
        self,
        key: str,
        stream: BinaryIO,
        max_bytes: int = 15 * 1024 * 1024,
        content_type: str = "application/octet-stream",
    ) -> StoredObjectMetadata:
        target = self._resolve_safe_path(key)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

        hasher = hashlib.sha256()
        total_bytes = 0
        tmp_target = target.with_suffix(".tmp")

        try:
            with open(tmp_target, "wb") as f:
                os.chmod(tmp_target, 0o600)
                while True:
                    chunk = stream.read(64 * 1024)
                    if not chunk:
                        break
                    total_bytes += len(chunk)
                    if total_bytes > max_bytes:
                        raise PayloadTooLargeError(
                            f"Uploaded stream exceeded limit of {max_bytes} bytes"
                        )
                    hasher.update(chunk)
                    f.write(chunk)
            os.replace(tmp_target, target)
        finally:
            if tmp_target.exists():
                try:
                    tmp_target.unlink()
                except OSError:
                    pass

        sha256_checksum = hasher.hexdigest()
        return StoredObjectMetadata(
            key=key,
            size_bytes=total_bytes,
            sha256_checksum=sha256_checksum,
            content_type=content_type,
            etag=f'"{sha256_checksum[:32]}"',
            version_id=None,
            backend="local",
        )

    def retrieve_bytes(self, key: str) -> bytes:
        target = self._resolve_safe_path(key)
        if not target.is_file():
            raise ObjectNotFoundError(f"Object not found: {key}")
        return target.read_bytes()

    def retrieve_stream(self, key: str) -> BinaryIO:
        return io.BytesIO(self.retrieve_bytes(key))

    def copy_object(self, source_key: str, dest_key: str) -> StoredObjectMetadata:
        src = self._resolve_safe_path(source_key)
        dst = self._resolve_safe_path(dest_key)
        if not src.is_file():
            raise ObjectNotFoundError(f"Source object not found: {source_key}")
        dst.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        data = src.read_bytes()
        dst.write_bytes(data)
        os.chmod(dst, 0o600)
        sha256_checksum = hashlib.sha256(data).hexdigest()
        return StoredObjectMetadata(
            key=dest_key,
            size_bytes=len(data),
            sha256_checksum=sha256_checksum,
            content_type="application/octet-stream",
            etag=f'"{sha256_checksum[:32]}"',
            version_id=None,
            backend="local",
        )

    def delete_object(self, key: str) -> bool:
        target = self._resolve_safe_path(key)
        if target.is_file():
            target.unlink()
            return True
        return False

    def delete_prefix(self, prefix: str) -> int:
        target_dir = self._resolve_safe_path(prefix)
        deleted = 0
        if target_dir.is_dir():
            for p in list(target_dir.rglob("*")):
                if p.is_file():
                    p.unlink()
                    deleted += 1
            # Clean up empty directories
            for d in sorted(target_dir.rglob("*"), key=lambda p: len(str(p)), reverse=True):
                if d.is_dir() and not any(d.iterdir()):
                    d.rmdir()
            if not any(target_dir.iterdir()):
                target_dir.rmdir()
        elif target_dir.is_file():
            target_dir.unlink()
            deleted = 1
        return deleted

    def exists(self, key: str) -> bool:
        target = self._resolve_safe_path(key)
        return target.is_file()

    def head_bucket(self) -> bool:
        return self.base_dir.is_dir()


def get_storage_backend() -> ObjectStorageBackend:
    """Factory creating the configured storage backend.

    In hosted/production mode, fails closed if S3 is not configured.
    """
    backend_type = os.environ.get("UNTANGLE_STORAGE_BACKEND", "").strip().lower()
    deploy_mode = os.environ.get("UNTANGLE_DEPLOY_MODE", "demo").strip().lower()

    if backend_type == "s3" or (not backend_type and deploy_mode in ("private", "production")):
        bucket = os.environ.get("UNTANGLE_S3_BUCKET")
        if not bucket:
            raise StorageConfigurationError(
                "UNTANGLE_S3_BUCKET must be configured for S3 storage backend"
            )
        return S3StorageBackend(
            bucket_name=bucket,
            endpoint_url=os.environ.get("UNTANGLE_S3_ENDPOINT_URL"),
            region_name=os.environ.get("UNTANGLE_S3_REGION", "ap-south-1"),
            aws_access_key_id=os.environ.get("UNTANGLE_S3_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("UNTANGLE_S3_SECRET_ACCESS_KEY"),
            use_ssl=os.environ.get("UNTANGLE_S3_USE_SSL", "true").lower() in ("true", "1", "yes"),
            force_path_style=os.environ.get("UNTANGLE_S3_FORCE_PATH_STYLE", "false").lower()
            in ("true", "1", "yes"),
            server_side_encryption=os.environ.get("UNTANGLE_S3_SERVER_SIDE_ENCRYPTION"),
        )

    if backend_type == "local" or deploy_mode == "demo":
        local_dir = os.environ.get("UNTANGLE_STORAGE_DIR", "./data/storage")
        return LocalStorageBackend(local_dir)

    raise StorageConfigurationError(f"Unknown or unconfigured storage backend: {backend_type}")
