"""End-to-end tests over the HTTP API."""
import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

BODY = {"seed": "api-seed", "width": 40, "height": 24, "room_count": 6}


def test_generate_is_idempotent_over_http():
    r1 = client.post("/api/layouts", json=BODY)
    r2 = client.post("/api/layouts", json=BODY)
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["layout_id"] == r2.json()["layout_id"]
    assert r1.json()["fingerprint"] == r2.json()["fingerprint"]


def test_versions_endpoint_and_pinning():
    versions = client.get("/api/versions").json()["available"]
    assert versions == ["v1", "v2"]
    fps = {}
    for v in versions:
        r = client.post("/api/layouts", json={**BODY, "algorithm_version": v})
        assert r.status_code == 201
        fps[v] = r.json()["fingerprint"]
    assert fps["v1"] != fps["v2"]


def test_unknown_version_rejected():
    r = client.post("/api/layouts", json={**BODY, "algorithm_version": "v9"})
    assert r.status_code == 422


def test_regenerate_and_transition_flow():
    lid = client.post("/api/layouts", json={**BODY, "seed": "flow"}).json()["layout_id"]
    # regenerate as non-editor -> 403
    r = client.post(
        f"/api/layouts/{lid}/regenerate",
        json={"x": 4, "y": 4, "w": 10, "h": 8, "sub_seed": "s"},
        headers={"x-role": "viewer"},
    )
    assert r.status_code == 403
    # lock as reviewer
    r = client.post(
        f"/api/layouts/{lid}/transition",
        json={"target": "locked"},
        headers={"x-role": "reviewer"},
    )
    assert r.status_code == 200
    # editing a locked layout -> 409
    r = client.post(
        f"/api/layouts/{lid}/regenerate",
        json={"x": 4, "y": 4, "w": 10, "h": 8, "sub_seed": "s"},
        headers={"x-role": "editor"},
    )
    assert r.status_code == 409
    # publish as publisher
    r = client.post(
        f"/api/layouts/{lid}/transition",
        json={"target": "published"},
        headers={"x-role": "publisher"},
    )
    assert r.status_code == 200
    # audit trail records everything
    actions = [e["action"] for e in client.get(f"/api/layouts/{lid}/audit").json()]
    assert actions == ["generate", "transition", "transition"]


def test_missing_layout_404():
    assert client.get("/api/layouts/nope").status_code == 404
