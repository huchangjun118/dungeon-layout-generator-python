"""Layout constraint validation.

Every violation is reported with the concrete coordinate that causes it, so
callers can locate the problem instead of silently shipping a broken layout.
Checked constraints:
  * bounds        - rooms must lie fully inside the grid
  * overlap       - room rectangles must not intersect
  * connectivity  - all FLOOR/DOOR cells form a single 4-connected component
  * reachability  - every room center is reachable from room 0's center
"""
from __future__ import annotations

from collections import deque

from .models import Room, TileType, Violation

_WALKABLE = (int(TileType.FLOOR), int(TileType.DOOR))


def _components(grid: list[list[int]]) -> list[set[tuple[int, int]]]:
    h = len(grid)
    w = len(grid[0]) if h else 0
    seen: set[tuple[int, int]] = set()
    comps: list[set[tuple[int, int]]] = []
    for y in range(h):
        for x in range(w):
            if grid[y][x] not in _WALKABLE or (x, y) in seen:
                continue
            comp: set[tuple[int, int]] = set()
            q = deque([(x, y)])
            seen.add((x, y))
            while q:
                cx, cy = q.popleft()
                comp.add((cx, cy))
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if (
                        0 <= nx < w
                        and 0 <= ny < h
                        and grid[ny][nx] in _WALKABLE
                        and (nx, ny) not in seen
                    ):
                        seen.add((nx, ny))
                        q.append((nx, ny))
            comps.append(comp)
    return comps


def validate_layout(grid: list[list[int]], rooms: list[Room]) -> list[Violation]:
    violations: list[Violation] = []
    h = len(grid)
    w = len(grid[0]) if h else 0

    # bounds
    for room in rooms:
        r = room.rect
        if r.x < 0 or r.y < 0 or r.right > w or r.bottom > h:
            violations.append(
                Violation(
                    kind="bounds",
                    message=f"room {room.room_id} extends outside the grid",
                    x=max(r.x, 0),
                    y=max(r.y, 0),
                )
            )

    # overlap (report the first colliding cell of each colliding pair)
    for i, a in enumerate(rooms):
        for b in rooms[i + 1 :]:
            if a.rect.intersects(b.rect):
                for x, y in a.rect.cells():
                    if b.rect.contains(x, y):
                        violations.append(
                            Violation(
                                kind="overlap",
                                message=(
                                    f"room {a.room_id} overlaps room {b.room_id}"
                                ),
                                x=x,
                                y=y,
                            )
                        )
                        break

    # connectivity
    comps = _components(grid)
    if not comps:
        violations.append(
            Violation(kind="connectivity", message="layout has no walkable cells", x=0, y=0)
        )
        return violations
    main = max(comps, key=len)
    for comp in comps:
        if comp is main:
            continue
        x, y = min(comp)  # deterministic representative cell
        violations.append(
            Violation(
                kind="connectivity",
                message=f"disconnected walkable region of {len(comp)} cell(s)",
                x=x,
                y=y,
            )
        )

    # reachability of every room center from the main component
    for room in rooms:
        cx, cy = room.center
        if not (0 <= cx < w and 0 <= cy < h):
            continue  # already reported as bounds
        if grid[cy][cx] not in _WALKABLE:
            violations.append(
                Violation(
                    kind="reachability",
                    message=f"room {room.room_id} center is not walkable",
                    x=cx,
                    y=cy,
                )
            )
        elif (cx, cy) not in main:
            violations.append(
                Violation(
                    kind="reachability",
                    message=f"room {room.room_id} is not reachable from room 0",
                    x=cx,
                    y=cy,
                )
            )

    return violations
