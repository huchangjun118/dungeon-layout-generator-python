"""Lifecycle: legal transitions, role checks, deterministic concurrency, audit."""
import asyncio

import pytest

from app.models import GenerationParams, LayoutStatus, Rect
from app.service import (
    InvalidTransitionError,
    LayoutNotFoundError,
    LayoutService,
    PermissionDeniedError,
)

PARAMS = GenerationParams(width=40, height=24, room_count=6)


def make() -> tuple[LayoutService, str]:
    svc = LayoutService()
    layout = asyncio.run(svc.generate("k", PARAMS, actor="editor-1"))
    return svc, layout.layout_id


def test_happy_path_draft_locked_published():
    svc, lid = make()
    lay = asyncio.run(svc.transition(lid, LayoutStatus.LOCKED, "rev", "reviewer"))
    assert lay.status is LayoutStatus.LOCKED
    lay = asyncio.run(svc.transition(lid, LayoutStatus.PUBLISHED, "pub", "publisher"))
    assert lay.status is LayoutStatus.PUBLISHED


def test_illegal_transitions_rejected():
    svc, lid = make()
    with pytest.raises(InvalidTransitionError):
        asyncio.run(svc.transition(lid, LayoutStatus.PUBLISHED, "pub", "publisher"))
    asyncio.run(svc.transition(lid, LayoutStatus.LOCKED, "rev", "reviewer"))
    asyncio.run(svc.transition(lid, LayoutStatus.PUBLISHED, "pub", "publisher"))
    with pytest.raises(InvalidTransitionError):  # published is terminal
        asyncio.run(svc.transition(lid, LayoutStatus.DRAFT, "rev", "reviewer"))


def test_unlock_returns_to_draft():
    svc, lid = make()
    asyncio.run(svc.transition(lid, LayoutStatus.LOCKED, "rev", "reviewer"))
    lay = asyncio.run(svc.transition(lid, LayoutStatus.DRAFT, "rev", "reviewer"))
    assert lay.status is LayoutStatus.DRAFT


def test_role_checks_enforced():
    svc, lid = make()
    with pytest.raises(PermissionDeniedError):
        asyncio.run(svc.transition(lid, LayoutStatus.LOCKED, "e", "editor"))
    with pytest.raises(PermissionDeniedError):
        asyncio.run(svc.transition(lid, LayoutStatus.LOCKED, "p", "publisher"))
    asyncio.run(svc.transition(lid, LayoutStatus.LOCKED, "r", "reviewer"))
    with pytest.raises(PermissionDeniedError):
        asyncio.run(svc.transition(lid, LayoutStatus.PUBLISHED, "r", "reviewer"))


def test_regenerate_requires_draft_and_editor():
    svc, lid = make()
    region = Rect(0, 0, 8, 8)
    with pytest.raises(PermissionDeniedError):
        asyncio.run(svc.regenerate(lid, region, "s", "a", role="reviewer"))
    asyncio.run(svc.transition(lid, LayoutStatus.LOCKED, "r", "reviewer"))
    with pytest.raises(InvalidTransitionError):
        asyncio.run(svc.regenerate(lid, region, "s", "a", role="editor"))


def test_concurrent_transitions_are_deterministic():
    async def run():
        svc = LayoutService()
        layout = await svc.generate("k", PARAMS, actor="e")
        lid = layout.layout_id
        await svc.transition(lid, LayoutStatus.LOCKED, "r", "reviewer")
        # publish vs unlock race: exactly one must win
        results = await asyncio.gather(
            svc.transition(lid, LayoutStatus.PUBLISHED, "p", "publisher"),
            svc.transition(lid, LayoutStatus.DRAFT, "r", "reviewer"),
            return_exceptions=True,
        )
        wins = [r for r in results if not isinstance(r, Exception)]
        losses = [r for r in results if isinstance(r, InvalidTransitionError)]
        assert len(wins) == 1 and len(losses) == 1
        final = svc.get(lid)
        assert final.status == wins[0].status
        return final.status

    # the race is serialized by the per-layout lock; every observation is
    # one of the two legal outcomes, never a torn state
    outcomes = {asyncio.run(run()) for _ in range(5)}
    assert outcomes <= {LayoutStatus.PUBLISHED, LayoutStatus.DRAFT}


def test_audit_trail_is_complete_and_ordered():
    svc, lid = make()
    asyncio.run(svc.transition(lid, LayoutStatus.LOCKED, "rev", "reviewer"))
    asyncio.run(svc.transition(lid, LayoutStatus.PUBLISHED, "pub", "publisher"))
    log = svc.audit_log(lid)
    assert [e.action for e in log] == ["generate", "transition", "transition"]
    assert [e.to_status for e in log] == ["draft", "locked", "published"]
    assert [e.revision for e in log] == sorted(e.revision for e in log)
    assert log[1].actor == "rev" and log[2].actor == "pub"


def test_missing_layout_rejected():
    svc = LayoutService()
    with pytest.raises(LayoutNotFoundError):
        asyncio.run(svc.transition("nope", LayoutStatus.LOCKED, "r", "reviewer"))
