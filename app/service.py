"""LayoutService: idempotent generation, lifecycle state machine, auditing.

Concurrency model:
  * Generation is singleflight per (seed, params) key: concurrent identical
    requests share one in-flight task and all observe the same Layout.
  * Waiters are shielded: one caller cancelling or timing out never cancels
    the shared computation nor pollutes other waiters' results.
  * State is only ever mutated by a single atomic dict store after a fully
    validated result exists - a failed/timed-out attempt stores nothing, so
    no half-finished layout is ever observable.
  * Because generation is a pure function of (seed, params, version), a retry
    after any interruption converges to byte-identical output.
"""
from __future__ import annotations

import asyncio

from .generator import get_generator
from .models import (
    ALLOWED_TRANSITIONS,
    TRANSITION_ROLES,
    AuditEntry,
    GenerationParams,
    Layout,
    LayoutStatus,
    Rect,
    layout_key,
)
from .regenerate import regenerate_region
from .validation import validate_layout


class ServiceError(Exception):
    """Base class for service-level failures."""


class GenerationError(ServiceError):
    """Generation produced an invalid layout or failed permanently."""


class GenerationTimeoutError(ServiceError):
    """Generation did not finish within the budget (after retries)."""


class LayoutNotFoundError(ServiceError):
    pass


class InvalidTransitionError(ServiceError):
    pass


class PermissionDeniedError(ServiceError):
    pass


class LayoutService:
    def __init__(self, max_retries: int = 2) -> None:
        self._max_retries = max_retries
        self._layouts: dict[str, Layout] = {}
        self._audits: dict[str, list[AuditEntry]] = {}
        self._inflight: dict[str, asyncio.Task[Layout]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    # ------------------------------------------------------------------ utils
    def _lock_for(self, layout_id: str) -> asyncio.Lock:
        return self._locks.setdefault(layout_id, asyncio.Lock())

    def _record(self, entry: AuditEntry) -> None:
        self._audits.setdefault(entry.layout_id, []).append(entry)

    # -------------------------------------------------------------- generate
    async def generate(
        self,
        seed: str,
        params: GenerationParams,
        actor: str,
        timeout: float | None = None,
    ) -> Layout:
        key = layout_key(seed, params)
        existing = self._layouts.get(key)
        if existing is not None:
            return existing  # idempotent hit

        task = self._inflight.get(key)
        if task is None:
            task = asyncio.ensure_future(
                self._generate_with_retry(key, seed, params, actor, timeout)
            )
            self._inflight[key] = task
            task.add_done_callback(lambda _t, k=key: self._inflight.pop(k, None))
        # shield: this caller going away must not cancel the shared task.
        return await asyncio.shield(task)

    async def _generate_with_retry(
        self, key: str, seed: str, params: GenerationParams, actor: str, timeout: float | None
    ) -> Layout:
        attempts = self._max_retries + 1
        last_exc: Exception | None = None
        for attempt in range(attempts):
            try:
                return await asyncio.wait_for(
                    self._generate_once(key, seed, params, actor), timeout
                )
            except asyncio.TimeoutError as e:
                last_exc = e
                continue  # retry policy: nothing was stored, safe to recompute
        raise GenerationTimeoutError(
            f"generation timed out after {attempts} attempt(s)"
        ) from last_exc

    async def _generate_once(
        self, key: str, seed: str, params: GenerationParams, actor: str
    ) -> Layout:
        # Pure & deterministic: safe to run again after any interruption.
        gen = get_generator(params.algorithm_version)
        grid, rooms = gen(seed, params)
        violations = validate_layout(grid, rooms)
        if violations:
            v = violations[0]
            raise GenerationError(
                f"generated layout violates {v.kind} at ({v.x}, {v.y}): {v.message}"
            )
        layout = Layout(
            layout_id=key, seed=seed, params=params, grid=grid, rooms=rooms
        )
        # Atomic publish: only a fully validated layout ever becomes visible.
        self._layouts[key] = layout
        self._record(
            AuditEntry(key, layout.revision, actor, "generate", "", LayoutStatus.DRAFT.value,
                       detail=f"version={params.algorithm_version}")
        )
        return layout

    # ------------------------------------------------------------ regenerate
    async def regenerate(
        self, layout_id: str, region: Rect, sub_seed: str, actor: str, role: str
    ) -> Layout:
        if role != "editor":
            raise PermissionDeniedError("regenerating a layout requires role 'editor'")
        async with self._lock_for(layout_id):
            layout = self._layouts.get(layout_id)
            if layout is None:
                raise LayoutNotFoundError(layout_id)
            if layout.status is not LayoutStatus.DRAFT:
                raise InvalidTransitionError(
                    f"cannot regenerate a {layout.status.value} layout; "
                    "only drafts are editable"
                )
            new_layout = regenerate_region(layout, region, sub_seed)
            self._layouts[layout_id] = new_layout
            self._record(
                AuditEntry(layout_id, new_layout.revision, actor, "regenerate",
                           layout.status.value, layout.status.value,
                           detail=f"region={region} sub_seed={sub_seed}")
            )
            return new_layout

    # ------------------------------------------------------------ transitions
    async def transition(
        self, layout_id: str, target: LayoutStatus, actor: str, role: str
    ) -> Layout:
        async with self._lock_for(layout_id):
            layout = self._layouts.get(layout_id)
            if layout is None:
                raise LayoutNotFoundError(layout_id)
            required = TRANSITION_ROLES[target]
            if role != required:
                raise PermissionDeniedError(
                    f"transition to {target.value} requires role {required!r}"
                )
            if target not in ALLOWED_TRANSITIONS[layout.status]:
                raise InvalidTransitionError(
                    f"illegal transition {layout.status.value} -> {target.value}"
                )
            updated = Layout(
                layout_id=layout.layout_id,
                seed=layout.seed,
                params=layout.params,
                grid=layout.grid,
                rooms=layout.rooms,
                status=target,
                revision=layout.revision + 1,
            )
            self._layouts[layout_id] = updated
            self._record(
                AuditEntry(layout_id, updated.revision, actor, "transition",
                           layout.status.value, target.value)
            )
            return updated

    # ----------------------------------------------------------------- reads
    def get(self, layout_id: str) -> Layout | None:
        return self._layouts.get(layout_id)

    def audit_log(self, layout_id: str) -> list[AuditEntry]:
        return list(self._audits.get(layout_id, []))
