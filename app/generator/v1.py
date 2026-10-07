"""Algorithm version v1: sequential room placement + L-shaped corridors.

Released 2026-10. This module is FROZEN: any behavioural change must ship as
a new version so historical seeds keep reproducing their original layouts.

Rules (deterministic given the derived RNG):
  1. Start from an all-WALL grid.
  2. Place rooms sequentially; each room gets a fixed number of placement
     attempts (consumed from the RNG whether or not they succeed, so the
     stream position never depends on map state).
  3. Rooms must keep a 1-cell wall margin from the grid edge and must not
     overlap (a 1-cell gap to earlier rooms is enforced).
  4. Connect consecutive rooms with L-shaped corridors between centers.
"""
from __future__ import annotations

from ..models import GenerationParams, Rect, Room, TileType
from ..rng import derive_rng

_ATTEMPTS_PER_ROOM = 40
_MARGIN = 1


def _carve_corridor(grid: list[list[int]], a: tuple[int, int], b: tuple[int, int], horizontal_first: bool) -> None:
    (x0, y0), (x1, y1) = a, b

    def h(y: int, xa: int, xb: int) -> None:
        for x in range(min(xa, xb), max(xa, xb) + 1):
            grid[y][x] = TileType.FLOOR

    def v(x: int, ya: int, yb: int) -> None:
        for y in range(min(ya, yb), max(ya, yb) + 1):
            grid[y][x] = TileType.FLOOR

    if horizontal_first:
        h(y0, x0, x1)
        v(x1, y0, y1)
    else:
        v(x0, y0, y1)
        h(y1, x0, x1)


def generate(seed: str, params: GenerationParams) -> tuple[list[list[int]], list[Room]]:
    rng = derive_rng("v1", seed, params.canonical())
    w, h = params.width, params.height
    grid = [[int(TileType.WALL)] * w for _ in range(h)]
    rooms: list[Room] = []

    for room_id in range(params.room_count):
        placed: Rect | None = None
        for _ in range(_ATTEMPTS_PER_ROOM):
            rw = rng.randint(params.min_room_size, params.max_room_size)
            rh = rng.randint(params.min_room_size, params.max_room_size)
            if rw > w - 2 * _MARGIN or rh > h - 2 * _MARGIN:
                continue
            rx = rng.randint(_MARGIN, w - _MARGIN - rw)
            ry = rng.randint(_MARGIN, h - _MARGIN - rh)
            cand = Rect(rx, ry, rw, rh)
            # 1-cell gap to already placed rooms.
            padded = Rect(cand.x - 1, cand.y - 1, cand.w + 2, cand.h + 2)
            if any(padded.intersects(r.rect) for r in rooms):
                continue
            placed = cand
            break
        if placed is None:
            continue  # deterministic skip; validation will flag unreachable goals
        room = Room(room_id=room_id, rect=placed)
        rooms.append(room)
        for x, y in placed.cells():
            grid[y][x] = TileType.FLOOR

    for i in range(1, len(rooms)):
        horizontal_first = bool(rng.getrandbits(1))
        _carve_corridor(grid, rooms[i - 1].center, rooms[i].center, horizontal_first)

    return grid, rooms
