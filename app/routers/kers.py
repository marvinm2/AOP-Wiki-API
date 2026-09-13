"""Key Event Relationships."""

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
from app.models import CSV_RESPONSE, NOT_FOUND_RESPONSE, KerDetailEnvelope, KerList
from app.routers.common import (
    chunked,
    clean,
    detected_by,
    group_fields,
    ids_of,
    joined_text,
    local_id,
    parse_param,
    split_taxa,
    unique,
)
from app.routers.genes import resolve_gene
from app.sparql.terms import Int, Iri, IriList, Term
from app.vocab import KER_TYPE

router = APIRouter(prefix="/v1", tags=["Key Event Relationships"])

HYDRATE_CHUNK = 200
EVIDENCE_FIELDS = (
    "biological_plausibility",
    "empirical_support",
    "uncertainties",
    "evidence_collection_strategy",
    "known_modulating_factors",
)


def _ref(rows: list[dict[str, str]]) -> dict[str, Any] | None:
    for row in rows:
        if (ke_id := ids.id_from_iri(ids.KEY_EVENT, row["value"])) is not None:
            return {"id": ke_id, "title": clean(row.get("title"))}
    return None


def _summary(iri: str, grouped: dict[str, list[dict[str, str]]]) -> dict[str, Any]:
    ker_id = ids.id_from_iri(ids.KER, iri) or 0

    def first(name: str) -> str | None:
        values = grouped.get(name)
        return clean(values[0]["value"]) if values else None

    return {
        "id": ker_id,
        "iri": iri,
        "label": f"KER {ker_id}",
        "upstream": _ref(grouped.get("up", [])),
        "downstream": _ref(grouped.get("down", [])),
        "aop_ids": ids_of(ids.AOP, (r["value"] for r in grouped.get("aop", []))),
        "created": first("created"),
        "modified": first("modified"),
        "aopwiki_url": ids.entity_page(ids.KER, ker_id),
    }


def _entity(name: str, kind: ids.EntityKind, value: str | None) -> Iri | None:
    if value is None:
        return None
    return ids.entity_iri(kind, parse_param(name, lambda v: ids.parse_entity_id(kind, v), value))


@router.get(
    "/kers",
    summary="List and filter Key Event Relationships",
    response_model=KerList,
    responses=CSV_RESPONSE,
)
async def list_kers(
    request: Request,
    aop: str | None = Query(None, description="Part of this AOP, e.g. `37`"),
    upstream: str | None = Query(None, description="Upstream Key Event id"),
    downstream: str | None = Query(None, description="Downstream Key Event id"),
    ke: str | None = Query(None, description="Key Event on either side"),
    gene: str | None = Query(None, description="Linked gene: HGNC id or symbol"),
    page: PageParams = Depends(page_params),
    format: str | None = Depends(format_query),
    data: DataService = Depends(get_data),
) -> Response:
    fmt = negotiate(request, format)
    filters: dict[str, Term | None] = {
        "aop": _entity("aop", ids.AOP, aop),
        "upstream": _entity("upstream", ids.KEY_EVENT, upstream),
        "downstream": _entity("downstream", ids.KEY_EVENT, downstream),
        "ke": _entity("ke", ids.KEY_EVENT, ke),
        "gene": None,
    }
    items: list[dict[str, Any]] = []
    total = 0
    gene_found = True
    if gene is not None:
        filters["gene"] = await resolve_gene(data, gene, "gene")
        gene_found = filters["gene"] is not None
    if gene_found:
        count_rows = await data.select("kers/count", **filters)
        total = int(count_rows[0]["total"]) if count_rows else 0
    if gene_found and page.offset < total:
        rows = await data.select(
            "kers/list", limit=Int(page.limit), offset=Int(page.offset), **filters
        )
        iris = [row["ker"] for row in rows]
        results = await asyncio.gather(
            *(
                data.select("kers/hydrate", kers=IriList(tuple(Iri(i) for i in chunk)))
                for chunk in chunked(iris, HYDRATE_CHUNK)
            )
        )
        grouped: dict[str, dict[str, list[dict[str, str]]]] = defaultdict(lambda: defaultdict(list))
        for result in results:
            for row in result:
                grouped[row["ker"]][row["field"]].append(row)
        items = [_summary(iri, grouped[iri]) for iri in iris]
    return respond(request, data, fmt=fmt, body=list_body(items, page, total, data, request))


@router.get(
    "/kers/{ker_id}",
    summary="One KER with its weight of evidence, quantitative understanding and applicability",
    response_model=KerDetailEnvelope,
    responses=NOT_FOUND_RESPONSE,
)
async def get_ker(
    request: Request,
    ker_id: str = Path(description="KER id, e.g. `1229` or `KER 1229`"),
    format: str | None = Depends(format_query),
    data: DataService = Depends(get_data),
) -> Response:
    fmt = negotiate(request, format)
    number = parse_param("ker_id", lambda v: ids.parse_entity_id(ids.KER, v), ker_id)
    iri = ids.entity_iri(ids.KER, number)
    rows = await data.select("kers/detail", ker=iri)
    if not any(r["field"] == "type" and r["value"] == KER_TYPE.value for r in rows):
        raise ApiError(404, "Not Found", f"no key event relationship with id {number}")
    grouped = group_fields(rows)
    summary = _summary(iri.value, grouped)

    genes: dict[int, dict[str, Any]] = {}
    for row in grouped.get("gene", []):
        hgnc = local_id(row["value"], "hgnc")
        if hgnc and hgnc.isdigit():
            genes.setdefault(
                int(hgnc),
                {
                    "hgnc_id": int(hgnc),
                    "symbol": clean(row.get("title")),
                    "detected_by": detected_by(row.get("ner"), row.get("regex")),
                },
            )
    aops: dict[int, dict[str, Any]] = {}
    for row in grouped.get("aop", []):
        if (aop_id := ids.id_from_iri(ids.AOP, row["value"])) is not None:
            aops.setdefault(aop_id, {"id": aop_id, "title": clean(row.get("title"))})
    taxa, taxa_text = split_taxa(grouped.get("taxon", []))

    detail = {
        **summary,
        "description": joined_text(grouped, "description"),
        "evidence": {name: joined_text(grouped, name) for name in EVIDENCE_FIELDS},
        "quantitative_understanding": {
            "description": joined_text(grouped, "quantitative_understanding"),
            "response_response_relationship": joined_text(
                grouped, "response_response_relationship"
            ),
            "time_scale": joined_text(grouped, "time_scale"),
            "feedback_loops": joined_text(grouped, "feedback_loops"),
        },
        "domain_of_applicability": joined_text(grouped, "applicability"),
        "sexes": unique(clean(r["value"]) for r in grouped.get("sex", [])),
        "life_stages": unique(clean(r["value"]) for r in grouped.get("life_stage", [])),
        "taxa": taxa,
        "taxa_text": taxa_text,
        "genes": sorted(genes.values(), key=lambda g: (g["symbol"] or "", g["hgnc_id"])),
        "aops": [aops[k] for k in sorted(aops)],
    }
    body = {"data": detail, "meta": {"total": 1, "dataset_version": data.token}}
    return respond(request, data, fmt=fmt, body=body, csv_items=[detail])
