"""FastAPI HTTP layer for the dungeon layout generator."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app import generators
from app.models import (GenerationParams, Layout, Rect, Role,
                        StateTransitionError, ValidationError)
from app.service import LayoutService
from app.store import LayoutStore


class GenerateRequest(BaseModel):
    seed: int
    params: GenerationParams = Field(default_factory=GenerationParams)
    version: str | None = None
    timeout_s: float | None = None


class RegenerateRequest(BaseModel):
    region: Rect
    timeout_s: float | None = None


class TransitionRequest(BaseModel):
    target: str
    actor: str
    role: Role


def _layout_response(layout: Layout, layout_id: str) -> dict:
    d = layout.canonical_dict()
    d.update({
        "layout_id": layout_id,
        "status": layout.status.value,
        "revision": layout.revision,
        "content_hash": layout.content_hash(),
    })
    return d


def create_app(db_path: str = ":memory:") -> FastAPI:
    store = LayoutStore(db_path)
    service = LayoutService(store)
    app = FastAPI(title="Dungeon Layout Generator")
    app.state.service = service

    # --- error mapping: failures must be explicit, never silent ----------
    @app.exception_handler(ValidationError)
    def _validation(_req: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={
            "error": "constraint_violation",
            "violations": [
                {"code": v.code, "message": v.message,
                 "locations": [list(p) for p in v.locations]}
                for v in exc.violations
            ],
        })

    @app.exception_handler(StateTransitionError)
    def _state(_req: Request, exc: StateTransitionError) -> JSONResponse:
        return JSONResponse(status_code=409,
                            content={"error": "illegal_state_transition",
                                     "message": str(exc)})

    @app.exception_handler(KeyError)
    def _notfound(_req: Request, exc: KeyError) -> JSONResponse:
        return JSONResponse(status_code=404,
                            content={"error": "not_found",
                                     "message": str(exc)})

    @app.exception_handler(TimeoutError)
    def _timeout(_req: Request, exc: TimeoutError) -> JSONResponse:
        return JSONResponse(status_code=504,
                            content={"error": "timeout", "message": str(exc)})

    @app.exception_handler(ValueError)
    def _badreq(_req: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400,
                            content={"error": "bad_request",
                                     "message": str(exc)})

    # --- routes ------------------------------------------------------------
    @app.get("/")
    def root() -> dict:
        return {"service": "dungeon-layout-generator", "status": "ok"}

    @app.get("/versions")
    def versions() -> dict:
        return {"available": generators.available_versions(),
                "default": generators.latest_version()}

    @app.post("/layouts/generate", status_code=200)
    def generate(req: GenerateRequest) -> dict:
        layout = service.generate(req.seed, req.params, req.version,
                                  req.timeout_s)
        lid = service.find_layout_id(req.seed, req.params, req.version)
        return _layout_response(layout, lid)

    @app.get("/layouts/{layout_id}")
    def get_layout(layout_id: str) -> dict:
        layout = service.get(layout_id)
        if layout is None:
            raise KeyError(layout_id)
        return _layout_response(layout, layout_id)

    @app.post("/layouts/{layout_id}/regenerate")
    def regenerate(layout_id: str, req: RegenerateRequest) -> dict:
        layout = service.regenerate_region(layout_id, req.region,
                                           req.timeout_s)
        return _layout_response(layout, layout_id)

    @app.post("/layouts/{layout_id}/transition")
    def transition(layout_id: str, req: TransitionRequest) -> dict:
        layout = service.transition(layout_id, req.target, req.actor,
                                    req.role)
        return _layout_response(layout, layout_id)

    @app.get("/layouts/{layout_id}/audit")
    def audit(layout_id: str) -> dict:
        return {"layout_id": layout_id, "events": service.audit_log(layout_id)}

    @app.post("/admin/recover")
    def recover() -> dict:
        return {"recovered_jobs": service.recover()}

    return app
