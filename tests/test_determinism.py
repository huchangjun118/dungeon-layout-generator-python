"""Determinism: same (seed, params, version) -> identical layout, always."""
import concurrent.futures as cf
import subprocess
import sys

from app.generators import get_generator
from app.models import GenerationParams
from app.service import LayoutService
from app.store import LayoutStore

PARAMS = GenerationParams(width=48, height=48, room_count=6)


def test_same_seed_same_params_identical_layout():
    svc = LayoutService(LayoutStore())
    a = svc.generate(123, PARAMS, version="v1")
    b = svc.generate(123, PARAMS, version="v1")
    assert a.content_hash() == b.content_hash()


def test_different_seeds_differ():
    svc = LayoutService(LayoutStore())
    a = svc.generate(1, PARAMS, version="v1")
    b = svc.generate(2, PARAMS, version="v1")
    assert a.content_hash() != b.content_hash()


def test_different_params_differ():
    svc = LayoutService(LayoutStore())
    a = svc.generate(1, PARAMS, version="v1")
    b = svc.generate(1, GenerationParams(width=48, height=48, room_count=7),
                     version="v1")
    assert a.content_hash() != b.content_hash()


def test_deterministic_across_processes():
    code = (
        "from app.generators import get_generator;"
        "from app.models import GenerationParams;"
        "print(get_generator('v1').generate(123,"
        " GenerationParams(width=48, height=48, room_count=6))"
        ".content_hash())"
    )
    hashes = {
        subprocess.check_output([sys.executable, "-c", code]).decode().strip()
        for _ in range(3)
    }
    assert len(hashes) == 1
    local = get_generator("v1").generate(123, PARAMS).content_hash()
    assert hashes == {local}


def test_request_order_and_cache_independence():
    # populate cache in one order
    svc1 = LayoutService(LayoutStore())
    svc1.generate(1, PARAMS, version="v1")
    svc1.generate(2, PARAMS, version="v1")
    h1 = svc1.generate(3, PARAMS, version="v1").content_hash()
    # fresh service, different order
    svc2 = LayoutService(LayoutStore())
    svc2.generate(3, PARAMS, version="v1")
    svc2.generate(1, PARAMS, version="v1")
    h2 = svc2.generate(3, PARAMS, version="v1").content_hash()
    assert h1 == h2


def test_concurrent_identical_requests_are_idempotent():
    svc = LayoutService(LayoutStore())
    with cf.ThreadPoolExecutor(16) as ex:
        results = list(ex.map(
            lambda _: svc.generate(99, PARAMS, version="v2"), range(32)))
    assert len({r.content_hash() for r in results}) == 1


def test_concurrent_mixed_requests_no_cross_talk():
    svc = LayoutService(LayoutStore())
    seeds = list(range(20))
    with cf.ThreadPoolExecutor(8) as ex:
        got = list(ex.map(
            lambda s: svc.generate(s, PARAMS, version="v1").content_hash(),
            seeds))
    for s, h in zip(seeds, got):
        assert svc.generate(s, PARAMS, version="v1").content_hash() == h
