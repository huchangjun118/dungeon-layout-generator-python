"""Generator algorithm version "v2" (evolved rules).

Differences vs v1 (frozen at release):
- rooms keep a 2-tile margin (looser packing)
- rooms are chained nearest-neighbour instead of placement order
- corridors route vertical leg first

v1 layouts remain reproducible through the v1 generator forever; v2 only
applies to requests that explicitly ask for it (or to the service default
once the default is bumped).
"""
from __future__ import annotations

from app.generators.v1 import (MARGIN, _components, _l_corridor, _place_rooms,
                               _stitch, _walkable)
from app.models import Corridor, GenerationParams, Layout, Rect, Room
from app.rng import make_rng

V2_MARGIN = 2


class GeneratorV2:
    version = "v2"

    def _corridors_for(self, rooms: list[Room],
                       params: GenerationParams) -> list[Corridor]:
        corridors: list[Corridor] = []
        cid = 0
        # nearest-neighbour chain, deterministic tie-breaking
        remaining = sorted(rooms, key=lambda r: r.id)
        current = remaining.pop(0)
        while remaining:
            nxt = min(
                remaining,
                key=lambda r: (abs(r.rect.center()[0] - current.rect.center()[0])
                               + abs(r.rect.center()[1] - current.rect.center()[1]),
                               r.id),
            )
            remaining.remove(nxt)
            pts = _l_corridor(current.rect.center(), nxt.rect.center(),
                              horizontal_first=False)
            corridors.append(Corridor(id=cid, points=tuple(pts),
                                      connects=(current.id, nxt.id)))
            cid += 1
            current = nxt
        return corridors

    def generate(self, seed: int, params: GenerationParams) -> Layout:
        rng = make_rng("gen", self.version, seed, params.canonical_json())
        area = Rect(1, 1, params.width - 2, params.height - 2)
        rooms = _place_rooms(rng, params, params.room_count, area,
                             margin=V2_MARGIN)
        corridors = self._corridors_for(rooms, params)
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
        inner = Rect(region.x + V2_MARGIN, region.y + V2_MARGIN,
                     max(1, region.w - 2 * V2_MARGIN),
                     max(1, region.h - 2 * V2_MARGIN))
        new_rooms: list[Room] = []
        if removed_rooms:
            placed = _place_rooms(rng, params, len(removed_rooms), inner,
                                  avoid=kept_rooms, margin=V2_MARGIN)
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

register(GeneratorV2())
