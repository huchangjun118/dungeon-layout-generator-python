"""Local (partial) regeneration of an existing layout.

Guarantees:
  * cells outside the region are copied through byte-identically;
  * the result is a pure function of (layout, region, sub_seed), so a retry
    after interruption reproduces the exact same layout;
  * global connectivity is restored by carving corridors *inside* the region
    only (an L-path between two interior cells never leaves a rectangular
    region), so the untouched area is never modified, not even for stitching.
"""
from __future__ import annotations

from .generator import get_generator
from .models import (
    GenerationParams,
    Layout,
    Rect,
    Room,
    TileType,
)
from .rng import derive_rng
from .validation import _components, validate_layout


class RegenerationError(RuntimeError):
    """Raised when a region cannot be regenerated into a valid layout."""


def _clip(region: Rect, width: int, height: int) -> Rect:
    x0, y0 = max(region.x, 0), max(region.y, 0)
    x1, y1 = min(region.right, width), min(region.bottom, height)
    if x1 <= x0 or y1 <= y0:
        raise RegenerationError(f"region {region} does not intersect the grid")
    return Rect(x0, y0, x1 - x0, y1 - y0)


def _inside_anchor(comp: set[tuple[int, int]], region: Rect) -> tuple[int, int] | None:
    inside = [c for c in comp if region.contains(*c)]
    return min(inside) if inside else None


def _border_entry(comp: set[tuple[int, int]], region: Rect) -> tuple[int, int] | None:
    """For a component living outside the region: the region cell orthogonally
    adjacent to the component's smallest border cell (deterministic)."""
    entries: list[tuple[int, int]] = []
    for x, y in comp:
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if region.contains(nx, ny):
                entries.append((nx, ny))
    return min(entries) if entries else None


def _reconnect(grid: list[list[int]], region: Rect, rng) -> None:
    """Merge walkable components by carving L-corridors inside `region`."""
    from .generator.v1 import _carve_corridor

    for _ in range(1024):  # hard bound; each pass merges two components
        comps = _components(grid)
        if len(comps) <= 1:
            return
        comps.sort(key=lambda c: (len(c), min(c)))
        small, main = comps[0], comps[-1]

        src = _inside_anchor(small, region)
        if src is None:
            src = _border_entry(small, region)
            if src is None:
                x, y = min(small)
                raise RegenerationError(
                    f"walkable component at ({x}, {y}) neither enters nor "
                    "touches the region; cannot stitch without modifying "
                    "cells outside the region"
                )
            grid[src[1]][src[0]] = TileType.FLOOR

        dst = _inside_anchor(main, region)
        if dst is None:
            dst = _border_entry(main, region)
            if dst is None:
                x, y = min(main)
                raise RegenerationError(
                    f"main component (nearest cell ({x}, {y})) neither enters "
                    "nor touches the region; the regenerated content would be "
                    "an unreachable island"
                )
            grid[dst[1]][dst[0]] = TileType.FLOOR

        horizontal_first = bool(rng.getrandbits(1))
        _carve_corridor(grid, src, dst, horizontal_first)
    raise RegenerationError("failed to reconnect components within iteration bound")


def regenerate_region(layout: Layout, region: Rect, sub_seed: str) -> Layout:
    params = layout.params
    height = len(layout.grid)
    width = len(layout.grid[0]) if height else 0
    region = _clip(region, width, height)

    # 1. Regenerate the sub-grid with the SAME algorithm version, so the new
    #    content is indistinguishable in style from a full generation.
    area_ratio = (region.w * region.h) / max(1, width * height)
    sub_room_count = max(1, round(params.room_count * area_ratio))
    sub_params = GenerationParams(
        width=region.w,
        height=region.h,
        room_count=sub_room_count,
        min_room_size=min(params.min_room_size, max(1, region.w - 2), max(1, region.h - 2)),
        max_room_size=min(params.max_room_size, max(1, region.w - 2), max(1, region.h - 2)),
        algorithm_version=params.algorithm_version,
    )
    if sub_params.min_room_size > sub_params.max_room_size:
        sub_params = GenerationParams(
            **{**sub_params.__dict__, "max_room_size": sub_params.min_room_size}
        )
    gen = get_generator(params.algorithm_version)
    sub_grid, sub_rooms = gen(f"{layout.seed}::{sub_seed}", sub_params)

    # 2. Paste: only cells inside the region change.
    new_grid = [row[:] for row in layout.grid]
    for y in range(region.h):
        for x in range(region.w):
            new_grid[region.y + y][region.x + x] = sub_grid[y][x]

    # 3. Restore connectivity without touching anything outside the region.
    rng = derive_rng(
        "regen-corridor", layout.seed, str(region), sub_seed, params.algorithm_version
    )
    _reconnect(new_grid, region, rng)

    # 4. Rooms: keep those fully outside the region untouched; replace the
    #    rest with the freshly generated (offset) rooms.
    kept = [r for r in layout.rooms if not r.rect.intersects(region)]
    next_id = max((r.room_id for r in kept), default=-1) + 1
    new_rooms = list(kept)
    for i, r in enumerate(sub_rooms):
        moved = Rect(r.rect.x + region.x, r.rect.y + region.y, r.rect.w, r.rect.h)
        new_rooms.append(Room(room_id=next_id + i, rect=moved))
    new_rooms.sort(key=lambda r: r.room_id)

    violations = validate_layout(new_grid, new_rooms)
    if violations:
        v = violations[0]
        raise RegenerationError(
            f"regenerated layout violates {v.kind} at ({v.x}, {v.y}): {v.message}"
        )

    return Layout(
        layout_id=layout.layout_id,
        seed=layout.seed,
        params=layout.params,
        grid=new_grid,
        rooms=new_rooms,
        status=layout.status,
        revision=layout.revision + 1,
    )
