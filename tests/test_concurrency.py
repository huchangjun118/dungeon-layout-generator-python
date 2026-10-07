"""Concurrency, timeout, cancellation and interruption recovery."""
import asyncio

import pytest

from app.models import GenerationParams
from app.service import (
    GenerationTimeoutError,
    LayoutService,
)

PARAMS = GenerationParams(width=40, height=24, room_count=6)


def test_concurrent_identical_requests_are_idempotent():
    async def run():
        svc = LayoutService()
        results = await asyncio.gather(
            *[svc.generate("k", PARAMS, actor=f"u{i}") for i in range(32)]
        )
        assert all(r is results[0] for r in results)
        # only one generate audit entry: work happened exactly once
        assert len([e for e in svc.audit_log(results[0].layout_id)
                    if e.action == "generate"]) == 1

    asyncio.run(run())


def test_cancellation_of_one_waiter_does_not_pollute_others():
    async def run():
        svc = LayoutService()
        started = asyncio.Event()

        orig = svc._generate_once

        async def slow_once(*args, **kwargs):
            started.set()
            await asyncio.sleep(0.05)
            return await orig(*args, **kwargs)

        svc._generate_once = slow_once  # type: ignore[method-assign]

        async def cancel_soon():
            t = asyncio.ensure_future(svc.generate("k", PARAMS, actor="impatient"))
            await started.wait()
            t.cancel()
            with pytest.raises(asyncio.CancelledError):
                await t

        cancelled, patient = await asyncio.gather(
            cancel_soon(), svc.generate("k", PARAMS, actor="patient")
        )
        assert patient.layout_id
        # the shared computation survived and was cached exactly once
        again = await svc.generate("k", PARAMS, actor="late")
        assert again is patient

    asyncio.run(run())


def test_timeout_retries_then_succeeds_with_identical_result():
    async def run():
        svc = LayoutService(max_retries=2)
        calls = {"n": 0}
        orig = svc._generate_once

        async def flaky(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] < 3:
                await asyncio.sleep(0.2)  # exceeds the timeout budget
            return await orig(*args, **kwargs)

        svc._generate_once = flaky  # type: ignore[method-assign]
        layout = await svc.generate("k", PARAMS, actor="u", timeout=0.05)
        assert calls["n"] == 3  # two timed-out attempts, then success

        # recovery result must equal an uninterrupted generation
        svc2 = LayoutService()
        reference = await svc2.generate("k", PARAMS, actor="u")
        assert layout.fingerprint() == reference.fingerprint()

    asyncio.run(run())


def test_exhausted_timeout_leaves_no_partial_state():
    async def run():
        svc = LayoutService(max_retries=1)

        async def stuck(*args, **kwargs):
            await asyncio.sleep(10)

        svc._generate_once = stuck  # type: ignore[method-assign]
        with pytest.raises(GenerationTimeoutError):
            await svc.generate("k", PARAMS, actor="u", timeout=0.02)

        from app.models import layout_key

        key = layout_key("k", PARAMS)
        assert svc.get(key) is None  # no half-finished layout
        assert svc.audit_log(key) == []  # no audit garbage

        # a later healthy attempt recovers cleanly
        svc2 = LayoutService()
        recovered = await svc2.generate("k", PARAMS, actor="u")
        assert recovered.fingerprint()

    asyncio.run(run())


def test_concurrent_different_seeds_isolated():
    async def run():
        svc = LayoutService()
        layouts = await asyncio.gather(
            *[svc.generate(f"seed-{i}", PARAMS, actor="u") for i in range(8)]
        )
        fps = {l.fingerprint() for l in layouts}
        assert len(fps) == len(layouts)  # no cross-contamination

    asyncio.run(run())
