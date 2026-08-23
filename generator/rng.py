"""
Seeded, reproducible randomness. NO wall clock, NO global random state.

Every logically-independent stream of draws is derived from the master seed
plus a string name, so adding a new stream never perturbs existing ones
(important for reproducibility across code changes). This is why we do NOT
call random.random() / Math.random() anywhere in the data logic.
"""

from __future__ import annotations

import hashlib
import random
from typing import Iterable, List, Sequence, TypeVar

T = TypeVar("T")


def _derive_seed(master_seed: int, name: str) -> int:
    h = hashlib.sha256(f"{master_seed}:{name}".encode("utf-8")).hexdigest()
    return int(h[:16], 16)


class Rng:
    """A named, seeded random stream wrapping random.Random."""

    def __init__(self, master_seed: int, name: str):
        self._r = random.Random(_derive_seed(master_seed, name))
        self.name = name

    def rand(self) -> float:
        return self._r.random()

    def chance(self, p: float) -> bool:
        return self._r.random() < p

    def randint(self, a: int, b: int) -> int:
        return self._r.randint(a, b)

    def choice(self, seq: Sequence[T]) -> T:
        return self._r.choice(seq)

    def weighted_choice(self, choices: Sequence[T], weights: Sequence[float]) -> T:
        return self._r.choices(list(choices), weights=list(weights), k=1)[0]

    def sample(self, population: Sequence[T], k: int) -> List[T]:
        return self._r.sample(list(population), k)

    def shuffle(self, seq: List[T]) -> None:
        self._r.shuffle(seq)

    def token(self, length: int) -> str:
        """Base62-ish token for Razorpay-style IDs, deterministic."""
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
        return "".join(self._r.choice(alphabet) for _ in range(length))

    def digits(self, length: int) -> str:
        return "".join(self._r.choice("0123456789") for _ in range(length))

    def normal_int(self, mean: float, sd: float, lo: int, hi: int) -> int:
        v = int(round(self._r.gauss(mean, sd)))
        return max(lo, min(hi, v))
