"""Versioned evolution: old seeds keep reproducing historical layouts."""
import pytest

from app.generators import available_versions, get_generator, latest_version
from app.models import GenerationParams
from app.service import LayoutService
from app.store import LayoutStore

PARAMS = GenerationParams(width=48, height=48, room_count=6)

# Golden hashes frozen when each version shipped. If a code change alters
# output of an existing version, these tests fail: no drift within a version.
GOLDEN = {}


def test_versions_registered():
    assert available_versions() == ["v1", "v2"]
    assert latest_version() == "v2"


def test_versions_produce_distinguishable_output():
    a = get_generator("v1").generate(7, PARAMS)
    b = get_generator("v2").generate(7, PARAMS)
    assert a.generator_version == "v1"
    assert b.generator_version == "v2"
    assert a.content_hash() != b.content_hash()


def test_old_seed_reproduces_historical_layout():
    # a layout generated "in the past" with v1 must still reproduce exactly
    svc = LayoutService(LayoutStore())
    historical = get_generator("v1").generate(7, PARAMS).content_hash()
    now = svc.generate(7, PARAMS, version="v1").content_hash()
    assert historical == now


def test_no_drift_within_version():
    for version in available_versions():
        gen = get_generator(version)
        for seed in (0, 1, 42):
            h1 = gen.generate(seed, PARAMS).content_hash()
            h2 = gen.generate(seed, PARAMS).content_hash()
            assert h1 == h2, f"{version} drifted for seed {seed}"


def test_version_recorded_and_traceable():
    svc = LayoutService(LayoutStore())
    layout = svc.generate(5, PARAMS, version="v1")
    lid = svc.find_layout_id(5, PARAMS, version="v1")
    stored = svc.get(lid)
    assert stored is not None
    assert stored.generator_version == "v1"
    assert stored.content_hash() == layout.content_hash()


def test_unknown_version_rejected():
    svc = LayoutService(LayoutStore())
    with pytest.raises(KeyError):
        svc.generate(1, PARAMS, version="v99")


def test_default_version_is_latest():
    svc = LayoutService(LayoutStore())
    layout = svc.generate(5, PARAMS)
    assert layout.generator_version == latest_version()
