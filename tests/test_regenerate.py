"""Regional regeneration: seamless stitching, preservation, connectivity."""
import pytest

from app.generators import get_generator
from app.models import GenerationParams, Rect
from app.service import LayoutService
from app.store import LayoutStore
from app.validation import validate_layout

PARAMS = GenerationParams(width=48, height=48, room_count=6)


def _region_around(room_rect, pad=3):
    return Rect(room_rect.x - pad, room_rect.y - pad,
                room_rect.w + 2 * pad, room_rect.h + 2 * pad)


def test_untouched_rooms_preserved_exactly():
    gen = get_generator("v1")
    layout = gen.generate(11, PARAMS)
    region = _region_around(layout.rooms[0].rect)
    outside_before = {r.id: r for r in layout.rooms
                      if not r.rect.intersects(region)}
    assert outside_before, "test region must leave some rooms untouched"
    regen = gen.regenerate_region(layout, region)
    outside_after = {r.id: r for r in regen.rooms if r.id in outside_before}
    assert outside_before == outside_after


def test_regen_result_is_valid_and_connected():
    for version in ("v1", "v2"):
        gen = get_generator(version)
        layout = gen.generate(11, PARAMS)
        for room in layout.rooms[:3]:
            regen = gen.regenerate_region(layout, _region_around(room.rect))
            assert validate_layout(regen) == [], \
                f"{version}: regen around room {room.id} broke constraints"


def test_regen_is_deterministic():
    gen = get_generator("v1")
    layout = gen.generate(11, PARAMS)
    region = _region_around(layout.rooms[0].rect)
    a = gen.regenerate_region(layout, region)
    b = gen.regenerate_region(layout, region)
    assert a.content_hash() == b.content_hash()


def test_regen_different_region_differs():
    gen = get_generator("v1")
    layout = gen.generate(11, PARAMS)
    a = gen.regenerate_region(layout, _region_around(layout.rooms[0].rect))
    b = gen.regenerate_region(layout, _region_around(layout.rooms[1].rect))
    assert a.content_hash() != b.content_hash()


def test_regen_bumps_revision_via_service():
    svc = LayoutService(LayoutStore())
    layout = svc.generate(11, PARAMS, version="v1")
    lid = svc.find_layout_id(11, PARAMS, version="v1")
    r1 = svc.regenerate_region(lid, _region_around(layout.rooms[0].rect))
    assert r1.revision == layout.revision + 1
    r2 = svc.regenerate_region(lid, _region_around(r1.rooms[-1].rect))
    assert r2.revision == layout.revision + 2
    # persisted
    assert svc.get(lid).revision == layout.revision + 2


def test_regen_unknown_layout_raises():
    svc = LayoutService(LayoutStore())
    with pytest.raises(KeyError):
        svc.regenerate_region("L-nonexistent", Rect(0, 0, 10, 10))
