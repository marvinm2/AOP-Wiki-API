"""Genes linked to Key Events and KERs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import Response

from app import ids
from app.data import DataService
from app.deps import get_data
from app.errors import ApiError
from app.formats import PageParams, format_query, list_body, negotiate, page_params, respond
from app.models import CSV_RESPONSE, NOT_FOUND_RESPONSE, GeneDetailEnvelope, GeneList
from app.routers.common import (
    clean,
    detected_by,
    group_fields,
    local_id,
    parse_param,
    xrefs_by_namespace,
)
from app.sparql.terms import Int, Iri, Lit, Term

router = APIRouter(prefix="/v1", tags=["Genes"])

GENE_TYPE = "http://edamontology.org/data_2298"
METHOD_FLAGS = {"any": (), "ner": ("method_ner",), "regex": ("method_regex",)}
METHOD_FLAGS["both"] = ("method_ner", "method_regex")


def hgnc_url(hgnc_id: int) -> str:
    return f"https://www.genenames.org/data/gene-symbol-report/#!/hgnc_id/HGNC:{hgnc_id}"


async def resolve_gene(data: DataService, raw: str, param: str) -> Iri | None:
    """HGNC IRI for an id or symbol; None when the symbol is unknown."""
    ref = parse_param(param, ids.parse_gene, raw)
    if ref.hgnc_id is not None:
        return ids.hgnc_iri(ref.hgnc_id)
    assert ref.symbol is not None
    rows = await data.select("genes/by_symbol", symbol=Lit(ref.symbol.lower()))
    return Iri(rows[0]["gene"]) if rows else None


@router.get(
    "/genes",
    summary="Genes linked to Key Events or KERs, with link counts",
    response_model=GeneList,
    responses=CSV_RESPONSE,
)
async def list_genes(
    request: Request,
    q: str | None = Query(None, description="Gene symbol prefix (case-insensitive), e.g. `PPAR`"),
    aop: str | None = Query(None, description="Linked to the Key Events or KERs of this AOP"),
    ke: str | None = Query(None, description="Linked to this Key Event"),
    method: str = Query(
        "any",
        pattern="^(any|regex|ner|both)$",
        description="Detection method: HGNC dictionary `regex`, BERN2 `ner`, `both`, or `any`",
    ),
    page: PageParams = Depends(page_params),
    format: str | None = Depends(format_query),
    data: DataService = Depends(get_data),
) -> Response:
    fmt = negotiate(request, format)
    filters: dict[str, Term | None] = {
        "q": parse_param("q", lambda v: Lit(" ".join(str(v).split()).lower()), q) if q else None,
        "aop": ids.entity_iri(
            ids.AOP, parse_param("aop", lambda v: ids.parse_entity_id(ids.AOP, v), aop)
        )
        if aop
        else None,
        "ke": ids.entity_iri(
            ids.KEY_EVENT, parse_param("ke", lambda v: ids.parse_entity_id(ids.KEY_EVENT, v), ke)
        )
        if ke
        else None,
    }
    flags = METHOD_FLAGS[method]
    count_rows = await data.select("genes/count", flags=flags, **filters)
    total = int(count_rows[0]["total"]) if count_rows else 0
    items: list[dict[str, Any]] = []
    if page.offset < total:
        rows = await data.select(
            "genes/list", flags=flags, limit=Int(page.limit), offset=Int(page.offset), **filters
        )
        for row in rows:
            hgnc = local_id(row["gene"], "hgnc")
            if not hgnc or not hgnc.isdigit():
                continue
            items.append(
                {
                    "hgnc_id": int(hgnc),
                    "iri": row["gene"],
                    "symbol": clean(row.get("symbol")),
                    "ke_count": int(row.get("ke_count", "0")),
                    "ker_count": int(row.get("ker_count", "0")),
                    "hgnc_url": hgnc_url(int(hgnc)),
                }
            )
    return respond(request, data, fmt=fmt, body=list_body(items, page, total, data, request))


@router.get(
    "/genes/{gene}",
    summary="One gene with cross-references and its linked Key Events, KERs and AOPs",
    response_model=GeneDetailEnvelope,
    responses=NOT_FOUND_RESPONSE,
)
async def get_gene(
    request: Request,
    gene: str = Path(description="HGNC id (`348`, `HGNC:348`) or symbol (`AHR`)"),
    format: str | None = Depends(format_query),
    data: DataService = Depends(get_data),
) -> Response:
    fmt = negotiate(request, format)
    iri = await resolve_gene(data, gene, "gene")
    rows = await data.select("genes/detail", gene=iri) if iri is not None else []
    if not any(r["field"] == "type" and r["value"] == GENE_TYPE for r in rows):
        raise ApiError(404, "Not Found", f"no HGNC gene matching {gene!r}")
    assert iri is not None
    grouped = group_fields(rows)
    hgnc_id = int(local_id(iri.value, "hgnc") or 0)

    key_events: dict[int, dict[str, Any]] = {}
    for row in grouped.get("key_event", []):
        if (ke_id := ids.id_from_iri(ids.KEY_EVENT, row["value"])) is not None:
            key_events.setdefault(
                ke_id,
                {
                    "id": ke_id,
                    "title": clean(row.get("title")),
                    "detected_by": detected_by(row.get("ner"), row.get("regex")),
                },
            )
    kers: dict[int, dict[str, Any]] = {}
    for row in grouped.get("ker", []):
        if (ker_id := ids.id_from_iri(ids.KER, row["value"])) is not None:
            kers.setdefault(
                ker_id,
                {
                    "id": ker_id,
                    "upstream_id": ids.id_from_iri(ids.KEY_EVENT, row.get("up", "")),
                    "downstream_id": ids.id_from_iri(ids.KEY_EVENT, row.get("down", "")),
                    "detected_by": detected_by(row.get("ner"), row.get("regex")),
                },
            )
    aops: dict[int, dict[str, Any]] = {}
    for row in grouped.get("aop", []):
        if (aop_id := ids.id_from_iri(ids.AOP, row["value"])) is not None:
            aops.setdefault(aop_id, {"id": aop_id, "title": clean(row.get("title"))})

    symbols = grouped.get("symbol", [])
    detail = {
        "hgnc_id": hgnc_id,
        "iri": iri.value,
        "symbol": clean(symbols[0]["value"]) if symbols else None,
        "hgnc_url": hgnc_url(hgnc_id),
        "xrefs": xrefs_by_namespace(r["value"] for r in grouped.get("xref", [])),
        "key_events": [key_events[k] for k in sorted(key_events)],
        "kers": [kers[k] for k in sorted(kers)],
        "aops": [aops[k] for k in sorted(aops)],
    }
    body = {"data": detail, "meta": {"total": 1, "dataset_version": data.token}}
    return respond(request, data, fmt=fmt, body=body, csv_items=[detail])
