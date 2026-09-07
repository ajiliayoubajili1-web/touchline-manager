"""Deterministic seeded random number generation.

Every random decision in the game flows through :class:`SeededRng` so that a
career started with a given seed reproduces exactly the same world and
simulation results. This makes bugs reproducible and the game testable.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass
class SeededRng:
    """A reproducible random stream, independent per stream name.

    Use separate *stream* names for logically distinct random processes so that
    changing one process never perturbs the results of another (stable world
    generation, stable match simulation, etc.).
    """

    seed: int
    _rngs: dict[str, random.Random] = None

    def __post_init__(self) -> None:
        if self._rngs is None:
            self._rngs = {}

    def _stream(self, stream: str) -> random.Random:
        if stream not in self._rngs:
            nested_seed = (self.seed ^ _mix_string(stream)) & ((1 << 64) - 1)
            self._rngs[stream] = random.Random(nested_seed)
        return self._rngs[stream]

    def reset(self) -> None:
        self._rngs = {}

    def randint(self, low: int, high: int, stream: str = "default") -> int:
        return self._stream(stream).randint(low, high)

    def randrange(self, low: int, high: int, stream: str = "default") -> int:
        return self._stream(stream).randrange(low, high)

    def choice(self, seq, stream: str = "default"):
        return self._stream(stream).choice(seq)

    def choices(self, seq, weights=None, k: int = 1, stream: str = "default"):
        return self._stream(stream).choices(seq, weights=weights, k=k)

    def sample(self, seq, k: int, stream: str = "default"):
        return self._stream(stream).sample(seq, k)

    def random(self, stream: str = "default") -> float:
        return self._stream(stream).random()

    def uniform(self, low: float, high: float, stream: str = "default") -> float:
        return self._stream(stream).uniform(low, high)

    def gauss(self, mu: float, sigma: float, stream: str = "default") -> float:
        return self._stream(stream).gauss(mu, sigma)

    def shuffle(self, seq, stream: str = "default") -> None:
        self._stream(stream).shuffle(seq)


def _mix_string(text: str) -> int:
    h = 14695981039346656037
    for byte in text.encode("utf-8"):
        h ^= byte
        h = (h * 1099511628211) & ((1 << 64) - 1)
    return h


def new_id(prefix: str, rng: SeededRng, stream: str = "ids") -> str:
    """Return a short, readable, unique-ish identifier.

    IDs are deterministic for a given seed: ``clb_0001``, ``ply_0042`` ...
    """
    return f"{prefix}_{rng.randint(100000, 999999, stream):0d}"