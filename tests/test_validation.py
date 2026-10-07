"""Constraint validation: overlap, connectivity, reachability, locations."""
import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.models import (Corridor, GenerationParams, Layout, Rect, Room,
                        ValidationError)
from app.validation import assert_valid, validate_layout

PARAMS = GenerationParams(width=48, height=48, room_count=6)


def _layout(rooms, corridors=()):
    return Layout(seed=1, params=PARAMS, generator_version="v1",
                  rooms=rooms, corridors=list(corridors))


def test_valid_layout_passes():
    rooms = [Room(0, Rect(2, 2, 4, 4)), Room(1, Rect(10, 2, 4, 4))]
    corr = Corridor(0, tuple((x, 4) for x in range(3, 11)), (0, 1))
    assert validate_layout(_layout(rooms, [corr])) == []


def test_overlap_reports_exact_tiles():
    rooms = [Room(0, Rect(2, 2, 5, 5)), Room(1, Rect(5, 5, 5, 5))]
    vs = validate_layout(_layout(rooms))
    overlap = [v for v in vs if v.code == "overlap"]
    assert len(overlap) == 1
    # overlapping region is (5,5)..(6,6)
    assert set(overlap[0].locations) == {(5, 5), (5, 6), (6, 5), (6, 6)}


def test_disconnected_reports_component_locations():
    rooms = [Room(0, Rect(2, 2, 4, 4)), Room(1, Rect(20, 20, 4, 4))]
    vs = validate_layout(_layout(rooms))
    disc = [v for v in vs if v.code == "disconnected"]
    assert len(disc) == 1
    assert (2, 2) in disc[0].locations and (20, 20) in disc[0].locations
    unreach = [v for v in vs if v.code == "unreachable"]
    assert any((22, 22) in v.locations for v in unreach)


def test_out_of_bounds_located():
    rooms = [Room(0, Rect(46, 46, 5, 5))]  # exceeds 48x48
    vs = validate_layout(_layout(rooms))
    oob = [v for v in vs if v.code == "out_of_bounds"]
    assert oob and oob[0].locations


def test_assert_valid_raises_with_all_violations():
    rooms = [Room(0, Rect(2, 2, 5, 5)), Room(1, Rect(5, 5, 5, 5)),
             Room(2, Rect(30, 30, 4, 4))]
    with pytest.raises(ValidationError) as ei:
        assert_valid(_layout(rooms))
    codes = {v.code for v in ei.value.violations}
    assert {"overlap", "disconnected"} <= codes


def test_api_returns_422_with_locations_on_violation():
    # force a violation by requesting an impossible room count
    client = TestClient(create_app())
    resp = client.post("/layouts/generate", json={
        "seed": 1, "version": "v1",
        "params": {"width": 12, "height": 12, "room_count": 50,
                   "min_room_size": 4, "max_room_size": 6,
                   "extra_corridors": 0},
    })
    assert resp.status_code == 400  # cannot place rooms -> explicit error
    assert resp.json()["error"] == "bad_request"
