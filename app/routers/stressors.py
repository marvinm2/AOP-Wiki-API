"""Stressors."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import Response

from app import ids
from app.data import DataService
from app.deps import get_data
from app.errors import ApiError
from app.formats import PageParams, format_query, list_body, negotiate, page_params, respond
from app.models import CSV_RESPONSE, NOT_FOUND_RESPONSE, StressorDetailEnvelope, StressorList
from app.routers.common import (
    chunked,
    clean,
    group_fields,
    ids_of,
    joined_text,
    local_id,
    parse_param,
    unique,
)
from app.sparql.terms import Int, Iri, IriList, Lit
from app.vocab import STRESSOR_TYPE

router = APIRouter(prefix="/v1", tags=["Stressors"])

HYDRATE_CHUNK = 200


def _summary(iri: str, fields: dict[str, list[str]]) -> dict[str, Any]:
    stressor_id = ids.id_from_iri(ids.STRESSOR, iri) or 0

    def first(name: str) -> str | None:
        values = fields.get(name)
        return clean(values[0]) if values else None

    return {
        "id": stressor_id,
        "iri": iri,
        "label": f"Stressor {stressor_id}",
        "title": first("title"),
        "created": first("created"),
        "modified": first("modified"),
        "chemical_cas": sorted(unique(local_id(c, "cas") for c in fields.get("chemical", []))),
        "aop_ids": ids_of(ids.AOP, fields.get("aop", [])),
        "aopwiki_url": ids.entity_page(ids.STRESSOR, stressor_id),
    }


@router.get(
    "/stressors",
    summary="List and filter stressors",
    response_model=StressorList,
    responses=CSV_RESPONSE,
)
async def list_stressors(
    request: Request,
    q: str | None = Query(None, description="Text in the stressor name (case-insensitive)"),
    aop: str | None = Query(None, description="Associated with this AOP, e.g. `37`"),
    chemical: str | None = Query(None, description="Contains this chemical (CAS number)"),
    has_chemical: bool | None = Query(None, description="Only stressors with a chemical entity"),
    page: PageParams = Depends(page_params),
    format: str | None = Depends(format_query),
    data: DataService = Depends(get_data),
) -> Response:
    fmt = negotiate(request, format)
    filters = {
        "q": parse_param("q", lambda v: Lit(ids.parse_search_term(v)), q) if q else None,
        "aop": ids.entity_iri(
            ids.AOP, parse_param("aop", lambda v: ids.parse_entity_id(ids.AOP, v), aop)
        )
        if aop
        else None,
        "chemical": ids.cas_iri(parse_param("chemical", ids.parse_cas, chemical))
        if chemical
        else None,
    }
    flags = ("has_chemical",) if has_chemical else ()
    count_rows = await data.select("stressors/count", flags=flags, **filters)
    total = int(count_rows[0]["total"]) if count_rows else 0
    items: list[dict[str, Any]] = []
    if page.offset < total:
        rows = await data.select(
            "stressors/list", flags=flags, limit=Int(page.limit), offset=Int(page.offset), **filters
        )
        iris = [row["stressor"] for row in rows]
        results = await asyncio.gather(
            *(
                data.select("stressors/hydrate", stressors=IriList(tuple(Iri(i) for i in chunk)))
                for chunk in chunked(iris, HYDRATE_CHUNK)
            )
        )
        fields: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        for result in results:
            for row in result:
                fields[row["stressor"]][row["field"]].append(row["value"])
        items = [_summary(iri, fields[iri]) for iri in iris]
    return respond(request, data, fmt=fmt, body=list_body(items, page, total, data, request))


@router.get(
    "/stressors/{stressor_id}",
    summary="One stressor with its chemicals and AOPs",
    response_model=StressorDetailEnvelope,
    responses=NOT_FOUND_RESPONSE,
)
async def get_stressor(
    request: Request,
    stressor_id: str = Path(description="Stressor id, e.g. `11`"),
    format: str | None = Depends(format_query),
    data: DataService = Depends(get_data),
) -> Response:
    fmt = negotiate(request, format)
    number = parse_param("stressor_id", lambda v: ids.parse_entity_id(ids.STRESSOR, v), stressor_id)
    rows = await data.select("stressors/detail", stressor=ids.entity_iri(ids.STRESSOR, number))
    if not any(r["field"] == "type" and r["value"] == STRESSOR_TYPE.value for r in rows):
        raise ApiError(404, "Not Found", f"no stressor with id {number}")
    grouped = group_fields(rows)
    iri = ids.entity_iri(ids.STRESSOR, number).value
    summary = _summary(iri, {field: [r["value"] for r in rs] for field, rs in grouped.items()})

    chemicals: dict[str, dict[str, Any]] = {}
    for row in grouped.get("chemical", []):
        cas = clean(row.get("cas")) or local_id(row["value"], "cas")
        chemicals.setdefault(
            row["value"],
            {
                "cas": cas,
                "title": clean(row.get("title")),
                "inchikey": local_id(row.get("inchikey", ""), "inchikey"),
            },
        )
    aops: dict[int, dict[str, Any]] = {}
    for row in grouped.get("aop", []):
        if (aop_id := ids.id_from_iri(ids.AOP, row["value"])) is not None:
            aops.setdefault(aop_id, {"id": aop_id, "title": clean(row.get("title"))})

    detail = {
        **summary,
        "description": joined_text(grouped, "description"),
        "chemicals": sorted(chemicals.values(), key=lambda c: (c["title"] or "").lower()),
        "aops": [aops[k] for k in sorted(aops)],
    }
    body = {"data": detail, "meta": {"total": 1, "dataset_version": data.token}}
    return respond(request, data, fmt=fmt, body=body, csv_items=[detail])
