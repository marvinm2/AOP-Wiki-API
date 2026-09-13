"""Liveness and readiness probes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.data import DataService
from app.deps import get_data
from app.errors import problem

router = APIRouter(tags=["Service"])

NO_STORE = {"Cache-Control": "no-store"}


@router.get("/health", summary="Liveness probe (does not contact the SPARQL endpoint)")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"}, headers=NO_STORE)


@router.get(
    "/health/ready",
    summary="Readiness probe: SPARQL endpoint reachable and dataset loaded",
    responses={503: {"description": "Endpoint unreachable, or the store is empty or reloading"}},
)
async def ready(request: Request, data: DataService = Depends(get_data)) -> JSONResponse:
    ok, detail = await data.readiness()
    if not ok:
        return problem(request, 503, "Not ready", detail, headers={"Retry-After": "30"})
    return JSONResponse(
        {"status": "ready", "dataset_version": data.token, "cached_queries": len(data.cache)},
        headers=NO_STORE,
    )
