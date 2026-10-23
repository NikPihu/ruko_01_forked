"""Keyed random streams: controlled randomness you can reproduce and shrink.

Every draw in sim_v2 comes from `stream(seed, *key)`, e.g. stream(7, "routine", "u_000123").
The key names *who* draws and *for what*, never *how many others exist*, so:
  - the same seed gives the same world (reproducible, debuggable);
  - a different seed gives a new variation inside the same ranges;
  - a 500-user world contains exactly the first 500 users of the 20,000-user world.
"""
from __future__ import annotations

import bisect
import hashlib
import math

import numpy as np


class R:
    """A small wrapper around numpy's Generator with the draws the simulator needs."""

    def __init__(self, gen: np.random.Generator):
        self.g = gen

    def random(self) -> float:
        return float(self.g.random())

    def chance(self, p: float) -> bool:
        return self.g.random() < p

    def uniform(self, lo: float, hi: float) -> float:
        return float(self.g.uniform(lo, hi))

    def loguniform(self, lo: float, hi: float) -> float:
        return float(math.exp(self.g.uniform(math.log(lo), math.log(hi))))

    def integer(self, lo: int, hi: int) -> int:
        """lo..hi inclusive."""
        return int(self.g.integers(lo, hi + 1))

    def lognormal(self, median: float, sigma: float) -> float:
        return float(median * math.exp(self.g.normal(0, sigma)))

    def poisson(self, lam: float) -> int:
        return int(self.g.poisson(lam))

    def choice(self, items, p=None):
        items = items if isinstance(items, (list, tuple)) else list(items)
        if p is None:
            return items[int(self.g.random() * len(items))]
        # cumulative weights + one uniform draw: same result as numpy's weighted choice, ~20x faster
        acc, total = [], 0.0
        for w in p:
            total += float(w)
            acc.append(total)
        return items[min(bisect.bisect_right(acc, self.g.random() * total), len(items) - 1)]

    def weighted(self, weights: dict):
        """Pick a key of {option: weight}."""
        return self.choice(list(weights), list(weights.values()))

    def sample(self, items, k: int) -> list:
        items = list(items)
        idx = self.g.choice(len(items), size=min(k, len(items)), replace=False)
        return [items[int(i)] for i in idx]


def stream(seed: int, *key) -> R:
    digest = hashlib.blake2b(repr((seed, *key)).encode(), digest_size=16).digest()
    return R(np.random.Generator(np.random.Philox(key=int.from_bytes(digest, "little"))))


def draw(r: R, spec, prev: float | None = None, total: float | None = None):
    """Turn a range spec from YAML into a number.

    5                      -> 5 (fixed)
    [lo, hi]               -> uniform
    {log: [lo, hi]}        -> log-uniform (good for money and durations)
    {int: [lo, hi]}        -> integer, inclusive
    {of: prev, x: [a, b]}  -> previous ask times a uniform factor (escalation)
    {of: total, x: [a, b]} -> everything paid so far times a factor ("tax to withdraw")
    """
    if isinstance(spec, (int, float)):
        return spec
    if isinstance(spec, list):
        return r.uniform(*spec)
    if "log" in spec:
        return r.loguniform(*spec["log"])
    if "int" in spec:
        return r.integer(*spec["int"])
    if "of" in spec:
        base = {"prev": prev, "total": total}[spec["of"]] or 0.0
        return base * draw(r, spec["x"])
    raise ValueError(f"unknown range spec {spec!r}")
