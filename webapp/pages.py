"""Server-rendered landing + upload pages, in the dashboard's design system."""

from __future__ import annotations

import pathlib
from functools import cache

_TEMPLATE_DIR = pathlib.Path(__file__).resolve().parent / "templates"


@cache
def _load_template(name: str) -> str:
    """Load a committed HTML template from webapp/templates, failing loudly.

    The landing page is a static, pre-built artifact (see tools/tailwind/build.sh):
    a missing or empty file is a build/packaging error, never a blank page served
    to a user, so raise rather than degrade silently.
    """
    path = _TEMPLATE_DIR / name
    if not path.is_file():
        raise FileNotFoundError(f"landing template not found: {path}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"landing template is empty: {path}")
    return text


def landing_page() -> str:
    """Return the pre-built landing page (self-hosted fonts + compiled CSS)."""
    return _load_template("landing.html")


def upload_page() -> str:
    """Return the pre-built upload page (posts to /reconcile)."""
    return _load_template("upload.html")


def verify_page() -> str:
    """Return the pre-built verify page (self-hosted fonts + compiled CSS)."""
    return _load_template("verify.html")


def dashboard_page() -> str:
    """Return the pre-built dashboard (its JS fetches live figures from /api/presentation)."""
    return _load_template("dashboard.html")


def investigate_page() -> str:
    """Return the investigate screen (its JS fetches cases from /api/investigations/sample)."""
    return _load_template("investigate.html")


