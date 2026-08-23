"""T009 — Isolation & least-privilege guard (constitution III/IV, FR-012, FR-014).

Static scans over engine/ source:
  1. No engine module imports the data generator.
  2. No engine module references ground_truth (only eval/ may read the answer key).
  3. FR-012: the only network-egress call site in engine/ is the LLM classification
     client — there is no other outbound path, so the engine cannot move money.
"""

from __future__ import annotations

import pathlib

ENGINE = pathlib.Path(__file__).resolve().parents[2] / "engine"


def _engine_files() -> list[pathlib.Path]:
    return sorted(ENGINE.rglob("*.py"))


def test_no_generator_import():
    offenders = []
    for f in _engine_files():
        src = f.read_text(encoding="utf-8")
        if "import generator" in src or "from generator" in src:
            offenders.append(str(f))
    assert not offenders, f"engine/ must not import generator: {offenders}"


def test_no_ground_truth_reference():
    offenders = []
    for f in _engine_files():
        if "ground_truth" in f.read_text(encoding="utf-8"):
            offenders.append(str(f))
    assert not offenders, f"engine/ must never reference ground_truth: {offenders}"


def test_network_egress_only_in_llm_client():
    """FR-012: no write/payout path. The sole outbound-network site is llm/client.py."""
    egress_tokens = ("urlopen", "http.client", "socket.socket", "requests.post", "requests.get")
    offenders = []
    for f in _engine_files():
        if f.name == "client.py" and f.parent.name == "llm":
            continue
        src = f.read_text(encoding="utf-8")
        for tok in egress_tokens:
            if tok in src:
                offenders.append(f"{f}: {tok}")
    assert not offenders, f"unexpected network egress outside llm/client.py: {offenders}"


def test_engine_does_not_open_ground_truth_file():
    for f in _engine_files():
        src = f.read_text(encoding="utf-8")
        assert "ground_truth.json" not in src, f"{f} must not open ground_truth.json"
