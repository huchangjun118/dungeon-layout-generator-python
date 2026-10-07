"""Concurrency, timeout and interruption recovery."""
import concurrent.futures as cf
import threading
import time

import pytest

import app.generators as generators_mod
from app.generators import get_generator, register
from app.models import GenerationParams
from app.service import LayoutService, make_key
from app.store import LayoutStore

PARAMS = GenerationParams(width=48, height=48, room_count=6)


class _SlowGen:
    """Test-only generator: v2 rules with an artificial delay."""

    version = "slow"
    _inner = get_generator("v2")

    def generate(self, seed, params):
        time.sleep(0.4)
        return self._inner.generate(seed, params)

    def regenerate_region(self, layout, region):
        return self._inner.regenerate_region(layout, region)


@pytest.fixture(autouse=True)
def _isolated_registry():
    """Keep test-only generators from leaking into other test modules."""
    saved = dict(generators_mod._REGISTRY)
    try:
        yield
    finally:
        generators_mod._REGISTRY.clear()
        generators_mod._REGISTRY.update(saved)


@pytest.fixture()
def slow_gen():
    gen = _SlowGen()
    register(gen)
    return gen


def test_concurrent_same_key_single_identical_result():
    svc = LayoutService(LayoutStore())
    with cf.ThreadPoolExecutor(16) as ex:
        results = list(ex.map(lambda _: svc.generate(5, PARAMS), range(16)))
    assert len({r.content_hash() for r in results}) == 1


def test_waiter_timeout_does_not_pollute_owner_result(slow_gen):
    svc = LayoutService(LayoutStore(), default_timeout_s=5.0)
    owner_result: list = []

    def owner():
        owner_result.append(svc.generate(5, PARAMS, version="slow"))

    t = threading.Thread(target=owner)
    t.start()
    time.sleep(0.05)  # ensure the owner claimed the job
    with pytest.raises(TimeoutError):
        svc.generate(5, PARAMS, version="slow", timeout_s=0.05)
    t.join()
    # owner finished cleanly; a later request gets the identical layout
    later = svc.generate(5, PARAMS, version="slow")
    assert later.content_hash() == owner_result[0].content_hash()
    assert later.content_hash() == get_generator("v2").generate(
        5, PARAMS).content_hash()


def test_cancelled_owner_leaves_no_debris():
    store = LayoutStore()
    svc = LayoutService(store)
    key = make_key("v1", 5, PARAMS)
    # simulate an owner cancelled mid-generation: claim then release
    assert store.begin_job(key, "v1") == "started"
    store.fail_job(key, "cancelled")
    assert store.job_status(key) is None  # no half-finished state
    # next request regenerates cleanly and deterministically
    layout = svc.generate(5, PARAMS, version="v1")
    assert layout.content_hash() == get_generator("v1").generate(
        5, PARAMS).content_hash()


def test_crash_recovery_regenerates_identical_layout(tmp_path):
    db = str(tmp_path / "layouts.db")
    expected = get_generator("v1").generate(5, PARAMS).content_hash()

    # process 1 "crashes" after claiming the job but before completing
    store1 = LayoutStore(db)
    key = make_key("v1", 5, PARAMS)
    assert store1.begin_job(key, "v1") == "started"
    store1.close()  # simulated crash: job left in 'running'

    # process 2 recovers and serves the same request
    store2 = LayoutStore(db)
    svc2 = LayoutService(store2)
    recovered = svc2.recover()
    assert recovered == [key]
    layout = svc2.generate(5, PARAMS, version="v1")
    assert layout.content_hash() == expected

    # process 3 (another restart) still returns the identical layout
    store2.close()
    svc3 = LayoutService(LayoutStore(db))
    assert svc3.generate(5, PARAMS, version="v1").content_hash() == expected


def test_persistence_across_restart(tmp_path):
    db = str(tmp_path / "layouts.db")
    svc1 = LayoutService(LayoutStore(db))
    a = svc1.generate(8, PARAMS, version="v2")
    svc1._store.close()
    svc2 = LayoutService(LayoutStore(db))
    b = svc2.generate(8, PARAMS, version="v2")
    assert a.content_hash() == b.content_hash()


def test_failed_generation_retries_then_raises():
    class _Broken:
        version = "broken"

        def generate(self, seed, params):
            raise RuntimeError("boom")

        def regenerate_region(self, layout, region):
            raise RuntimeError("boom")

    register(_Broken())
    svc = LayoutService(LayoutStore())
    with pytest.raises(RuntimeError, match="boom"):
        svc.generate(1, PARAMS, version="broken")
    # no debris: the key is claimable again
    key = make_key("broken", 1, PARAMS)
    assert svc._store.job_status(key) is None
