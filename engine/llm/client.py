"""Provider-agnostic, OpenAI-compatible chat client (research R5).

Design constraints:
- ``--no-ai`` short-circuits to a no-op that returns ``None`` (interpreted upstream as
  "no proposal → UNKNOWN"). The default run and every test use this path — no keys needed.
- Provider, model and API key come from the environment / ``.env`` only, never CLI args.
- Uses the stdlib HTTP client (urllib) — no heavy vendor SDK.
- The client only ever *proposes*; a deterministic rule must confirm before any verdict
  stands (constitution II). This module cannot, on its own, produce a money verdict.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

# OpenAI-compatible base URLs per provider.
_ENDPOINTS = {
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "cerebras": "https://api.cerebras.ai/v1/chat/completions",
}


@dataclass
class LLMResponse:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


class LLMClient:
    """OpenAI-compatible client. When ``enabled`` is False every call is a no-op."""

    def __init__(
        self,
        *,
        enabled: bool,
        provider: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.enabled = enabled
        self.provider = provider
        self.model = model
        self._api_key = api_key
        self._timeout = timeout
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def complete(self, system: str, user: str) -> LLMResponse | None:
        """Return a completion, or None when AI is disabled / unavailable.

        The no-op branch is what the deterministic pipeline and all tests exercise.
        """
        if not self.enabled:
            return None
        if not (self.provider and self.model and self._api_key):
            return None
        url = _ENDPOINTS.get(self.provider)
        if not url:
            return None
        body = json.dumps(
            {
                "model": self.model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
        ).encode()
        # Only ever speak HTTP(S) to a configured provider — never file:// or a custom scheme,
        # even if a base URL is misconfigured (defence in depth; also satisfies bandit B310).
        if not url.lower().startswith(("https://", "http://")):
            return None
        req = urllib.request.Request(
            url,  # noqa: S310 — scheme validated above
            data=body,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # nosec B310 — scheme validated to http(s) above
                data = json.loads(resp.read().decode())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            return None
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return None
        usage = data.get("usage", {}) or {}
        pt = int(usage.get("prompt_tokens", 0))
        ct = int(usage.get("completion_tokens", 0))
        self.calls += 1
        self.prompt_tokens += pt
        self.completion_tokens += ct
        return LLMResponse(text=text, prompt_tokens=pt, completion_tokens=ct)
