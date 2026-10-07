"""HTTP API surface tests."""
from fastapi.testclient import TestClient

from app.api import create_app

client = TestClient(create_app())


def test_versions_endpoint():
    body = client.get("/versions").json()
    assert body["available"] == ["v1", "v2"]
    assert body["default"] == "v2"


def test_generate_is_idempotent_over_http():
    req = {"seed": 42, "version": "v1",
           "params": {"width": 48, "height": 48, "room_count": 6,
                      "min_room_size": 4, "max_room_size": 10,
                      "extra_corridors": 1}}
    a = client.post("/layouts/generate", json=req).json()
    b = client.post("/layouts/generate", json=req).json()
    assert a["content_hash"] == b["content_hash"]
    assert a["layout_id"] == b["layout_id"]
    assert a["status"] == "draft"


def test_regenerate_transition_audit_flow():
    a = client.post("/layouts/generate", json={"seed": 9, "version": "v1"}).json()
    lid = a["layout_id"]
    room0 = a["rooms"][0]["rect"]
    reg = client.post(f"/layouts/{lid}/regenerate", json={"region": {
        "x": room0["x"] - 2, "y": room0["y"] - 2,
        "w": room0["w"] + 4, "h": room0["h"] + 4}})
    assert reg.status_code == 200
    assert reg.json()["revision"] == a["revision"] + 1

    assert client.post(f"/layouts/{lid}/transition", json={
        "target": "locked", "actor": "alice", "role": "editor"
    }).status_code == 200
    # locked: regen now rejected with 409
    assert client.post(f"/layouts/{lid}/regenerate", json={"region": {
        "x": 0, "y": 0, "w": 5, "h": 5}}).status_code == 409
    # viewer may not publish
    assert client.post(f"/layouts/{lid}/transition", json={
        "target": "published", "actor": "mallory", "role": "viewer"
    }).status_code == 409
    assert client.post(f"/layouts/{lid}/transition", json={
        "target": "published", "actor": "root", "role": "admin"
    }).status_code == 200
    events = client.get(f"/layouts/{lid}/audit").json()["events"]
    assert [e["to_state"] for e in events] == ["locked", "published"]


def test_unknown_layout_404():
    assert client.get("/layouts/L-nope").status_code == 404


def test_unknown_version_404():
    resp = client.post("/layouts/generate",
                       json={"seed": 1, "version": "v99"})
    assert resp.status_code == 404


def test_recover_endpoint():
    assert client.post("/admin/recover").json() == {"recovered_jobs": []}
