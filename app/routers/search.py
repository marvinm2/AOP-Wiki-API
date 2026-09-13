"""Cross-entity name search."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.data import DataService
from app.deps import get_data
from app.errors import ApiError
from app.formats import format_query, negotiate, respond
from app.models import CSV_RESPONSE, Meta
from app.search_index import TYPES, SearchIndex

router = APIRouter(prefix="/v1", tags=["Search"])


class SearchHit(BaseModel):
    type: str = Field(description=", ".join(TYPES))
    id: int | str = Field(description="Numeric id, CAS number for chemicals, HGNC id for genes")
    title: str | None
    matched: str | None = Field(description="The name or synonym that matched")
    score: int = Field(description="100 exact, 90 id, 80 prefix, 60 word start, 40 substring")
    path: str = Field(description="API path of the resource")


class SearchResults(BaseModel):
    data: list[SearchHit]
    meta: Meta


def get_index(request: Request) -> SearchIndex:
    index = getattr(request.app.state, "search_index", None)
    if index is None:
        index = request.app.state.search_index = SearchIndex()
    return index


@router.get(
    "/search",
    summary="Find AOPs, Key Events, stressors, chemicals and genes by name, synonym or id",
    response_model=SearchResults,
    responses=CSV_RESPONSE,
)
async def search(
    request: Request,
    q: str = Query(min_length=1, max_length=200, description="Name, synonym or identifier"),
    types: str | None = Query(None, description=f"Comma-separated subset of: {', '.join(TYPES)}"),
    limit: int = Query(20, ge=1, le=100),
    format: str | None = Depends(format_query),
    data: DataService = Depends(get_data),
    index: SearchIndex = Depends(get_index),
) -> Response:
    fmt = negotiate(request, format)
    needle = " ".join(q.split())
    if len(needle) < 2 and not needle.isdigit():
        raise ApiError(
            400,
            "Invalid request parameters",
            errors=[{"param": "q", "msg": "use at least 2 characters"}],
        )
    wanted = set(TYPES)
    if types:
        wanted = {t.strip() for t in types.split(",") if t.strip()}
        if unknown := wanted - set(TYPES):
            raise ApiError(
                400,
                "Invalid request parameters",
                errors=[{"param": "types", "msg": f"unknown types {sorted(unknown)}"}],
            )
    await index.ensure(data)
    hits, total = index.search(needle, wanted, limit)
    prefix = request.scope.get("root_path", "").rstrip("/")
    for hit in hits:
        hit["path"] = prefix + hit["path"]
    body = {
        "data": hits,
        "meta": {"total": total, "limit": limit, "dataset_version": data.token},
    }
    return respond(request, data, fmt=fmt, body=body)
