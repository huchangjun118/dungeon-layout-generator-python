"""Deterministic RNG helpers.

All randomness in the system flows through here so results never depend on
process state, PYTHONHASHSEED, or call ordering across requests.
"""
from __future__ import annotations

import hashlib
import random


def derive_rng(*parts: str) -> random.Random:
    """Create a Random seeded deterministically from string parts.

    Uses SHA-256 over a length-prefixed encoding so that ("ab", "c") and
    ("a", "bc") cannot collide, and so the result is stable across processes
    (unlike the builtin ``hash()`` which is salted per process).
    """
    h = hashlib.sha256()
    for part in parts:
        data = part.encode("utf-8")
        h.update(len(data).to_bytes(8, "big"))
        h.update(data)
    seed_int = int.from_bytes(h.digest()[:16], "big")
    return random.Random(seed_int)
