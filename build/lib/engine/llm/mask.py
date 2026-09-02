"""PII masking applied before any text is sent to a language model (FR-011).

Deterministic, reversible-within-a-call masking: each distinct PII token maps to a
stable placeholder (e.g. ``<NAME_1>``) so the model still sees structure without the
raw value. Order of application matters (emails/phones before name heuristics).
"""

from __future__ import annotations

import re

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# VPA handles like name@ybl, x@okaxis (UPI) — mask the local part, keep the PSP suffix.
_VPA = re.compile(r"\b([A-Za-z0-9.\-_]{2,})@(ybl|okaxis|okhdfcbank|oksbi|okicici|paytm|apl|ibl)\b", re.I)
_PHONE = re.compile(r"(?<!\d)(?:\+?91[\-\s]?)?[6-9]\d{9}(?!\d)")
# "FROM RAJESH KUMAR", "MR/MS <NAME>" style person names in narrations.
_PERSON = re.compile(r"\b(FROM|MR|MRS|MS|SHRI|SMT)\s+([A-Z][A-Z .]{2,40})", re.I)


class Masker:
    def __init__(self) -> None:
        self._map: dict[str, str] = {}
        self._counts: dict[str, int] = {}

    def _placeholder(self, kind: str, value: str) -> str:
        if value in self._map:
            return self._map[value]
        self._counts[kind] = self._counts.get(kind, 0) + 1
        ph = f"<{kind}_{self._counts[kind]}>"
        self._map[value] = ph
        return ph

    def mask(self, text: str) -> str:
        if not text:
            return text
        out = _EMAIL.sub(lambda m: self._placeholder("EMAIL", m.group(0)), text)
        out = _VPA.sub(lambda m: f"{self._placeholder('VPA', m.group(1))}@{m.group(2)}", out)
        out = _PHONE.sub(lambda m: self._placeholder("PHONE", m.group(0)), out)

        def _person(m: re.Match) -> str:
            return f"{m.group(1)} {self._placeholder('NAME', m.group(2).strip())}"

        out = _PERSON.sub(_person, out)
        return out

    @property
    def mapping(self) -> dict[str, str]:
        return dict(self._map)


def mask_text(text: str) -> str:
    """Convenience one-shot masker (fresh mapping)."""
    return Masker().mask(text)
