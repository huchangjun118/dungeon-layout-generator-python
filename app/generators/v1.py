"""Generator algorithm version "v1" (baseline rules).

Algorithm (frozen for reproducibility):
1. Rooms are placed by rejection sampling with a 1-tile margin so rooms
   never touch or overlap.
2. Rooms are chained in placement order with L-shaped corridors between
   room centers (horizontal leg first), plus ``extra_corridors`` random
   extra links.
3. All randomness derives from (version, seed, params) via app.rng, so the
   output is identical in any process at any time.

Regional regeneration: rooms/corridors intersecting the region are removed,
replacement rooms are placed fully inside the region from a deterministic
regen-RNG, and connectivity is repaired with deterministic corridor
stitching. Everything outside the region is preserved exactly.
"""
from __future__ import annotations

from app.models import Corridor, GenerationParams, Layout, Rect, Room
from app.rng import make_rng

MARGIN = 1  # minimum gap between rooms


def _place_rooms(rng, params: GenerationParams, count: int,
                 area: Rect, avoid: list[Room] | None = None,
                 margin: int = MARGIN) -> list[Room]:
    """Place ``count`` non-overlapping rooms inside ``area``."""
    avoid = avoid or []
    rooms: list[Room] = []
    attempts = 0
    max_attempts = count * 200 + 200
    next_id = 0
    while len(rooms) < count and attempts < max_attempts:
        attempts += 1
        w = rng.randint(params.min_room_size, params.max_room_size)
        h = rng.randint(params.min_room_size, params.max_room_size)
        if w > area.w or h > area.h:
            continue
        x = rng.randint(area.x, area.x2 - w + 1)
        y = rng.randint(area.y, area.y2 - h + 1)
        rect = Rect(x, y, w, h)
        grown = Rect(x - margin, y - margin, w + 2 * margin, h + 2 * margin)
        if any(grown.intersects(r.rect) for r in rooms) or \
           any(grown.intersects(r.rect) for r in avoid):
            continue
        rooms.append(Room(id=next_id, rect=rect))
        next_id += 1
    if len(rooms) < count:
        raise ValueError(
            f"cannot place {count} rooms in {area.w}x{area.h} area with "
            f"size range [{params.min_room_size},{params.max_room_size}]"
        )
    return rooms


def _l_corridor(a: tuple[int, int], b: tuple[int, int],
                horizontal_first: bool) -> list[tuple[int, int]]:
    """L-shaped path of grid tiles from a to b (inclusive)."""
    points: list[tuple[int, int]] = []
    x, y = a
    if horizontal_first:
        while x != b[0]:
            points.append((x, y))
            x += 1 if b[0] > x else -1
        while y != b[1]:
            points.append((x, y))
            y += 1 if b[1] > y else -1
    else:
        while y != b[1]:
            points.append((x, y))
            y += 1 if b[1] > y else -1
        while x != b[0]:
            points.append((x, y))
            x += 1 if b[0] > x else -1
    points.append(b)
    return points


def _walkable(rooms: list[Room], corridors: list[Corridor]) -> set[tuple[int, int]]:
    tiles: set[tuple[int, int]] = set()
    for r in rooms:
        for x in range(r.rect.x, r.rect.x2 + 1):
            for y in range(r.rect.y, r.rect.y2 + 1):
                tiles.add((x, y))
    for c in corridors:
        tiles.update(c.points)
    return tiles


def _components(walkable: set[tuple[int, int]]) -> list[set[tuple[int, int]]]:
    """Connected components (4-neighbourhood) in deterministic order."""
    remaining = set(walkable)
    comps: list[set[tuple[int, int]]] = []
    while remaining:
        seed_tile = min(remaining)
        comp: set[tuple[int, int]] = set()
        stack = [seed_tile]
        remaining.discard(seed_tile)
        while stack:
            cx, cy = stack.pop()
            comp.add((cx, cy))
            for nb in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                if nb in remaining:
                    remaining.discard(nb)
                    stack.append(nb)
        comps.append(comp)
    comps.sort(key=min)
    return comps


def _stitch(corridors: list[Corridor], walkable: set[tuple[int, int]],
            next_id: int) -> list[Corridor]:
    """Deterministically connect all components with L-corridors."""
    result = list(corridors)
    while True:
        comps = _components(walkable)
        if len(comps) <= 1:
            return result
        # find the closest tile pair between comp[0] and any other comp,
        # with fully deterministic tie-breaking
        best: tuple[int, tuple[int, int], tuple[int, int]] | None = None
        for other in comps[1:]:
            for pa in comps[0]:
                for pb in other:
                    d = abs(pa[0] - pb[0]) + abs(pa[1] - pb[1])
                    cand = (d, pa, pb)
                    if best is None or cand < best:
                        best = cand
        assert best is not None
        _, pa, pb = best
        pts = _l_corridor(pa, pb, horizontal_first=True)
        result.append(Corridor(id=next_id, points=tuple(pts),
                               connects=(-1, -1)))
        walkable.update(pts)
        next_id += 1


class GeneratorV1:
    version = "v1"

    def _corridors_for(self, rng, rooms: list[Room],
                       params: GenerationParams) -> list[Corridor]:
        corridors: list[Corridor] = []
        cid = 0
        # chain rooms in placement order
        for a, b in zip(rooms, rooms[1:]):
            pts = _l_corridor(a.rect.center(), b.rect.center(),
                              horizontal_first=True)
            corridors.append(Corridor(id=cid, points=tuple(pts),
                                      connects=(a.id, b.id)))
            cid += 1
        # extra random links
        for _ in range(params.extra_corridors):
            a = rng.choice(rooms)
            b = rng.choice(rooms)
            if a.id == b.id:
                continue
            pts = _l_corridor(a.rect.center(), b.rect.center(),
                              horizontal_first=True)
            corridors.append(Corridor(id=cid, points=tuple(pts),
                                      connects=(a.id, b.id)))
            cid += 1
        return corridors

    def generate(self, seed: int, params: GenerationParams) -> Layout:
        rng = make_rng("gen", self.version, seed, params.canonical_json())
        area = Rect(1, 1, params.width - 2, params.height - 2)
        rooms = _place_rooms(rng, params, params.room_count, area)
        corridors = self._corridors_for(rng, rooms, params)
        return Layout(seed=seed, params=params,
                      generator_version=self.version,
                      rooms=rooms, corridors=corridors)

    def regenerate_region(self, layout: Layout, region: Rect) -> Layout:
        params = layout.params
        kept_rooms = [r for r in layout.rooms if not r.rect.intersects(region)]
        removed_rooms = [r for r in layout.rooms if r.rect.intersects(region)]
        region_tiles = {(x, y)
                        for x in range(region.x, region.x2 + 1)
                        for y in range(region.y, region.y2 + 1)}
        kept_corridors = [
            c for c in layout.corridors
            if not (set(c.points) & region_tiles)
            and all(any(r.id == rid for r in kept_rooms) or rid == -1
                    for rid in c.connects)
        ]

        rng = make_rng("regen", self.version, layout.seed,
                       params.canonical_json(),
                       region.x, region.y, region.w, region.h)
        inner = Rect(region.x + MARGIN, region.y + MARGIN,
                     max(1, region.w - 2 * MARGIN),
                     max(1, region.h - 2 * MARGIN))
        new_rooms: list[Room] = []
        if removed_rooms:
            placed = _place_rooms(rng, params, len(removed_rooms), inner,
                                  avoid=kept_rooms)
            base_id = max((r.id for r in layout.rooms), default=-1) + 1
            new_rooms = [Room(id=base_id + i, rect=r.rect, kind=r.kind)
                         for i, r in enumerate(placed)]

        rooms = kept_rooms + new_rooms
        next_cid = max((c.id for c in layout.corridors), default=-1) + 1
        walkable = _walkable(rooms, kept_corridors)
        corridors = _stitch(kept_corridors, walkable, next_cid)

        return Layout(seed=layout.seed, params=params,
                      generator_version=self.version,
                      rooms=sorted(rooms, key=lambda r: r.id),
                      corridors=sorted(corridors, key=lambda c: c.id),
                      status=layout.status,
                      revision=layout.revision + 1)


from app.generators import register  # noqa: E402

register(GeneratorV1())
