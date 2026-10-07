"""Local regeneration: untouched cells preserved, connectivity kept, pure."""
import pytest

from app.generator import get_generator
from app.models import GenerationParams, Layout, Rect
from app.regenerate import RegenerationError, regenerate_region
from app.validation import validate_layout


def make_layout(version="v2", seed="regen-seed") -> Layout:
    p = GenerationParams(width=48, height=32, room_count=8, algorithm_version=version)
    grid, rooms = get_generator(version)(seed, p)
    return Layout(layout_id="L1", seed=seed, params=p, grid=grid, rooms=rooms)


def region_around(layout: Layout, room_index: int = 0, w: int = 16, h: int = 12) -> Rect:
    """A region guaranteed to overlap walkable space (centered on a room)."""
    cx, cy = layout.rooms[room_index].center
    x = max(0, min(cx - w // 2, layout.params.width - w))
    y = max(0, min(cy - h // 2, layout.params.height - h))
    return Rect(x, y, w, h)


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_untouched_cells_byte_identical(version):
    layout = make_layout(version)
    region = region_around(layout)
    out = regenerate_region(layout, region, "sub-1")
    for y in range(layout.params.height):
        for x in range(layout.params.width):
            if not region.contains(x, y):
                assert out.grid[y][x] == layout.grid[y][x], (x, y)


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_result_stays_valid_and_connected(version):
    layout = make_layout(version)
    out = regenerate_region(layout, region_around(layout), "sub-1")
    assert validate_layout(out.grid, out.rooms) == []


def test_regeneration_is_deterministic():
    layout = make_layout()
    region = region_around(layout)
    a = regenerate_region(layout, region, "sub-1")
    b = regenerate_region(layout, region, "sub-1")
    assert a.grid == b.grid
    assert a.rooms == b.rooms
    assert a.fingerprint() == b.fingerprint()


def test_different_sub_seed_changes_only_region():
    layout = make_layout()
    region = region_around(layout)
    a = regenerate_region(layout, region, "sub-1")
    b = regenerate_region(layout, region, "sub-2")
    assert a.grid != b.grid  # different sub-seed -> different content
    for y in range(layout.params.height):
        for x in range(layout.params.width):
            if not region.contains(x, y):
                assert a.grid[y][x] == b.grid[y][x]


def test_rooms_outside_region_kept():
    layout = make_layout()
    region = region_around(layout)
    out = regenerate_region(layout, region, "sub-1")
    kept = [r for r in layout.rooms if not r.rect.intersects(region)]
    for r in kept:
        assert r in out.rooms


def test_revision_increments():
    layout = make_layout()
    out = regenerate_region(layout, region_around(layout), "sub-1")
    assert out.revision == layout.revision + 1


def test_empty_region_rejected():
    layout = make_layout()
    with pytest.raises(RegenerationError):
        regenerate_region(layout, Rect(200, 200, 4, 4), "sub-1")


def test_full_grid_region_regenerates_everything():
    layout = make_layout()
    region = Rect(0, 0, layout.params.width, layout.params.height)
    out = regenerate_region(layout, region, "sub-1")
    assert validate_layout(out.grid, out.rooms) == []


def test_island_region_fails_with_located_reason():
    """Regenerating a region that touches no walkable cell would create an
    unreachable island; the error must name a concrete location."""
    import re

    layout = make_layout()
    # find a region far from any walkable cell
    target = None
    for y in range(0, layout.params.height - 6):
        for x in range(0, layout.params.width - 6):
            cand = Rect(x, y, 6, 6)
            if all(
                layout.grid[yy][xx] == 0
                for yy in range(max(0, y - 1), min(layout.params.height, y + 7))
                for xx in range(max(0, x - 1), min(layout.params.width, x + 7))
            ):
                target = cand
                break
        if target:
            break
    if target is None:
        pytest.skip("no wall-only region found for this seed")
    with pytest.raises(RegenerationError) as exc:
        regenerate_region(layout, target, "sub-1")
    assert re.search(r"\(\d+, \d+\)", str(exc.value)), str(exc.value)
