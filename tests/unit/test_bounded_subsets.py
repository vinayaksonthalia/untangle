"""Adversarial and resource-bound coverage for the bounded set-sum helper."""

from __future__ import annotations

from engine.bounded_subsets import find_bounded_subsets


def test_five_term_subset_is_recovered_by_identity_not_position():
    items = [("s5", 500), ("s1", 100), ("s4", 400), ("s2", 200), ("s3", 300)]

    result = find_bounded_subsets(items, 1500, min_terms=2, max_terms=5)

    assert result.exhausted is False
    assert result.subsets == (("s1", "s2", "s3", "s4", "s5"),)


def test_multiple_witnesses_are_ambiguous():
    items = [("a", 100), ("b", 200), ("c", 300), ("d", 400)]

    result = find_bounded_subsets(items, 500, min_terms=2, max_terms=5)

    assert result.exhausted is False
    assert len(result.subsets) == 2
    assert result.subsets[0] != result.subsets[1]


def test_combination_budget_exhaustion_fails_closed():
    items = [(f"s{i:03d}", i + 1) for i in range(24)]

    result = find_bounded_subsets(
        items,
        10_000,
        min_terms=2,
        max_terms=5,
        max_items=24,
        max_combinations=25,
    )

    assert result.exhausted is True
    assert result.subsets == ()


def test_all_identity_witnesses_are_considered_for_ambiguity():
    # Duplicate amounts create three valid 0/1 identities. Exact enumeration must
    # report ambiguity rather than treating the first two as a resource failure.
    items = [("a", 100), ("b", 100), ("c", 100), ("tail", 50)]

    result = find_bounded_subsets(items, 250, min_terms=3, max_terms=3, max_results=3)

    assert result.exhausted is False
    assert len(result.subsets) == 3


def test_input_order_does_not_change_witnesses():
    items = [("z", 100), ("a", 200), ("m", 300)]

    forward = find_bounded_subsets(items, 500, min_terms=2, max_terms=2)
    reverse = find_bounded_subsets(list(reversed(items)), 500, min_terms=2, max_terms=2)

    assert forward == reverse
