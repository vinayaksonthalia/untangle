"""Deterministic, fail-closed bounded subset-sum enumeration.

The reconciliation engine keeps its established exact 1--3-term search for the
normal candidate pool (up to 200 settlements).  A small pool can opt into the
4--5-term expansion below.  The combination budget makes the expanded search
explicitly bounded; callers abstain if a caller-supplied budget is exceeded.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import combinations


@dataclass(frozen=True)
class BoundedSubsetResult:
    """At most ``max_results`` distinct identity tuples and an exhaustion marker."""

    subsets: tuple[tuple[str, ...], ...]
    exhausted: bool = False


def find_legacy_subsets(
    items: Sequence[tuple[str, int]], target: int, *, max_results: int = 2
) -> BoundedSubsetResult:
    """Preserve the original indexed exact 2--3-term matcher.

    This path is intentionally amount-indexed rather than combination-enumerated:
    it supports the established candidate pool of up to 200 settlements without
    changing its performance or 1--3-term behavior.
    """
    if target <= 0 or max_results < 1:
        raise ValueError("invalid legacy subset-sum bounds")
    ordered = list(items)
    if len({item_id for item_id, _ in ordered}) != len(ordered):
        raise ValueError("subset-sum item identities must be unique")
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value <= 0 for _, value in ordered
    ):
        raise ValueError("subset-sum item amounts must be positive integers")

    value_to_ids: dict[int, list[str]] = {}
    for item_id, value in ordered:
        value_to_ids.setdefault(value, []).append(item_id)

    matches: list[tuple[str, ...]] = []
    seen: set[frozenset[str]] = set()

    # Preserve the original fast 2-term lookup and candidate ordering.
    for item_id, value in ordered:
        remainder = target - value
        for other_id in value_to_ids.get(remainder, []):
            if other_id <= item_id:
                continue
            subset = frozenset((item_id, other_id))
            if subset not in seen:
                seen.add(subset)
                matches.append((item_id, other_id))
                if len(matches) >= max_results:
                    return BoundedSubsetResult(tuple(matches))

    # Preserve the original fast 3-term lookup and candidate ordering.
    for first_index, (first_id, first_value) in enumerate(ordered):
        for second_id, second_value in ordered[first_index + 1 :]:
            remainder = target - first_value - second_value
            if remainder <= 0:
                continue
            for third_id in value_to_ids.get(remainder, []):
                if third_id <= second_id:
                    continue
                subset = frozenset((first_id, second_id, third_id))
                if subset not in seen:
                    seen.add(subset)
                    matches.append((first_id, second_id, third_id))
                    if len(matches) >= max_results:
                        return BoundedSubsetResult(tuple(matches))
    return BoundedSubsetResult(tuple(matches))


def find_bounded_subsets(
    items: Sequence[tuple[str, int]],
    target: int,
    *,
    tolerance: int = 0,
    min_terms: int = 1,
    max_terms: int = 5,
    max_items: int = 16,
    max_combinations: int = 100_000,
    max_results: int = 2,
    sort_items: bool = True,
) -> BoundedSubsetResult:
    """Find up to ``max_results`` distinct positive-item subsets matching ``target``.

    The search is exhaustive within the requested term bounds when it completes.
    It is bounded by ``max_items`` and ``max_combinations``; if either bound is
    exceeded, ``exhausted`` is true and ``subsets`` is empty so callers must fail
    closed.  Positive integer amounts make every combination a valid 0/1 identity
    subset.  Items are sorted by identity by default for reproducible output; the
    legacy engine path may preserve its existing candidate order with
    ``sort_items=False``.

    The engine uses ``max_items=16`` for the new 4--5-term expansion.  The separate
    ``find_legacy_subsets`` path handles its established 1--3-term pool of up to
    200 candidates with amount lookups rather than combination enumeration.
    """
    if target <= 0 or tolerance < 0 or min_terms < 0 or max_terms < min_terms:
        raise ValueError("invalid bounded subset-sum bounds")
    if max_items < 1 or max_combinations < 1 or max_results < 1:
        raise ValueError("bounded subset-sum budgets must be positive")

    ordered = list(items)
    if sort_items:
        ordered.sort(key=lambda item: item[0])
    if len(ordered) > max_items:
        return BoundedSubsetResult((), exhausted=True)
    if len({item_id for item_id, _ in ordered}) != len(ordered):
        raise ValueError("subset-sum item identities must be unique")
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value <= 0 for _, value in ordered
    ):
        raise ValueError("subset-sum item amounts must be positive integers")

    matches: list[tuple[str, ...]] = []
    examined = 0
    for term_count in range(min_terms, max_terms + 1):
        for combo in combinations(ordered, term_count):
            examined += 1
            if examined > max_combinations:
                return BoundedSubsetResult((), exhausted=True)
            if abs(sum(value for _, value in combo) - target) > tolerance:
                continue
            subset = tuple(item_id for item_id, _ in combo)
            matches.append(subset)
            if len(matches) >= max_results:
                return BoundedSubsetResult(tuple(matches))
    return BoundedSubsetResult(tuple(matches))
