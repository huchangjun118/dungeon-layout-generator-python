"""Versioning: old versions keep reproducing history; versions are distinct."""
import pytest

from app.generator import UnknownVersionError, available_versions, get_generator
from app.models import ALGORITHM_VERSIONS, GenerationParams

# Golden fingerprints frozen at release time. If a code change alters the
# output of a released version, these tests fail - that is the guard rail.
GOLDEN_V1 = "64cef47a369b2701823de5fd46fa00e7fbdfddf4259332d556ae563c3b6b5f86"
GOLDEN_V2 = "35253b2ec38795b93fe5bc940d6ddaaf50347bdfdaf29df2b0fee840b9c6cce6"


def _fp(version: str, seed: str) -> str:
    import hashlib

    p = GenerationParams(width=40, height=24, room_count=6, algorithm_version=version)
    grid, _ = get_generator(version)(seed, p)
    h = hashlib.sha256()
    for row in grid:
        h.update(bytes(row))
    return h.hexdigest()


def test_registry_matches_declared_versions():
    assert set(available_versions()) == set(ALGORITHM_VERSIONS)


def test_unknown_version_rejected():
    with pytest.raises(UnknownVersionError):
        get_generator("v999")


def test_versions_are_distinguishable():
    assert _fp("v1", "golden-seed") != _fp("v2", "golden-seed")


def test_v1_output_is_frozen():
    assert _fp("v1", "golden-seed") == GOLDEN_V1


def test_v2_output_is_frozen():
    assert _fp("v2", "golden-seed") == GOLDEN_V2
