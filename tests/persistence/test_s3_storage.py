"""Comprehensive tests for ObjectStorageBackend implementations (S3 and Local)."""

from __future__ import annotations

import hashlib
import io
import stat
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from persistence.storage import (
    LocalStorageBackend,
    PayloadTooLargeError,
    S3StorageBackend,
    SecurityViolationError,
    StorageConfigurationError,
    generate_artifact_object_key,
    generate_attempt_artifact_key,
    generate_input_object_key,
    generate_staging_upload_key,
    get_storage_backend,
)


@pytest.fixture
def s3_bucket_name() -> str:
    return "test-untangle-storage-bucket"


@pytest.fixture
def mock_s3(s3_bucket_name: str):
    with mock_aws():
        client = boto3.client("s3", region_name="ap-south-1")
        client.create_bucket(
            Bucket=s3_bucket_name,
            CreateBucketConfiguration={"LocationConstraint": "ap-south-1"},
        )
        yield client


def test_s3_storage_upload_download_and_checksum(mock_s3, s3_bucket_name: str) -> None:
    backend = S3StorageBackend(
        bucket_name=s3_bucket_name,
        region_name="ap-south-1",
    )

    data = b"test reconciliation content deterministic paise 10050"
    expected_hash = hashlib.sha256(data).hexdigest()
    expected_size = len(data)

    key = generate_staging_upload_key("org_test", "staging_01", "bank_statement")
    meta = backend.store_bytes(
        key=key,
        data=data,
        content_type="text/csv",
    )

    assert meta.backend == "s3"
    assert meta.key == key
    assert meta.size_bytes == expected_size
    assert meta.sha256_checksum == expected_hash

    # Download and verify
    downloaded = backend.retrieve_bytes(key)
    assert downloaded == data

    # Stream retrieve
    stream = backend.retrieve_stream(key)
    assert stream.read() == data

    assert backend.exists(key) is True


def test_s3_storage_rejects_payload_too_large(mock_s3, s3_bucket_name: str) -> None:
    backend = S3StorageBackend(
        bucket_name=s3_bucket_name,
        region_name="ap-south-1",
    )
    data = b"x" * 100
    key = "tenants/test/test.bin"
    with pytest.raises(PayloadTooLargeError, match="exceeded limit"):
        backend.store_stream(
            key=key,
            stream=io.BytesIO(data),
            max_bytes=50,
        )


def test_s3_storage_copy_and_delete(mock_s3, s3_bucket_name: str) -> None:
    backend = S3StorageBackend(
        bucket_name=s3_bucket_name,
        region_name="ap-south-1",
    )
    data = b"payload to copy and delete"
    sha = hashlib.sha256(data).hexdigest()

    src_key = "tenants/org_1/staging/file.csv"
    dst_key = generate_input_object_key("org_1", "run_1", "bank_statement", sha, "statement.csv")

    backend.store_bytes(key=src_key, data=data)

    copied_meta = backend.copy_object(source_key=src_key, dest_key=dst_key)
    assert copied_meta.key == dst_key
    assert backend.retrieve_bytes(dst_key) == data

    # Delete source
    assert backend.delete_object(src_key) is True
    assert backend.exists(src_key) is False


def test_s3_storage_delete_prefix(mock_s3, s3_bucket_name: str) -> None:
    backend = S3StorageBackend(
        bucket_name=s3_bucket_name,
        region_name="ap-south-1",
    )
    prefix = "tenants/org_purge/runs/run_999/"
    for i in range(3):
        k = f"{prefix}artifact_{i}.json"
        d = f"content_{i}".encode()
        backend.store_bytes(key=k, data=d)

    deleted_count = backend.delete_prefix(prefix)
    assert deleted_count == 3

    for i in range(3):
        k = f"{prefix}artifact_{i}.json"
        assert backend.exists(k) is False


def test_s3_head_bucket_and_missing_object(mock_s3, s3_bucket_name: str) -> None:
    backend = S3StorageBackend(
        bucket_name=s3_bucket_name,
        region_name="ap-south-1",
    )
    assert backend.head_bucket() is True
    assert backend.exists("non_existent_key") is False

    with pytest.raises(KeyError, match="Object not found"):
        backend.retrieve_bytes("non_existent_key")


def test_local_storage_crud_and_permissions(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage"
    backend = LocalStorageBackend(base_dir=storage_dir)

    data = b"local content deterministic paise 50000"
    sha = hashlib.sha256(data).hexdigest()
    key = generate_artifact_object_key("org_loc", "run_loc", "tally_xml", sha, "xml")

    meta = backend.store_bytes(
        key=key,
        data=data,
        content_type="application/xml",
    )

    assert meta.backend == "local"
    assert meta.key == key
    assert meta.size_bytes == len(data)
    assert meta.sha256_checksum == sha

    # Check file permissions (POSIX mode 0o600 on file, 0o700 on parent dirs)
    file_path = storage_dir / key
    assert file_path.exists()
    mode = stat.S_IMODE(file_path.stat().st_mode)
    assert mode == 0o600

    # Read back
    assert backend.retrieve_bytes(key) == data
    assert backend.retrieve_stream(key).read() == data
    assert backend.exists(key) is True

    # Copy
    dst_key = generate_artifact_object_key("org_loc", "run_loc_copy", "tally_xml", sha, "xml")
    copied = backend.copy_object(key, dst_key)
    assert copied.key == dst_key
    assert backend.retrieve_bytes(dst_key) == data

    # Delete
    assert backend.delete_object(key) is True
    assert backend.exists(key) is False


def test_local_storage_path_traversal_prevention(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage"
    backend = LocalStorageBackend(base_dir=storage_dir)

    malicious_keys = [
        "../escape.txt",
        "tenants/../../etc/passwd",
        "/absolute/path/attack",
        "tenants/org/../../../root",
    ]

    for bad_key in malicious_keys:
        with pytest.raises(SecurityViolationError, match="Path traversal detected"):
            backend.store_bytes(
                key=bad_key,
                data=b"bad",
            )

        with pytest.raises(SecurityViolationError, match="Path traversal detected"):
            backend.retrieve_bytes(bad_key)

        with pytest.raises(SecurityViolationError, match="Path traversal detected"):
            backend.delete_object(bad_key)


def test_local_storage_delete_prefix(tmp_path: Path) -> None:
    storage_dir = tmp_path / "storage"
    backend = LocalStorageBackend(base_dir=storage_dir)

    prefix = "tenants/org_1/runs/run_1/"
    for name in ["art1.json", "art2.json", "nested/art3.json"]:
        k = f"{prefix}{name}"
        backend.store_bytes(key=k, data=b"item")

    deleted = backend.delete_prefix(prefix)
    assert deleted == 3
    assert backend.exists(f"{prefix}art1.json") is False


def test_key_generator_formats() -> None:
    stg = generate_staging_upload_key("org_1", "stg_99", "file.csv")
    assert stg == "tenants/org_1/staging/uploads/stg_99/file.csv"

    inp = generate_input_object_key(
        "org_1", "run_1", "bank_statement", "abc1234567890123456", "Statement Jan 2026.csv"
    )
    assert (
        inp
        == "tenants/org_1/runs/run_1/inputs/bank_statement_abc1234567890123_Statement_Jan_2026.csv"
    )

    art = generate_artifact_object_key(
        "org_1", "run_1", "report_json", "abc1234567890123456", "json"
    )
    assert art == "tenants/org_1/runs/run_1/artifacts/report_json_abc1234567890123.json"

    att = generate_attempt_artifact_key("org_1", "run_1", "tok_abc", "tally_xml", "xml")
    assert att == "tenants/org_1/runs/run_1/staging/attempts/tok_abc/tally_xml.xml"


def test_factory_fails_closed_in_hosted_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNTANGLE_DEPLOY_MODE", "production")
    monkeypatch.delenv("UNTANGLE_S3_BUCKET", raising=False)
    monkeypatch.delenv("UNTANGLE_STORAGE_BACKEND", raising=False)

    with pytest.raises(StorageConfigurationError, match="UNTANGLE_S3_BUCKET must be configured"):
        get_storage_backend()
