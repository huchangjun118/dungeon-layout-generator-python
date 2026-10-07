"""Determinism: same (seed, params, version) -> identical layout, always."""
import asyncio
import subprocess
import sys

from app.generator import get_generator
from app.models import GenerationParams
from app.service import LayoutService

PARAMS = GenerationParams(width=40, height=24, room_count=6)


def _fingerprint(version: str, seed: str) -> str:
    p = GenerationParams(
        width=PARAMS.width,
        height=PARAMS.height,
        room_count=PARAMS.room_count,
        algorithm_version=version,
    )
    grid, rooms = get_generator(version)(seed, p)
    import hashlib

    h = hashlib.sha256()
    for row in grid:
        h.update(bytes(row))
    return h.hexdigest()


def test_same_seed_same_params_identical_grid():
    for version in ("v1", "v2"):
        p = GenerationParams(width=40, height=24, room_count=6, algorithm_version=version)
        g1, r1 = get_generator(version)("alpha", p)
        g2, r2 = get_generator(version)("alpha", p)
        assert g1 == g2
        assert r1 == r2


def test_different_seeds_differ():
    p = GenerationParams(width=40, height=24, room_count=6)
    g1, _ = get_generator("v2")("alpha", p)
    g2, _ = get_generator("v2")("beta", p)
    assert g1 != g2


def test_reproducible_across_processes():
    """A fresh interpreter (simulating restart / another worker) must
    reproduce the exact same fingerprint."""
    code = (
        "from tests.test_determinism import _fingerprint;"
        "print(_fingerprint('v2', 'alpha'))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True,
        cwd=".",
    ).stdout.strip()
    assert out == _fingerprint("v2", "alpha")


def test_concurrent_requests_return_identical_layout():
    async def run():
        svc = LayoutService()
        p = GenerationParams(width=40, height=24, room_count=6)
        results = await asyncio.gather(
            *[svc.generate("gamma", p, actor=f"u{i}") for i in range(16)]
        )
        return results

    results = asyncio.run(run())
    first = results[0]
    for r in results[1:]:
        assert r is first  # singleflight: literally the same object


def test_request_order_does_not_matter():
    async def run(order):
        svc = LayoutService()
        p = GenerationParams(width=40, height=24, room_count=6)
        layouts = {}
        for seed in order:
            layouts[seed] = await svc.generate(seed, p, actor="u")
        return {k: v.fingerprint() for k, v in layouts.items()}

    a = asyncio.run(run(["s1", "s2", "s3"]))
    b = asyncio.run(run(["s3", "s1", "s2"]))
    assert a == b
