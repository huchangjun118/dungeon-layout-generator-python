"""Layout constraint validation.

Checks performed:
- overlap: no two rooms may intersect
- bounds: rooms and corridor tiles must stay inside the grid
- connectivity: all walkable tiles form a single 4-connected component
- reachability: every room center is reachable from the first room center

Every violation carries concrete tile locations so failures can be
pinpointed instead of silently producing a broken layout.
"""
from __future__ import annotations

from app.generators.v1 import _components, _walkable
from app.models import (ConstraintViolation, Layout, ValidationError)


def validate_layout(layout: Layout) -> list[ConstraintViolation]:
    """Return all constraint violations (empty list means valid)."""
    violations: list[ConstraintViolation] = []
    w, h = layout.params.width, layout.params.height

    # --- bounds ---------------------------------------------------------
    for room in layout.rooms:
        r = room.rect
        if r.x < 0 or r.y < 0 or r.x2 >= w or r.y2 >= h:
            violations.append(ConstraintViolation(
                code="out_of_bounds",
                message=f"room {room.id} exceeds grid {w}x{h}",
                locations=((r.x, r.y), (r.x2, r.y2)),
            ))
    for c in layout.corridors:
        bad = tuple(p for p in c.points
                    if not (0 <= p[0] < w and 0 <= p[1] < h))
        if bad:
            violations.append(ConstraintViolation(
                code="out_of_bounds",
                message=f"corridor {c.id} leaves grid {w}x{h}",
                locations=bad,
            ))

    # --- overlap ----------------------------------------------------------
    rooms = layout.rooms
    for i in range(len(rooms)):
        for j in range(i + 1, len(rooms)):
            a, b = rooms[i].rect, rooms[j].rect
            if a.intersects(b):
                ox1, oy1 = max(a.x, b.x), max(a.y, b.y)
                ox2, oy2 = min(a.x2, b.x2), min(a.y2, b.y2)
                locs = tuple((x, y)
                             for x in range(ox1, ox2 + 1)
                             for y in range(oy1, oy2 + 1))
                violations.append(ConstraintViolation(
                    code="overlap",
                    message=f"rooms {rooms[i].id} and {rooms[j].id} overlap",
                    locations=locs,
                ))

    # --- connectivity / reachability --------------------------------------
    walkable = _walkable(layout.rooms, layout.corridors)
    if not walkable:
        violations.append(ConstraintViolation(
            code="disconnected", message="layout has no walkable tiles"))
        return violations
    comps = _components(walkable)
    if len(comps) > 1:
        # report the smallest tile of each component so the break is locatable
        locs = tuple(sorted(min(c) for c in comps))
        violations.append(ConstraintViolation(
            code="disconnected",
            message=f"layout splits into {len(comps)} disconnected components",
            locations=locs,
        ))
        # per-room reachability detail
        main = comps[0]
        for room in layout.rooms:
            ctr = room.rect.center()
            if ctr not in main:
                violations.append(ConstraintViolation(
                    code="unreachable",
                    message=f"room {room.id} center is not reachable from "
                            f"the main component",
                    locations=(ctr,),
                ))
    return violations


def assert_valid(layout: Layout) -> None:
    """Raise ValidationError if the layout violates any constraint."""
    violations = validate_layout(layout)
    if violations:
        raise ValidationError(violations)
