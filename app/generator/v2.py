"""Algorithm version v2: BSP-based room placement + MST corridors.

Released 2026-10. This module is FROZEN: any behavioural change must ship as
a new version so historical seeds keep reproducing their original layouts.

Rules (deterministic given the derived RNG):
  1. Recursively BSP-split the interior (1-cell wall margin) into leaves.
  2. Place one room per leaf, in traversal order, capped at ``room_count``.
  3. Connect rooms with a minimum spanning tree (Prim, Manhattan distance,
     deterministic tie-breaks) and carve L-shaped corridors for MST edges.
"""
from __future__ import annotations

from ..models import GenerationParams, Rect, Room, TileType
from ..rng import derive_rng
from .v1 import _carve_corridor

_MARGIN = 1


def _split(rng, rect: Rect, min_leaf: int, depth: int, max_depth: int, leaves: list[Rect]) -> None:
    can_h = rect.h >= 2 * min_leaf
    can_v = rect.w >= 2 * min_leaf
    if depth >= max_depth or (not can_h and not can_v):
        leaves.append(rect)
        return
    if can_h and can_v:
        horizontal = bool(rng.getrandbits(1))
    else:
        horizontal = can_h
    if horizontal:
        cut = rng.randint(rect.y + min_leaf, rect.bottom - min_leaf)
        first = Rect(rect.x, rect.y, rect.w, cut - rect.y)
        second = Rect(rect.x, cut, rect.w, rect.bottom - cut)
    else:
        cut = rng.randint(rect.x + min_leaf, rect.right - min_leaf)
        first = Rect(rect.x, rect.y, cut - rect.x, rect.h)
        second = Rect(cut, rect.y, rect.right - cut, rect.h)
    _split(rng, first, min_leaf, depth + 1, max_depth, leaves)
    _split(rng, second, min_leaf, depth + 1, max_depth, leaves)


def _mst_edges(rooms: list[Room]) -> list[tuple[int, int]]:
    """Prim's MST over room centers with fully deterministic tie-breaking."""
    if len(rooms) < 2:
        return []
    in_tree = {0}
    edges: list[tuple[int, int]] = []
    while len(in_tree) < len(rooms):
        best: tuple[int, int, int] | None = None  # (dist, a, b)
        for a in sorted(in_tree):
            ax, ay = rooms[a].center
            for b in range(len(rooms)):
                if b in in_tree:
                    continue
                bx, by = rooms[b].center
                dist = abs(ax - bx) + abs(ay - by)
                cand = (dist, a, b)
                if best is None or cand < best:
                    best = cand
        assert best is not None
        _, a, b = best
        edges.append((a, b))
        in_tree.add(b)
    return edges


def generate(seed: str, params: GenerationParams) -> tuple[list[list[int]], list[Room]]:
    rng = derive_rng("v2", seed, params.canonical())
    w, h = params.width, params.height
    grid = [[int(TileType.WALL)] * w for _ in range(h)]
    interior = Rect(_MARGIN, _MARGIN, max(0, w - 2 * _MARGIN), max(0, h - 2 * _MARGIN))

    min_leaf = max(params.min_room_size + 2, 4)
    max_depth = 8
    leaves: list[Rect] = []
    if interior.w > 0 and interior.h > 0:
        _split(rng, interior, min_leaf, 0, max_depth, leaves)

    rooms: list[Room] = []
    for room_id, leaf in enumerate(leaves[: params.room_count]):
        rw = rng.randint(params.min_room_size, params.max_room_size)
        rh = rng.randint(params.min_room_size, params.max_room_size)
        rw = max(1, min(rw, leaf.w))
        rh = max(1, min(rh, leaf.h))
        rx = rng.randint(leaf.x, leaf.right - rw)
        ry = rng.randint(leaf.y, leaf.bottom - rh)
        rect = Rect(rx, ry, rw, rh)
        rooms.append(Room(room_id=room_id, rect=rect))
        for x, y in rect.cells():
            grid[y][x] = TileType.FLOOR

    for a, b in _mst_edges(rooms):
        horizontal_first = bool(rng.getrandbits(1))
        _carve_corridor(grid, rooms[a].center, rooms[b].center, horizontal_first)

    return grid, rooms
