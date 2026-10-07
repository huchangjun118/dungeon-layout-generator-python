"""Core data types for layout generation.

Only type definitions and pure helpers live here; no generation logic.
"""
from __future__ import annotations

import enum
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

#: All algorithm versions ever shipped. Old versions are kept forever so
#: historical seeds remain reproducible.
ALGORITHM_VERSIONS: tuple[str, ...] = ("v1", "v2")

#: Version used when the caller does not pin one explicitly.
DEFAULT_ALGORITHM_VERSION: str = "v2"


class TileType(enum.IntEnum):
    WALL = 0
    FLOOR = 1
    DOOR = 2


class LayoutStatus(str, enum.Enum):
    DRAFT = "draft"
    LOCKED = "locked"
    PUBLISHED = "published"


#: Legal status transitions. Anything not listed here is rejected.
ALLOWED_TRANSITIONS: dict[LayoutStatus, frozenset[LayoutStatus]] = {
    LayoutStatus.DRAFT: frozenset({LayoutStatus.LOCKED}),
    LayoutStatus.LOCKED: frozenset({LayoutStatus.DRAFT, LayoutStatus.PUBLISHED}),
    LayoutStatus.PUBLISHED: frozenset(),
}

#: Role required to perform a transition into the given status.
TRANSITION_ROLES: dict[LayoutStatus, str] = {
    LayoutStatus.LOCKED: "reviewer",
    LayoutStatus.DRAFT: "reviewer",
    LayoutStatus.PUBLISHED: "publisher",
}


@dataclass(frozen=True)
class GenerationParams:
    """Parameters that, together with the seed, fully determine a layout."""

    width: int
    height: int
    room_count: int
    min_room_size: int = 3
    max_room_size: int = 8
    algorithm_version: str = DEFAULT_ALGORITHM_VERSION

    def canonical(self) -> str:
        """Stable serialization independent of dict ordering / Python version."""
        return json.dumps(
            {
                "width": self.width,
                "height": self.height,
                "room_count": self.room_count,
                "min_room_size": self.min_room_size,
                "max_room_size": self.max_room_size,
                "algorithm_version": self.algorithm_version,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def contains(self, px: int, py: int) -> bool:
        return self.x <= px < self.right and self.y <= py < self.bottom

    def intersects(self, other: "Rect") -> bool:
        return not (
            self.right <= other.x
            or other.right <= self.x
            or self.bottom <= other.y
            or other.bottom <= self.y
        )

    def cells(self):
        for yy in range(self.y, self.y + self.h):
            for xx in range(self.x, self.x + self.w):
                yield xx, yy


@dataclass(frozen=True)
class Room:
    room_id: int
    rect: Rect

    @property
    def center(self) -> tuple[int, int]:
        return (self.rect.x + self.rect.w // 2, self.rect.y + self.rect.h // 2)


@dataclass
class Layout:
    """A generated layout plus its lifecycle metadata."""

    layout_id: str
    seed: str
    params: GenerationParams
    grid: list[list[int]]
    rooms: list[Room]
    status: LayoutStatus = LayoutStatus.DRAFT
    revision: int = 0

    def fingerprint(self) -> str:
        """Content hash of the generated geometry (excludes metadata)."""
        h = hashlib.sha256()
        h.update(self.params.canonical().encode())
        h.update(self.seed.encode())
        for row in self.grid:
            h.update(bytes(row))
        return h.hexdigest()


@dataclass(frozen=True)
class Violation:
    """A single constraint violation, located at a concrete position."""

    kind: str  # "connectivity" | "reachability" | "overlap" | "bounds"
    message: str
    x: int
    y: int


@dataclass(frozen=True)
class AuditEntry:
    layout_id: str
    revision: int
    actor: str
    action: str
    from_status: str
    to_status: str
    detail: str = ""


def layout_key(seed: str, params: GenerationParams) -> str:
    """Idempotency key: identical seed+params always map to the same key."""
    return hashlib.sha256(f"{seed}|{params.canonical()}".encode()).hexdigest()[:24]
