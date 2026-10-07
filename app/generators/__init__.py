"""Registry of versioned generators."""
from __future__ import annotations

from app.generators.base import LayoutGenerator

_REGISTRY: dict[str, LayoutGenerator] = {}


def register(generator: LayoutGenerator) -> None:
    _REGISTRY[generator.version] = generator


def get_generator(version: str) -> LayoutGenerator:
    if version not in _REGISTRY:
        raise KeyError(f"unknown generator version: {version!r}")
    return _REGISTRY[version]


def latest_version() -> str:
    if not _REGISTRY:
        raise RuntimeError("no generators registered")
    return sorted(_REGISTRY)[-1]


def available_versions() -> list[str]:
    return sorted(_REGISTRY)


# Importing the modules registers their generators.
from app.generators import v1 as _v1  # noqa: E402,F401
from app.generators import v2 as _v2  # noqa: E402,F401
