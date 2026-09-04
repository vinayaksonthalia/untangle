"""Regression tests for the keepalive ping contract (scripts/keepalive_ping.sh).

The keepalive workflow must stay warm-friendly (retry through a cold start) yet
still fail a run when the endpoint is genuinely unreachable — otherwise a broken
deploy leaves the scheduled workflow silently green. These tests pin both the
success path and the failure path by running the real script against a stubbed
`curl` placed on PATH, so a future edit that restores silent success is caught.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "keepalive_ping.sh"


def _run_with_stub_curl(tmp_path: Path, curl_script: str):
    """Run keepalive_ping.sh with a fake `curl` (given as bash) first on PATH."""
    fake_curl = tmp_path / "curl"
    fake_curl.write_text("#!/usr/bin/env bash\n" + curl_script + "\n")
    fake_curl.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{tmp_path}{os.pathsep}{env['PATH']}"
    env["KEEPALIVE_ATTEMPTS"] = "3"
    env["KEEPALIVE_SLEEP"] = "0"  # no real waiting in tests
    return subprocess.run(
        ["bash", str(SCRIPT), "https://example.test/healthz"],
        env=env,
        capture_output=True,
        text=True,
    )


def test_script_exists_and_is_bash():
    assert SCRIPT.is_file()
    assert SCRIPT.read_text().startswith("#!/usr/bin/env bash")


def test_awake_on_2xx_exits_zero(tmp_path):
    # curl -w "%{http_code}" writes the status code to stdout; body is discarded.
    r = _run_with_stub_curl(tmp_path, 'echo 200')
    assert r.returncode == 0, r.stderr
    assert "awake" in r.stdout


def test_3xx_counts_as_awake(tmp_path):
    r = _run_with_stub_curl(tmp_path, 'echo 302')
    assert r.returncode == 0, r.stderr
    assert "awake" in r.stdout


def test_transport_failure_fails_run(tmp_path):
    # curl itself failing (DNS/timeout) -> non-zero exit, script sees 000.
    r = _run_with_stub_curl(tmp_path, 'exit 7')
    assert r.returncode == 1
    assert "::error::" in r.stdout
    assert "000" in r.stdout


def test_http_error_fails_run(tmp_path):
    # A reachable-but-broken deploy (5xx) must not leave the workflow green.
    r = _run_with_stub_curl(tmp_path, 'echo 503')
    assert r.returncode == 1
    assert "::error::" in r.stdout


def test_recovers_after_cold_start_retry(tmp_path):
    # First two attempts fail, third returns 200 -> overall success (exit 0).
    counter = tmp_path / "n"
    curl = (
        f'n=$(cat "{counter}" 2>/dev/null || echo 0); '
        f'n=$((n + 1)); echo "$n" > "{counter}"; '
        'if [ "$n" -ge 3 ]; then echo 200; else echo 000; fi'
    )
    r = _run_with_stub_curl(tmp_path, curl)
    assert r.returncode == 0, r.stderr
    assert "awake" in r.stdout
    assert "attempt 3" in r.stdout
