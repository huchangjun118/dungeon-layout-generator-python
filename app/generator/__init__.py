"""Versioned generator registry.

Each algorithm version is implemented in its own module and registered here
exactly once. Old versions are never modified after release, so a (seed,
params, version) triple reproduces the same layout forever.
"""
from __future__ import annotations

from typing import Callable

from ..models import ALGORITHM_VERSIONS, GenerationParams, Room

GeneratorFn = Callable[[str, GenerationParams], "tuple[list[list[int]], list[Room]]"]

_REGISTRY: dict[str, GeneratorFn] = {}


def register(version: str, fn: GeneratorFn) -> None:
    if version in _REGISTRY:
        raise ValueError(f"algorithm version {version!r} already registered")
    _REGISTRY[version] = fn


def get_generator(version: str) -> GeneratorFn:
    try:
        return _REGISTRY[version]
    except KeyError:
        raise UnknownVersionError(
            f"unknown algorithm version {version!r}; known: {sorted(_REGISTRY)}"
        ) from None


class UnknownVersionError(ValueError):
    """Raised when a layout references an algorithm version we do not ship."""


def available_versions() -> list[str]:
    return sorted(_REGISTRY)


from . import v1, v2  # noqa: E402  (register at import time, after defs)

register("v1", v1.generate)
register("v2", v2.generate)

assert set(available_versions()) == set(ALGORITHM_VERSIONS), (
    "registry and models.ALGORITHM_VERSIONS are out of sync"
)
