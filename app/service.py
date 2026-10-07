"""High-level layout service: generation, regeneration, lifecycle.

Guarantees:
- deterministic output per (seed, params, version): the idempotency key is
  a pure function of the inputs and the generator is pure, so any request
  order, cache state or process restart yields the identical layout.
- idempotent concurrency: the first caller claims the job row atomically;
  concurrent callers wait for the same row and read the same stored result.
- timeout/cancellation isolation: a waiting caller that times out simply
  stops waiting; a cancelled/failed owner releases the job row so nothing
  half-finished is ever visible and a later request regenerates cleanly.
- recovery: jobs orphaned by a crash are dropped by recover(); because
  generation is deterministic the regenerated result is bit-identical to
  an uninterrupted run.
"""
from __future__ import annotations

import hashlib
import time

from app import generators
from app.models import (GenerationParams, Layout, LayoutStatus, Rect, Role,
                        StateTransitionError, ValidationError)
from app.state import check_transition
from app.store import LayoutStore
from app.validation import assert_valid

POLL_INTERVAL_S = 0.01
MAX_ATTEMPTS = 3  # retry policy for failed/cancelled claims


def make_key(version: str, seed: int, params: GenerationParams) -> str:
    """Deterministic idempotency key for a generation request."""
    raw = f"{version}|{seed}|{params.canonical_json()}"
    return hashlib.sha256(raw.encode()).hexdigest()


def make_layout_id(key: str) -> str:
    return f"L-{key[:16]}"


class LayoutService:
    def __init__(self, store: LayoutStore, default_timeout_s: float = 30.0):
        self._store = store
        self._default_timeout_s = default_timeout_s

    # --- generation ------------------------------------------------------
    def generate(
        self,
        seed: int,
        params: GenerationParams,
        version: str | None = None,
        timeout_s: float | None = None,
    ) -> Layout:
        """Idempotently generate (or fetch) the layout for these inputs."""
        version = version or generators.latest_version()
        gen = generators.get_generator(version)
        key = make_key(version, seed, params)
        timeout = self._default_timeout_s if timeout_s is None else timeout_s

        attempts = 0
        while True:
            status = self._store.begin_job(key, version)
            if status == "done":
                found = self._store.find_by_key(key)
                assert found is not None, "done job without stored layout"
                return found[1]
            if status == "started":
                attempts += 1
                try:
                    layout = gen.generate(seed, params)
                    assert_valid(layout)  # never emit a broken layout
                    self._store.save_layout(make_layout_id(key), key, layout)
                    self._store.complete_job(key, make_layout_id(key))
                    return layout
                except BaseException:
                    # release the claim so waiters/retries see no debris
                    self._store.fail_job(key, "owner failed or cancelled")
                    if attempts >= MAX_ATTEMPTS:
                        raise
                    continue  # retry per policy
            # someone else owns the job: wait for them, bounded by timeout
            layout = self._wait_for(key, timeout)
            if layout is not None:
                return layout
            # owner died without completing (crash/cancel): try to claim
            # the job ourselves; deterministic regeneration is identical.
            attempts += 1
            if attempts >= MAX_ATTEMPTS:
                raise TimeoutError(
                    f"generation for key {key} did not finish within "
                    f"{attempts} attempts"
                )

    def _wait_for(self, key: str, timeout_s: float) -> Layout | None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            status = self._store.job_status(key)
            if status == "done":
                found = self._store.find_by_key(key)
                return found[1] if found else None
            if status is None:
                return None  # owner failed/cancelled; caller may retry
            time.sleep(POLL_INTERVAL_S)
        raise TimeoutError(f"timed out waiting for generation {key}")

    # --- regional regeneration --------------------------------------------
    def regenerate_region(
        self, layout_id: str, region: Rect, timeout_s: float | None = None
    ) -> Layout:
        layout = self._store.get_layout(layout_id)
        if layout is None:
            raise KeyError(f"unknown layout: {layout_id}")
        if layout.status is not LayoutStatus.DRAFT:
            raise StateTransitionError(
                f"cannot regenerate layout in status {layout.status.value}; "
                f"only drafts are mutable"
            )
        gen = generators.get_generator(layout.generator_version)
        new_layout = gen.regenerate_region(layout, region)
        assert_valid(new_layout)  # connectivity/seam enforced, not assumed
        self._store.save_layout(layout_id, make_key(
            new_layout.generator_version, new_layout.seed,
            new_layout.params), new_layout)
        return new_layout

    # --- lifecycle ---------------------------------------------------------
    def transition(
        self, layout_id: str, target: str, actor: str, role: Role
    ) -> Layout:
        target_status = LayoutStatus(target)
        current = self._store.current_status(layout_id)
        if current is None:
            raise KeyError(f"unknown layout: {layout_id}")
        check_transition(current, target_status, role)  # raises if illegal
        if not self._store.compare_and_swap_status(
            layout_id, current, target_status, actor, role.value
        ):
            # lost a concurrent race: report the deterministic outcome
            now = self._store.current_status(layout_id)
            raise StateTransitionError(
                f"concurrent transition: state is now {now}, "
                f"requested {current.value} -> {target_status.value} was rejected"
            )
        layout = self._store.get_layout(layout_id)
        assert layout is not None
        return layout

    # --- queries / recovery -------------------------------------------------
    def get(self, layout_id: str) -> Layout | None:
        return self._store.get_layout(layout_id)

    def find_layout_id(self, seed: int, params: GenerationParams,
                       version: str | None = None) -> str:
        version = version or generators.latest_version()
        return make_layout_id(make_key(version, seed, params))

    def audit_log(self, layout_id: str) -> list[dict]:
        return self._store.audit_log(layout_id)

    def recover(self) -> list[str]:
        """Recover jobs interrupted by a crash.

        Orphaned 'running' claims are dropped; the next generate() call for
        the same inputs regenerates the bit-identical layout. Returns the
        recovered job keys.
        """
        return self._store.recover_stale_jobs()
