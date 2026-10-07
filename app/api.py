"""FastAPI routes exposing the layout service."""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from .generator import available_versions
from .models import (
    ALGORITHM_VERSIONS,
    DEFAULT_ALGORITHM_VERSION,
    GenerationParams,
    Layout,
    LayoutStatus,
    Rect,
)
from .service import (
    GenerationError,
    GenerationTimeoutError,
    InvalidTransitionError,
    LayoutNotFoundError,
    LayoutService,
    PermissionDeniedError,
)

router = APIRouter()
service = LayoutService()


# ------------------------------------------------------------------ schemas
class GenerateRequest(BaseModel):
    seed: str
    width: int = Field(ge=8, le=512)
    height: int = Field(ge=8, le=512)
    room_count: int = Field(ge=1, le=128)
    min_room_size: int = Field(default=3, ge=1)
    max_room_size: int = Field(default=8, ge=1)
    algorithm_version: str = DEFAULT_ALGORITHM_VERSION
    timeout: float | None = Field(default=None, gt=0)

    def to_params(self) -> GenerationParams:
        if self.algorithm_version not in ALGORITHM_VERSIONS:
            raise HTTPException(
                422, f"unknown algorithm_version {self.algorithm_version!r}"
            )
        if self.min_room_size > self.max_room_size:
            raise HTTPException(422, "min_room_size must be <= max_room_size")
        return GenerationParams(
            width=self.width,
            height=self.height,
            room_count=self.room_count,
            min_room_size=self.min_room_size,
            max_room_size=self.max_room_size,
            algorithm_version=self.algorithm_version,
        )


class RegenerateRequest(BaseModel):
    x: int
    y: int
    w: int = Field(ge=1)
    h: int = Field(ge=1)
    sub_seed: str


class TransitionRequest(BaseModel):
    target: LayoutStatus


class LayoutResponse(BaseModel):
    layout_id: str
    seed: str
    algorithm_version: str
    status: LayoutStatus
    revision: int
    fingerprint: str
    rooms: int
    grid: list[list[int]]


def _to_response(layout: Layout) -> LayoutResponse:
    return LayoutResponse(
        layout_id=layout.layout_id,
        seed=layout.seed,
        algorithm_version=layout.params.algorithm_version,
        status=layout.status,
        revision=layout.revision,
        fingerprint=layout.fingerprint(),
        rooms=len(layout.rooms),
        grid=layout.grid,
    )


# ------------------------------------------------------------------ routes
@router.post("/layouts", response_model=LayoutResponse, status_code=201)
async def generate_layout(
    req: GenerateRequest, x_actor: str = Header("anonymous")
) -> LayoutResponse:
    layout = await _map_errors_async(
        service.generate(req.seed, req.to_params(), actor=x_actor, timeout=req.timeout)
    )
    return _to_response(layout)


@router.get("/layouts/{layout_id}", response_model=LayoutResponse)
async def get_layout(layout_id: str) -> LayoutResponse:
    layout = service.get(layout_id)
    if layout is None:
        raise HTTPException(404, f"layout {layout_id!r} not found")
    return _to_response(layout)


@router.post("/layouts/{layout_id}/regenerate", response_model=LayoutResponse)
async def regenerate_layout(
    layout_id: str,
    req: RegenerateRequest,
    x_actor: str = Header("anonymous"),
    x_role: str = Header("editor"),
) -> LayoutResponse:
    layout = await _map_errors_async(
        service.regenerate(
            layout_id, Rect(req.x, req.y, req.w, req.h), req.sub_seed,
            actor=x_actor, role=x_role,
        )
    )
    return _to_response(layout)


@router.post("/layouts/{layout_id}/transition", response_model=LayoutResponse)
async def transition_layout(
    layout_id: str,
    req: TransitionRequest,
    x_actor: str = Header("anonymous"),
    x_role: str = Header("editor"),
) -> LayoutResponse:
    layout = await _map_errors_async(
        service.transition(layout_id, req.target, actor=x_actor, role=x_role)
    )
    return _to_response(layout)


@router.get("/layouts/{layout_id}/audit")
async def get_audit(layout_id: str) -> list[dict]:
    if service.get(layout_id) is None:
        raise HTTPException(404, f"layout {layout_id!r} not found")
    return [e.__dict__ for e in service.audit_log(layout_id)]


@router.get("/versions")
async def get_versions() -> dict:
    return {"available": available_versions(), "default": DEFAULT_ALGORITHM_VERSION}


async def _map_errors_async(coro):
    try:
        return await coro
    except LayoutNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except PermissionDeniedError as e:
        raise HTTPException(403, str(e)) from e
    except InvalidTransitionError as e:
        raise HTTPException(409, str(e)) from e
    except GenerationTimeoutError as e:
        raise HTTPException(504, str(e)) from e
    except GenerationError as e:
        raise HTTPException(500, str(e)) from e
