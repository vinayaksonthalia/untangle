"""Configuration and secrets loading (constitution IV).

Secrets come ONLY from a gitignored ``.env`` file (never CLI flags). If AI is
requested (``--ai`` present) but the matching provider key is missing, we fail
fast with exit code 3 and a clear message — never a bare stack trace.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from engine.packs import DEFAULT_PACK_ID, NarrationEvidencePack, get_pack

_KEY_ENV = {
    "openrouter": "OPENROUTER_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
}

# A cost-model default (see abstain.py): a wrong auto-attribution corrupts downstream
# reconciliation and books far beyond a ~2-minute human review of an escalation.
DEFAULT_THRESHOLD = 0.55


class ConfigError(Exception):
    """Configuration problem (e.g. AI requested but no key). CLI maps this to exit 3."""


def load_dotenv(path: str = ".env") -> dict[str, str]:
    env: dict[str, str] = {}
    if not os.path.exists(path):
        return env
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


@dataclass
class Config:
    use_ai: bool
    provider: str | None
    model: str | None
    api_key: str | None
    threshold: float
    seed: int
    global_solver: bool = False
    evidence_pack_selector: str | None = DEFAULT_PACK_ID
    evidence_pack: NarrationEvidencePack | None = None

    def provider_or_none(self) -> str:
        return self.provider if self.use_ai else "none"


def build_config(
    *,
    no_ai: bool,
    provider: str | None,
    model: str | None,
    threshold: float | None,
    seed: int,
    dotenv_path: str = ".env",
    global_solver: bool = False,
    evidence_pack: str | None = None,
) -> Config:
    use_ai = not no_ai
    env = {**load_dotenv(dotenv_path), **os.environ}
    resolved_provider = provider or env.get("LLM_PROVIDER")
    resolved_model = model or env.get("LLM_MODEL")
    api_key = None
    if use_ai:
        if not resolved_provider:
            raise ConfigError(
                "AI is enabled but no provider is set. "
                "Pass --provider <openrouter|gemini|groq|cerebras> or set LLM_PROVIDER in .env, "
                "or run with --no-ai."
            )
        env_key = _KEY_ENV.get(resolved_provider)
        if not env_key:
            raise ConfigError(
                f"Unknown provider {resolved_provider!r}. "
                f"Choose one of: {', '.join(_KEY_ENV)}."
            )
        api_key = env.get(env_key)
        if not api_key:
            raise ConfigError(
                f"AI requested with provider {resolved_provider!r} but {env_key} is not set in .env. "
                f"Add {env_key}=... to .env, or run with --no-ai."
            )
        if not resolved_model:
            raise ConfigError(
                "AI requested but no model set. Pass --model <id> or set LLM_MODEL in .env."
            )
    # The abstention gate is a financial safety mechanism: a confidence must clear `threshold` to be
    # auto-attributed. A non-finite threshold (NaN/inf) or one outside [0, 1] silently defeats it —
    # e.g. `confidence < NaN` is always False, so low-confidence guesses get emitted instead of
    # abstained. Reject it rather than let an invalid runtime option disable the gate.
    resolved_threshold = DEFAULT_THRESHOLD if threshold is None else threshold
    # reconcile() is a reusable Python entry point too, so a caller may pass any type/value. Convert
    # an unsupported type (str, complex, ...) into the same ConfigError as other invalid thresholds.
    if isinstance(resolved_threshold, bool) or not isinstance(resolved_threshold, (int, float)):
        raise ConfigError(
            f"threshold must be a number in [0, 1]; got {resolved_threshold!r} of type "
            f"{type(resolved_threshold).__name__}."
        )
    # The [0, 1] range check alone rejects everything invalid WITHOUT ever raising: NaN (all its
    # comparisons are False), ±inf, out-of-range floats, and huge ints (bigint comparison never
    # overflows — unlike math.isfinite(10**1000), which raises OverflowError). A NaN/inf threshold
    # would otherwise silently defeat the abstention safety gate (confidence < NaN is always False).
    if not (0.0 <= resolved_threshold <= 1.0):
        raise ConfigError(
            f"threshold must be a finite number in [0, 1]; got {resolved_threshold!r}. "
            "The abstention gate cannot be disabled with an out-of-range, NaN, or inf threshold."
        )
    from engine.packs import PackError

    pack_selector = evidence_pack or env.get("EVIDENCE_PACK") or DEFAULT_PACK_ID
    try:
        resolved_pack = get_pack(pack_selector)
    except PackError as exc:
        raise ConfigError(str(exc)) from exc

    return Config(
        use_ai=use_ai,
        provider=resolved_provider if use_ai else None,
        model=resolved_model if use_ai else None,
        api_key=api_key,
        threshold=resolved_threshold,
        seed=seed,
        global_solver=global_solver,
        evidence_pack_selector=pack_selector,
        evidence_pack=resolved_pack,
    )
