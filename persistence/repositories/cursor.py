"""Opaque cursor pagination helpers for tenant repositories."""

from __future__ import annotations

import base64
from datetime import UTC, datetime


def encode_cursor(dt: datetime, record_id: int) -> str:
    """Encode created_at timestamp and record ID into an opaque cursor."""
    raw = f"{dt.isoformat()}|{record_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def decode_cursor(cursor_str: str) -> tuple[datetime, int]:
    """Decode an opaque cursor into (created_at, record_id)."""
    try:
        raw = base64.urlsafe_b64decode(cursor_str.encode("ascii")).decode("utf-8")
        dt_str, id_str = raw.split("|", 1)
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt, int(id_str)
    except Exception as exc:
        raise ValueError(f"Invalid pagination cursor: {cursor_str!r}") from exc
