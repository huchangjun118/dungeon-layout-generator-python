"""Deterministic RNG helpers.

All randomness in the system flows through seed derivation here so results
are reproducible across processes, platforms and request ordering.

We deliberately avoid Python's ``hash()`` (salted per process) and instead
use SHA-256 over a canonical encoding of the parts.
"""
from __future__ import annotations

import hashlib
import json
import random


def derive_seed(*parts: object) -> int:
    """Derive a stable 64-bit seed from arbitrary parts.

    The same parts always produce the same seed in any process, on any
    machine, at any time.
    """
    canonical = json.dumps(parts, sort_keys=True, separators=(",", ":"),
                           default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def make_rng(*parts: object) -> random.Random:
    """Create a Random instance seeded deterministically from parts."""
    return random.Random(derive_seed(*parts))
