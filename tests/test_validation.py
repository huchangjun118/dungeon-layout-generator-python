"""Constraint validation: violations must carry a concrete location."""
from app.models import Rect, Room
from app.validation import validate_layout


def test_connectivity_violation_located():
    grid = [[0] * 6 for _ in range(6)]
    grid[1][1] = 1
    grid[4][4] = 1
    violations = validate_layout(grid, [])
    conn = [v for v in violations if v.kind == "connectivity"]
    assert conn, "expected a connectivity violation"
    v = conn[0]
    # the reported coordinate must actually be a walkable cell of a
    # disconnected component
    assert grid[v.y][v.x] == 1
    assert (v.x, v.y) == (4, 4)


def test_overlap_violation_located():
    rooms = [Room(0, Rect(1, 1, 3, 3)), Room(1, Rect(3, 3, 3, 3))]
    grid = [[1] * 8 for _ in range(8)]
    violations = validate_layout(grid, rooms)
    ov = [v for v in violations if v.kind == "overlap"]
    assert ov
    v = ov[0]
    assert rooms[0].rect.contains(v.x, v.y)
    assert rooms[1].rect.contains(v.x, v.y)


def test_reachability_violation_located():
    grid = [[0] * 6 for _ in range(6)]
    grid[1][1] = 1
    rooms = [Room(0, Rect(1, 1, 1, 1)), Room(1, Rect(4, 4, 1, 1))]
    violations = validate_layout(grid, rooms)
    reach = [v for v in violations if v.kind == "reachability"]
    assert reach
    assert (reach[0].x, reach[0].y) == rooms[1].center


def test_bounds_violation_located():
    grid = [[1] * 4 for _ in range(4)]
    rooms = [Room(0, Rect(2, 2, 5, 5))]
    violations = validate_layout(grid, rooms)
    assert any(v.kind == "bounds" for v in violations)


def test_valid_layout_has_no_violations():
    grid = [[0] * 6 for _ in range(6)]
    for y in range(1, 5):
        for x in range(1, 5):
            grid[y][x] = 1
    rooms = [Room(0, Rect(1, 1, 2, 2)), Room(1, Rect(3, 3, 2, 2))]
    assert validate_layout(grid, rooms) == []
