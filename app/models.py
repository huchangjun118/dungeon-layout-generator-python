"""Core data types for the dungeon layout generator.

All types are plain dataclasses with deterministic (de)serialization so that
layouts can be persisted, hashed and compared for reproducibility checks.
"""
from __future__ import annotations

import enum
import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any


class LayoutStatus(str, enum.Enum):
    """Lifecycle states of a layout."""

    DRAFT = "draft"
    LOCKED = "locked"
    PUBLISHED = "published"


class Role(str, enum.Enum):
    """Caller roles used by the permission checks."""

    VIEWER = "viewer"
    EDITOR = "editor"
    ADMIN = "admin"


@dataclass(frozen=True)
class Rect:
    """Axis-aligned rectangle, inclusive bounds in tile coordinates."""

    x: int
    y: int
    w: int
    h: int

    @property
    def x2(self) -> int:
        return self.x + self.w - 1

    @property
    def y2(self) -> int:
        return self.y + self.h - 1

    def contains(self, px: int, py: int) -> bool:
        return self.x <= px <= self.x2 and self.y <= py <= self.y2

    def intersects(self, other: "Rect") -> bool:
        return not (
            self.x2 < other.x
            or other.x2 < self.x
            or self.y2 < other.y
            or other.y2 < self.y
        )

    def center(self) -> tuple[int, int]:
        return (self.x + self.w // 2, self.y + self.h // 2)


@dataclass(frozen=True)
class Room:
    id: int
    rect: Rect
    kind: str = "normal"


@dataclass(frozen=True)
class Corridor:
    """An L-shaped corridor expressed as a list of grid points."""

    id: int
    points: tuple[tuple[int, int], ...]
    connects: tuple[int, int]  # room ids


@dataclass(frozen=True)
class GenerationParams:
    """Parameters controlling layout generation.

    Changing any field produces a different (but still deterministic) layout
    for the same seed.
    """

    width: int = 64
    height: int = 64
    room_count: int = 8
    min_room_size: int = 4
    max_room_size: int = 10
    extra_corridors: int = 1

    def canonical_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


@dataclass
class Layout:
    """A generated dungeon layout."""

    seed: int
    params: GenerationParams
    generator_version: str
    rooms: list[Room] = field(default_factory=list)
    corridors: list[Corridor] = field(default_factory=list)
    status: LayoutStatus = LayoutStatus.DRAFT
    revision: int = 0

    def canonical_dict(self) -> dict[str, Any]:
        """Content-only canonical form (excludes status/revision)."""
        return {
            "seed": self.seed,
            "params": asdict(self.params),
            "generator_version": self.generator_version,
            "rooms": [
                {"id": r.id, "rect": asdict(r.rect), "kind": r.kind}
                for r in self.rooms
            ],
            "corridors": [
                {"id": c.id, "points": [list(p) for p in c.points],
                 "connects": list(c.connects)}
                for c in self.corridors
            ],
        }

    def canonical_json(self) -> str:
        return json.dumps(self.canonical_dict(), sort_keys=True,
                          separators=(",", ":"))

    def content_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode()).hexdigest()

    def to_json(self) -> str:
        d = self.canonical_dict()
        d["status"] = self.status.value
        d["revision"] = self.revision
        return json.dumps(d, sort_keys=True)

    @staticmethod
    def from_json(raw: str) -> "Layout":
        d = json.loads(raw)
        params = GenerationParams(**d["params"])
        rooms = [Room(id=r["id"], rect=Rect(**r["rect"]), kind=r["kind"])
                 for r in d["rooms"]]
        corridors = [
            Corridor(id=c["id"],
                     points=tuple(tuple(p) for p in c["points"]),
                     connects=tuple(c["connects"]))
            for c in d["corridors"]
        ]
        return Layout(
            seed=d["seed"],
            params=params,
            generator_version=d["generator_version"],
            rooms=rooms,
            corridors=corridors,
            status=LayoutStatus(d.get("status", "draft")),
            revision=d.get("revision", 0),
        )


@dataclass(frozen=True)
class ConstraintViolation:
    """A single constraint failure, locatable to concrete positions."""

    code: str  # e.g. "overlap", "disconnected", "unreachable"
    message: str
    locations: tuple[tuple[int, int], ...] = ()


class ValidationError(Exception):
    def __init__(self, violations: list[ConstraintViolation]):
        self.violations = violations
        super().__init__(
            "; ".join(f"[{v.code}] {v.message} @ {v.locations}"
                      for v in violations)
        )


class StateTransitionError(Exception):
    """Raised on illegal status transitions or permission violations."""


class GenerationInProgress(Exception):
    """Raised internally to signal a duplicate in-flight generation."""
