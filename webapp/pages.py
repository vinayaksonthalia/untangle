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


def _page(name: str) -> str:
    html = _load_template(name)
    return html.replace("</head>", '<script src="/static/run-session.js"></script>\n</head>', 1)


def landing_page() -> str:
    """Return the pre-built landing page (self-hosted fonts + compiled CSS)."""
    return _page("landing.html")


def upload_page() -> str:
    """Return the pre-built upload page (posts to /reconcile)."""
    return _page("upload.html")


def verify_page() -> str:
    """Return the pre-built verify page (self-hosted fonts + compiled CSS)."""
    return _page("verify.html")


def dashboard_page() -> str:
    """Return the dashboard; its JS reads this tab's result bundle."""
    return _page("dashboard.html")


def investigate_page() -> str:
    """Return investigations from the same tab-local result as the dashboard."""
    return _page("investigate.html")


def certificate_page() -> str:
    """Return the printable document and download from this tab's certificate."""
    return _page("certificate.html")
