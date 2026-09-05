"""Cryptographic primitives, hashing, token generation, and state encryption.

Provides zero-credential logging guarantees and constant-time verifications.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from typing import Final

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

DEFAULT_SALT: Final[bytes] = b"untangle_oidc_code_verifier_salt"


def hash_token(token: str) -> str:
    """Return the SHA-256 hex digest of a token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_ip(ip: str, salt: str = "") -> str:
    """Return the SHA-256 hex digest of an IP address with optional salt."""
    return hashlib.sha256((salt + ip).encode("utf-8")).hexdigest()


def truncate_user_agent(ua: str | None, max_length: int = 128) -> str | None:
    """Truncate a user-agent string to max_length characters."""
    if ua is None:
        return None
    return ua[:max_length]


def generate_session_token() -> str:
    """Generate a high-entropy URL-safe random session token."""
    return secrets.token_urlsafe(32)


def generate_invitation_token() -> str:
    """Generate a high-entropy URL-safe random invitation token."""
    return secrets.token_urlsafe(32)


def generate_csrf_token(secret_key: str, session_token_hash: str) -> str:
    """Generate an HMAC-SHA256 double-submit CSRF token bound to session token hash."""
    message = f"{session_token_hash}:csrf".encode()
    return hmac.new(secret_key.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_csrf_token(secret_key: str, session_token_hash: str, token: str) -> bool:
    """Verify an HMAC-SHA256 double-submit CSRF token in constant time."""
    expected = generate_csrf_token(secret_key, session_token_hash)
    return hmac.compare_digest(expected, token)


def derive_encryption_key(secret_key: str, salt: bytes = DEFAULT_SALT) -> bytes:
    """Derive a 32-byte encryption key from the application secret key using HKDF-SHA256."""
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=b"untangle_aes_gcm_kdf",
    )
    return hkdf.derive(secret_key.encode("utf-8"))


def encrypt_code_verifier(code_verifier: str, key: bytes) -> str:
    """Encrypt a PKCE code verifier using AES-GCM (12-byte random nonce).

    Returns a base64url-encoded string of (nonce + ciphertext + tag).
    """
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, code_verifier.encode("utf-8"), None)
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")


def decrypt_code_verifier(encrypted_b64: str, key: bytes) -> str:
    """Decrypt a PKCE code verifier from AES-GCM base64url representation."""
    raw = base64.urlsafe_b64decode(encrypted_b64.encode("ascii"))
    if len(raw) < 12:
        raise ValueError("Invalid encrypted payload: too short")
    nonce = raw[:12]
    ciphertext = raw[12:]
    aesgcm = AESGCM(key)
    decrypted_bytes = aesgcm.decrypt(nonce, ciphertext, None)
    return decrypted_bytes.decode("utf-8")
