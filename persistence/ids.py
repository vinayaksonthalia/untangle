"""Cryptographically secure, non-enumerable public identifier generators.

Public identifiers decouple internal database surrogate keys (BigInteger) from external APIs.
"""

from __future__ import annotations

import re
import secrets

# Type prefixes for public entities
PREFIX_ORGANISATION = "org_"
PREFIX_PRINCIPAL = "usr_"
PREFIX_MEMBERSHIP = "mem_"
PREFIX_RUN = "run_"
PREFIX_FILE = "file_"
PREFIX_RESULT = "res_"
PREFIX_INVESTIGATION = "inv_"
PREFIX_CERTIFICATE = "cert_"
PREFIX_ARTIFACT = "art_"
PREFIX_AUDIT_EVENT = "aud_"

_PUBLIC_ID_RE = re.compile(r"^[a-z]{3,4}_[0-9a-f]{32}$")


class PublicIdError(ValueError):
    """Raised when a public identifier is malformed or invalid."""


def generate_public_id(prefix: str) -> str:
    """Generate an opaque, non-enumerable public ID with 128 bits of entropy.

    Example: 'run_9a2f1b8c4d3e5f6a7b8c9d0e1f2a3b4c'
    """
    if not prefix.endswith("_") or len(prefix) < 4:
        raise PublicIdError(f"Invalid prefix: {prefix!r}. Must end with an underscore.")
    # 16 bytes = 32 hex chars = 128 bits of cryptographically secure entropy
    token = secrets.token_hex(16)
    return f"{prefix}{token}"


def validate_public_id(val: str, expected_prefix: str | None = None) -> str:
    """Validate that a public ID matches the canonical format and expected prefix."""
    if not isinstance(val, str) or not _PUBLIC_ID_RE.match(val):
        raise PublicIdError(f"Malformed public ID: {val!r}")
    if expected_prefix is not None and not val.startswith(expected_prefix):
        raise PublicIdError(
            f"Public ID {val!r} does not start with expected prefix {expected_prefix!r}"
        )
    return val
