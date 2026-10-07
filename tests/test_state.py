"""Lifecycle state machine: legality, permissions, audit, determinism."""
import concurrent.futures as cf

import pytest

from app.models import GenerationParams, LayoutStatus, Role, StateTransitionError
from app.service import LayoutService
from app.store import LayoutStore

PARAMS = GenerationParams(width=48, height=48, room_count=6)


@pytest.fixture()
def svc_and_lid():
    svc = LayoutService(LayoutStore())
    svc.generate(1, PARAMS, version="v1")
    return svc, svc.find_layout_id(1, PARAMS, version="v1")


def test_happy_path_draft_locked_published(svc_and_lid):
    svc, lid = svc_and_lid
    assert svc.get(lid).status is LayoutStatus.DRAFT
    svc.transition(lid, "locked", "alice", Role.EDITOR)
    assert svc.get(lid).status is LayoutStatus.LOCKED
    svc.transition(lid, "published", "root", Role.ADMIN)
    assert svc.get(lid).status is LayoutStatus.PUBLISHED


def test_illegal_transitions_rejected(svc_and_lid):
    svc, lid = svc_and_lid
    with pytest.raises(StateTransitionError):
        svc.transition(lid, "published", "root", Role.ADMIN)  # skip locked
    svc.transition(lid, "locked", "alice", Role.EDITOR)
    with pytest.raises(StateTransitionError):
        svc.transition(lid, "locked", "alice", Role.EDITOR)  # no-op
    svc.transition(lid, "published", "root", Role.ADMIN)
    with pytest.raises(StateTransitionError):
        svc.transition(lid, "draft", "root", Role.ADMIN)  # terminal


def test_permission_enforced(svc_and_lid):
    svc, lid = svc_and_lid
    with pytest.raises(StateTransitionError):
        svc.transition(lid, "locked", "mallory", Role.VIEWER)
    svc.transition(lid, "locked", "alice", Role.EDITOR)
    with pytest.raises(StateTransitionError):
        svc.transition(lid, "published", "alice", Role.EDITOR)
    assert svc.get(lid).status is LayoutStatus.LOCKED  # unchanged


def test_every_transition_audited(svc_and_lid):
    svc, lid = svc_and_lid
    svc.transition(lid, "locked", "alice", Role.EDITOR)
    svc.transition(lid, "draft", "alice", Role.EDITOR)
    svc.transition(lid, "locked", "bob", Role.EDITOR)
    svc.transition(lid, "published", "root", Role.ADMIN)
    log = svc.audit_log(lid)
    assert [(e["from_state"], e["to_state"], e["actor"])
            for e in log] == [
        ("draft", "locked", "alice"),
        ("locked", "draft", "alice"),
        ("draft", "locked", "bob"),
        ("locked", "published", "root"),
    ]


def test_concurrent_transitions_deterministic(svc_and_lid):
    svc, lid = svc_and_lid
    # 8 threads race to lock; exactly one wins, final state is locked
    results = []
    errors = []

    def try_lock(i):
        try:
            svc.transition(lid, "locked", f"user{i}", Role.EDITOR)
            results.append(i)
        except StateTransitionError as e:
            errors.append(str(e))

    with cf.ThreadPoolExecutor(8) as ex:
        list(ex.map(try_lock, range(8)))
    assert len(results) == 1
    assert len(errors) == 7
    assert svc.get(lid).status is LayoutStatus.LOCKED
    assert len(svc.audit_log(lid)) == 1  # exactly one audited transition


def test_locked_layout_not_mutable(svc_and_lid):
    from app.models import Rect
    svc, lid = svc_and_lid
    svc.transition(lid, "locked", "alice", Role.EDITOR)
    with pytest.raises(StateTransitionError):
        svc.regenerate_region(lid, Rect(0, 0, 20, 20))
