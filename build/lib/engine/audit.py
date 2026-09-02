"""Hash-chained audit ledger — whole-file snapshot (constitution IV, research R7).

Each entry stores the SHA-256 of the previous entry, forming a chain: tampering
with any past entry invalidates every hash after it. This is stated precisely as
"append-only with a hash chain"; stronger anchoring (committing the daily root to
git so a push timestamp fixes it) is an operational step outside this module.

Determinism: the ledger is written from an in-memory list in a fixed order and the
per-entry payload is canonical JSON, so identical inputs yield an identical chain
head. No wall-clock timestamps are embedded (they would break byte-identical reruns).
"""

from __future__ import annotations

import hashlib
import json
import os

GENESIS = "0" * 64


def _hash(prev: str, payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{prev}|{canonical}".encode()).hexdigest()


class AuditLedger:
    def __init__(self) -> None:
        self._entries: list[dict] = []
        self._head: str = GENESIS

    @property
    def root(self) -> str:
        return self._head

    def append(self, event: str, payload: dict) -> str:
        seq = len(self._entries)
        body = {"seq": seq, "event": event, "payload": payload, "prev": self._head}
        entry_hash = _hash(self._head, body)
        body["hash"] = entry_hash
        self._entries.append(body)
        self._head = entry_hash
        return entry_hash

    def write(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            for e in self._entries:
                fh.write(json.dumps(e, sort_keys=True, separators=(",", ":")) + "\n")

    @staticmethod
    def verify(path: str) -> bool:
        """Re-derive the chain from disk; return True iff every link is intact."""
        prev = GENESIS
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                e = json.loads(line)
                stored = e.pop("hash")
                if e.get("prev") != prev:
                    return False
                if _hash(prev, e) != stored:
                    return False
                prev = stored
        return True
