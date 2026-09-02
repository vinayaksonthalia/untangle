"""Versioned Narration Evidence Packs (Phase 2, Task 1).

Provides an immutable, versioned evidence pack boundary for payment-rail narration rules.
Narration rules are strictly decoupled from reconciliation-backed evidence (such as UTR
matching, amount correlation, and set-sum reconstruction).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from engine.models import BankCreditLine, EvidenceItem, Rail

DEFAULT_PACK_ID = "in.untangle.narration.default"
DEFAULT_PACK_VERSION = "1.0.0"
DEFAULT_PACK_SCHEMA_VERSION = "1.0.0"
SUPPORTED_SCHEMA_VERSIONS: frozenset[str] = frozenset({"1.0.0"})

# Characters that must create explicit token/whitespace boundaries rather than being stripped away:
# Zero-width spaces, joiners, formatting chars, BOM, soft hyphens, direction marks.
_ZERO_WIDTH_AND_INVISIBLE = re.compile(
    r"[\u200b\u200c\u200d\u200e\u200f\ufeff\u2060\u00ad\u202a\u202b\u202c\u202d\u202e]"
)
_MULTI_WHITESPACE = re.compile(r"\s+")


def normalize_narration(text: str) -> str:
    """Deterministic, boundary-preserving, idempotent Unicode narration normalizer.

    1. Applies Unicode NFKC normalization.
    2. Replaces zero-width, formatting, and invisible characters with a space boundary (' ')
       so adjacent alphanumeric runs are NEVER concatenated across removed characters.
    3. Collapses multiple whitespace runs into a single space.
    4. Trims leading and trailing whitespace.
    """
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text)
    with_boundaries = _ZERO_WIDTH_AND_INVISIBLE.sub(" ", normalized)
    return _MULTI_WHITESPACE.sub(" ", with_boundaries).strip()


class PackError(Exception):
    """Raised when evidence pack resolution, schema validation, or retrieval fails."""


@dataclass(frozen=True)
class NarrationEvidencePack:
    """Immutable, versioned rule pack for narration-derived evidence."""

    pack_id: str
    version: str
    schema_version: str
    description: str
    rail_keywords: MappingProxyType[Rail, tuple[str, ...]]
    decoy_markers: tuple[str, ...]
    rzp_brand: tuple[str, ...]
    rzp_context: tuple[str, ...]
    rzp_ifsc: str
    non_rzp_pattern_weight: float = 0.95
    rzp_brand_context_weight: float = 0.30
    rzp_brand_weak_weight: float = 0.15
    rzp_ifsc_weight: float = 0.25
    settlement_ref_weight: float = 0.50

    def evaluate_non_rzp_signals(self, line: BankCreditLine) -> dict[Rail, list[EvidenceItem]]:
        """Evaluate non-Razorpay narration patterns against normalized text."""
        text = normalize_narration(line.raw_text()).lower()
        out: dict[Rail, list[EvidenceItem]] = {}
        for rail, kws in self.rail_keywords.items():
            hit = None
            for kw in kws:
                if kw in text:
                    hit = kw
                    break
            if hit:
                out.setdefault(rail, []).append(
                    EvidenceItem(
                        signal=f"narration_pattern:{rail.value}",
                        detail=f"narration contains {hit!r}",
                        weight=self.non_rzp_pattern_weight,
                    )
                )
        return out

    def has_decoy_marker(self, line: BankCreditLine) -> str | None:
        """Check whether normalized narration contains any decoy markers."""
        text = normalize_narration(line.raw_text()).lower()
        for marker in self.decoy_markers:
            if marker in text:
                return marker
        return None

    def evaluate_rzp_narration_signals(
        self,
        line: BankCreditLine,
        *,
        has_tokens: bool,
        matched_exact_utr: bool,
    ) -> list[EvidenceItem]:
        """Evaluate narration brand, context, IFSC, and settlement reference signals.

        Decoy markers void positive narration resemblance (brand, IFSC, settlement_ref),
        but do not erase independently backed report evidence (handled in engine.evidence).
        """
        ev: list[EvidenceItem] = []
        low = normalize_narration(line.raw_text()).lower()
        decoy = self.has_decoy_marker(line)
        if not decoy:
            has_brand = any(b in low for b in self.rzp_brand)
            has_ifsc = self.rzp_ifsc in low
            rzp_identity = has_brand or has_ifsc
            has_context = any(c in low for c in self.rzp_context)

            if has_brand and has_context:
                ev.append(
                    EvidenceItem(
                        "narration_brand_rzp",
                        "razorpay brand + settlement context",
                        self.rzp_brand_context_weight,
                    )
                )
            elif has_brand:
                ev.append(
                    EvidenceItem(
                        "narration_brand_rzp",
                        "razorpay brand token (weak)",
                        self.rzp_brand_weak_weight,
                    )
                )

            if has_ifsc:
                ev.append(
                    EvidenceItem(
                        "ifsc_ratn",
                        "RATN0000088 (Razorpay RBL settlement IFSC)",
                        self.rzp_ifsc_weight,
                    )
                )

            if rzp_identity and has_tokens and not matched_exact_utr:
                ev.append(
                    EvidenceItem(
                        "settlement_ref",
                        "UTR-shaped transfer reference with a Razorpay identity token",
                        self.settlement_ref_weight,
                    )
                )
        return ev

    def to_dict(self) -> dict[str, Any]:
        return {
            "pack_id": self.pack_id,
            "version": self.version,
            "schema_version": self.schema_version,
            "description": self.description,
        }


DEFAULT_NARRATION_PACK = NarrationEvidencePack(
    pack_id=DEFAULT_PACK_ID,
    version=DEFAULT_PACK_VERSION,
    schema_version=DEFAULT_PACK_SCHEMA_VERSION,
    description="Built-in default multi-rail narration evidence rules from existing origin/main.",
    rail_keywords=MappingProxyType({
        Rail.OTHER_GATEWAY: (
            "payu", "cashfree", "ccavenue", "cc avenue", "easebuzz",
            "billdesk", "instamojo", "infibeam", "phonepe payment",
        ),
        Rail.COD_REMITTANCE: (
            "cod", "shiprocket", "delhivery", "xpressbees", "ecom express",
            "shopify commerce", "cash on delivery",
        ),
        Rail.DIRECT_UPI: (
            "upi settlement", "upi merchant", "upi/cr", "bulk upi cr",
            "npci", "upi/", "@ybl", "@okaxis", "@paytm", "@okhdfcbank",
        ),
        Rail.UNRELATED: (
            "personal", "gst refund", "savings interest", "interest credit",
            "int.pd", "charges", " chg", "outward chg", "vendor refund",
            "payouts", "amazon seller", "salary", "loan disbursal", "cbic",
        ),
    }),
    decoy_markers=("payouts", "vendor refund", "@ybl", "collect", "payout"),
    rzp_brand=("razorpay", "rzp"),
    rzp_context=("settlement", "settle", "razorpay software", "razorpayx settlement"),
    rzp_ifsc="ratn0000088",
)

_REGISTRY: dict[tuple[str, str], NarrationEvidencePack] = {
    (DEFAULT_PACK_ID, DEFAULT_PACK_VERSION): DEFAULT_NARRATION_PACK,
}
PACK_REGISTRY: MappingProxyType[tuple[str, str], NarrationEvidencePack] = MappingProxyType(_REGISTRY)


def resolve_pack_provenance(value: Any) -> NarrationEvidencePack:
    """Resolve serialized pack provenance and reject unknown or malformed identities."""
    if not isinstance(value, dict) or set(value) != {"pack_id", "version", "schema_version", "description"}:
        raise PackError("Invalid evidence-pack provenance shape")
    if not all(isinstance(value[k], str) for k in ("pack_id", "version", "schema_version", "description")):
        raise PackError("Evidence-pack provenance fields must be strings")
    pack = get_pack(f"{value['pack_id']}@{value['version']}")
    if value["schema_version"] != pack.schema_version:
        raise PackError("Evidence-pack schema version does not match registry")
    if value["description"] != pack.description:
        raise PackError("Evidence-pack description does not match registry")
    return pack


def parse_pack_selector(selector: str | None = None) -> tuple[str, str]:
    """Parse a pack selector in the format 'pack_id@version' or return defaults."""
    if selector is None or selector == "default":
        return DEFAULT_PACK_ID, DEFAULT_PACK_VERSION
    if not isinstance(selector, str):
        raise PackError(f"Invalid pack selector type: {type(selector).__name__}; expected str")
    s = selector.strip()
    if not s:
        return DEFAULT_PACK_ID, DEFAULT_PACK_VERSION
    if "@" in s:
        pid, _, ver = s.partition("@")
        pid = pid.strip()
        ver = ver.strip()
        if not pid or not ver:
            raise PackError(f"Malformed pack selector {selector!r}; expected format 'pack_id@version'")
        return pid, ver
    return s, DEFAULT_PACK_VERSION


def get_pack(selector: str | None = None) -> NarrationEvidencePack:
    """Resolve an immutable evidence pack by selector ('pack_id@version') or return default."""
    pid, ver = parse_pack_selector(selector)
    pack = PACK_REGISTRY.get((pid, ver))
    if pack is None:
        available = [f"{p}@{v}" for (p, v) in PACK_REGISTRY.keys()]
        raise PackError(
            f"Unknown narration evidence pack: {pid}@{ver}. Available built-in packs: {', '.join(available)}"
        )
    if pack.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise PackError(
            f"Unsupported evidence pack schema version {pack.schema_version!r} for pack {pid}@{ver}. "
            f"Supported schema versions: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
        )
    return pack


def get_default_pack() -> NarrationEvidencePack:
    """Return the immutable built-in default pack."""
    return DEFAULT_NARRATION_PACK
