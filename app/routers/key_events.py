"""Key Events."""

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
from app.models import (
    CSV_RESPONSE,
    NOT_FOUND_RESPONSE,
    KeyEventAopCollection,
    KeyEventChemicalCollection,
    KeyEventDetailEnvelope,
    KeyEventList,
    KeyEventStressorCollection,
    NeighbourCollection,
    RoleLinkCollection,
)
from app.routers.common import (
    chunked,
    clean,
    collection_body,
    detected_by,
    group_fields,
    ids_of,
    joined_text,
    local_id,
    ontology_term,
    parse_param,
    require_entity,
    split_taxa,
    truthy,
    unique,
)
from app.sparql.terms import Int, Iri, IriList, Lit, Term
from app.vocab import KEY_EVENT_TYPE

router = APIRouter(prefix="/v1", tags=["Key Events"])

LEVELS = ("Molecular", "Cellular", "Tissue", "Organ", "Individual", "Population")
HYDRATE_CHUNK = 200
MAX_EDGES = 500
KE_ID_DOC = "Key Event id, e.g. `18` or `KE 18`"


def _ke_id(value: str, name: str = "ke_id") -> int:
    return parse_param(name, lambda v: ids.parse_entity_id(ids.KEY_EVENT, v), value)


def _role(is_mie: bool, is_ao: bool) -> str:
    return "mie" if is_mie else "ao" if is_ao else "ke"


def _summary(iri: str, fields: dict[str, list[str]]) -> dict[str, Any]:
    ke_id = ids.id_from_iri(ids.KEY_EVENT, iri) or 0

    def first(name: str) -> str | None:
        values = fields.get(name)
        return clean(values[0]) if values else None

    mie_in = ids_of(ids.AOP, fields.get("mie_of", []))
    ao_in = ids_of(ids.AOP, fields.get("ao_of", []))
    return {
        "id": ke_id,
        "iri": iri,
        "label": f"KE {ke_id}",
        "title": first("title"),
        "short_name": first("short_name"),
        "level": first("level"),
        "aop_ids": ids_of(ids.AOP, fields.get("aop", [])),
        "mie_in_aop_ids": mie_in,
        "ao_in_aop_ids": ao_in,
        "is_mie": bool(mie_in),
        "is_ao": bool(ao_in),
        "aopwiki_url": ids.entity_page(ids.KEY_EVENT, ke_id),
    }


async def hydrate_key_events(data: DataService, iris: list[str]) -> list[dict[str, Any]]:
    results = await asyncio.gather(
        *(
            data.select("key_events/hydrate", kes=IriList(tuple(Iri(i) for i in chunk)))
            for chunk in chunked(iris, HYDRATE_CHUNK)
        )
    )
    fields: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for rows in results:
        for row in rows:
            fields[row["ke"]][row["field"]].append(row["value"])
    return [_summary(iri, fields[iri]) for iri in iris]


async def key_event_filters(
    q: str | None = Query(None, description="Text in the title or short name (case-insensitive)"),
    level: str | None = Query(
        None, description=f"Level of biological organisation: {', '.join(LEVELS)}"
    ),
    aop: str | None = Query(None, description="Occurs in this AOP, e.g. `37`"),
    taxon: str | None = Query(None, description="NCBI taxon id, e.g. `9606`"),
    organ: str | None = Query(None, description="Organ term, e.g. `UBERON:0002107`"),
    cell_type: str | None = Query(None, description="Cell type term, e.g. `CL:0000182`"),
    gene: str | None = Query(None, description="Linked gene: HGNC id or symbol, e.g. `AHR`"),
    data: DataService = Depends(get_data),
) -> dict[str, Term | None] | None:
    """Filter terms for the KE list queries; None when a gene symbol matches nothing."""
    filters: dict[str, Term | None] = {
        "q": parse_param("q", lambda v: Lit(ids.parse_search_term(v)), q) if q else None,
        "aop": ids.entity_iri(
            ids.AOP, parse_param("aop", lambda v: ids.parse_entity_id(ids.AOP, v), aop)
        )
        if aop
        else None,
        "taxon": ids.taxon_iri(parse_param("taxon", ids.parse_taxon, taxon)) if taxon else None,
        "organ": parse_param("organ", lambda v: ids.parse_obo_term("UBERON", v), organ)
        if organ
        else None,
        "cell_type": parse_param("cell_type", lambda v: ids.parse_obo_term("CL", v), cell_type)
        if cell_type
        else None,
        "level": None,
        "gene": None,
    }
    if level is not None:
        canonical = {lvl.lower(): lvl for lvl in LEVELS}.get(level.strip().lower())
        if canonical is None:
            raise ApiError(
                400,
                "Invalid request parameters",
                errors=[{"param": "level", "msg": f"must be one of {', '.join(LEVELS)}"}],
            )
        filters["level"] = Lit(canonical)
    if gene is not None:
        ref = parse_param("gene", ids.parse_gene, gene)
        if ref.hgnc_id is not None:
            filters["gene"] = ids.hgnc_iri(ref.hgnc_id)
        else:
            assert ref.symbol is not None
            rows = await data.select("genes/by_symbol", symbol=Lit(ref.symbol.lower()))
            if not rows:
                return None
            filters["gene"] = Iri(rows[0]["gene"])
    return filters


async def _list_key_events(
    request: Request,
    data: DataService,
    page: PageParams,
    fmt_param: str | None,
    filters: dict[str, Term | None] | None,
    role: str | None,
) -> Response:
    fmt = negotiate(request, fmt_param)
    items: list[dict[str, Any]] = []
    total = 0
    if filters is not None:
        flags = (f"role_{role}",) if role else ()
        count_rows = await data.select("key_events/count", flags=flags, **filters)
        total = int(count_rows[0]["total"]) if count_rows else 0
        if page.offset < total:
            rows = await data.select(
                "key_events/list",
                flags=flags,
                limit=Int(page.limit),
                offset=Int(page.offset),
                **filters,
            )
            items = await hydrate_key_events(data, [row["ke"] for row in rows])
    return respond(request, data, fmt=fmt, body=list_body(items, page, total, data, request))


@router.get(
    "/key-events",
    summary="List and filter Key Events",
    response_model=KeyEventList,
    responses=CSV_RESPONSE,
)
async def list_key_events(
    request: Request,
    role: str | None = Query(
        None,
        pattern="^(mie|ke|ao)$",
        description="Has this role in at least one AOP: `mie`, `ao`, or intermediate `ke`",
    ),
    filters: dict[str, Term | None] | None = Depends(key_event_filters),
    page: PageParams = Depends(page_params),
    format: str | None = Depends(format_query),
    data: DataService = Depends(get_data),
) -> Response:
    return await _list_key_events(request, data, page, format, filters, role)


@router.get(
    "/mies",
    summary="Key Events that are the molecular initiating event of at least one AOP",
    response_model=KeyEventList,
    responses=CSV_RESPONSE,
)
async def list_mies(
    request: Request,
    filters: dict[str, Term | None] | None = Depends(key_event_filters),
    page: PageParams = Depends(page_params),
    format: str | None = Depends(format_query),
    data: DataService = Depends(get_data),
) -> Response:
    return await _list_key_events(request, data, page, format, filters, "mie")


@router.get(
    "/aos",
    summary="Key Events that are the adverse outcome of at least one AOP",
    response_model=KeyEventList,
    responses=CSV_RESPONSE,
)
async def list_aos(
    request: Request,
    filters: dict[str, Term | None] | None = Depends(key_event_filters),
    page: PageParams = Depends(page_params),
    format: str | None = Depends(format_query),
    data: DataService = Depends(get_data),
) -> Response:
    return await _list_key_events(request, data, page, format, filters, "ao")


def _detail(ke_id: int, rows: list[dict[str, str]]) -> dict[str, Any]:
    grouped = group_fields(rows)
    iri = ids.entity_iri(ids.KEY_EVENT, ke_id).value

    aops: dict[int, dict[str, Any]] = {}
    for row in grouped.get("aop", []):
        aop_id = ids.id_from_iri(ids.AOP, row["value"])
        if aop_id is not None:
            aops.setdefault(
                aop_id,
                {
                    "id": aop_id,
                    "title": clean(row.get("title")),
                    "role": _role(truthy(row.get("is_mie")), truthy(row.get("is_ao"))),
                },
            )
    fields = {field: [r["value"] for r in rs] for field, rs in grouped.items()}
    fields["mie_of"] = [
        ids.entity_iri(ids.AOP, a["id"]).value for a in aops.values() if a["role"] == "mie"
    ]
    fields["ao_of"] = [
        ids.entity_iri(ids.AOP, a["id"]).value for a in aops.values() if a["role"] == "ao"
    ]
    summary = _summary(iri, fields)

    events: dict[str, dict[str, Any]] = {}
    for row in grouped.get("biological_event", []):
        event = events.setdefault(row["value"], {"process": None, "object": None, "action": None})
        event["process"] = event["process"] or ontology_term(
            row.get("process"), row.get("process_title")
        )
        event["object"] = event["object"] or ontology_term(
            row.get("object"), row.get("object_title")
        )
        event["action"] = event["action"] or clean(row.get("action"))

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

    def term(field: str) -> dict[str, Any] | None:
        found = grouped.get(field)
        return ontology_term(found[0]["value"], found[0].get("title")) if found else None

    taxa, taxa_text = split_taxa(grouped.get("taxon", []))
    return {
        **summary,
        "description": joined_text(grouped, "description"),
        "measurement_methods": joined_text(grouped, "method"),
        "domain_of_applicability": joined_text(grouped, "applicability"),
        "sexes": unique(clean(r["value"]) for r in grouped.get("sex", [])),
        "life_stages": unique(clean(r["value"]) for r in grouped.get("life_stage", [])),
        "taxa": taxa,
        "taxa_text": taxa_text,
        "organ": term("organ"),
        "cell_type": term("cell_type"),
        "biological_events": list(events.values()),
        "aops": [aops[k] for k in sorted(aops)],
        "genes": sorted(genes.values(), key=lambda g: (g["symbol"] or "", g["hgnc_id"])),
    }


@router.get(
    "/key-events/{ke_id}",
    summary="One Key Event with its context, biological events, AOPs and genes",
    response_model=KeyEventDetailEnvelope,
    responses=NOT_FOUND_RESPONSE,
)
async def get_key_event(
    request: Request,
    ke_id: str = Path(description=KE_ID_DOC),
    format: str | None = Depends(format_query),
    data: DataService = Depends(get_data),
) -> Response:
    fmt = negotiate(request, format)
    number = _ke_id(ke_id)
    rows = await data.select("key_events/detail", ke=ids.entity_iri(ids.KEY_EVENT, number))
    if not any(r["field"] == "type" and r["value"] == KEY_EVENT_TYPE.value for r in rows):
        raise ApiError(404, "Not Found", f"no key event with id {number}")
    detail = _detail(number, rows)
    body = {"data": detail, "meta": {"total": 1, "dataset_version": data.token}}
    return respond(request, data, fmt=fmt, body=body, csv_items=[detail])


@router.get(
    "/key-events/{ke_id}/aops",
    summary="AOPs that contain a Key Event, with its role in each",
    response_model=KeyEventAopCollection,
    responses=NOT_FOUND_RESPONSE,
)
async def key_event_aops(
    request: Request,
    ke_id: str = Path(description=KE_ID_DOC),
    role: str | None = Query(None, pattern="^(mie|ke|ao)$", description="Only this role"),
    format: str | None = Depends(format_query),
    data: DataService = Depends(get_data),
) -> Response:
    fmt = negotiate(request, format)
    ke = await require_entity(data, ids.KEY_EVENT, _ke_id(ke_id), KEY_EVENT_TYPE)
    items: dict[int, dict[str, Any]] = {}
    for row in await data.select("key_events/aops", ke=ke):
        aop_id = ids.id_from_iri(ids.AOP, row["aop"])
        if aop_id is not None:
            items.setdefault(
                aop_id,
                {
                    "id": aop_id,
                    "title": clean(row.get("title")),
                    "role": _role(truthy(row.get("is_mie")), truthy(row.get("is_ao"))),
                },
            )
    result = [items[k] for k in sorted(items) if role is None or items[k]["role"] == role]
    return respond(request, data, fmt=fmt, body=collection_body(result, data))


async def _walk(data: DataService, start: int, direction: str, depth: int) -> list[dict[str, Any]]:
    """Breadth-first expansion over KERs, one SPARQL query per hop (no property paths)."""
    start_iri = ids.entity_iri(ids.KEY_EVENT, start).value
    seen = {start_iri}
    frontier = [start_iri]
    edges: dict[int, dict[str, Any]] = {}
    for hop in range(1, depth + 1):
        if not frontier:
            break
        results = await asyncio.gather(
            *(
                data.select(f"key_events/{direction}", kes=IriList(tuple(Iri(i) for i in chunk)))
                for chunk in chunked(frontier, HYDRATE_CHUNK)
            )
        )
        next_frontier: list[str] = []
        for rows in results:
            for row in rows:
                ker_id = ids.id_from_iri(ids.KER, row["ker"])
                from_id = ids.id_from_iri(ids.KEY_EVENT, row["from"])
                to_id = ids.id_from_iri(ids.KEY_EVENT, row["to"])
                if ker_id is None or from_id is None or to_id is None:
                    continue
                edge = edges.setdefault(
                    ker_id,
                    {
                        "ker_id": ker_id,
                        "from_ke_id": from_id,
                        "ke_id": to_id,
                        "ke_title": clean(row.get("to_title")),
                        "depth": hop,
                        "aop_ids": [],
                    },
                )
                aop_id = ids.id_from_iri(ids.AOP, row.get("aop", ""))
                if aop_id is not None and aop_id not in edge["aop_ids"]:
                    edge["aop_ids"].append(aop_id)
                if row["to"] not in seen:
                    seen.add(row["to"])
                    next_frontier.append(row["to"])
        if len(edges) > MAX_EDGES:
            raise ApiError(
                400,
                "Result too large",
                f"more than {MAX_EDGES} relationships within depth {hop}; use a smaller depth",
            )
        frontier = next_frontier
    for edge in edges.values():
        edge["aop_ids"].sort()
    return sorted(edges.values(), key=lambda e: (e["depth"], e["ke_id"], e["ker_id"]))


def _neighbour_route(direction: str):
    async def handler(
        request: Request,
        ke_id: str = Path(description=KE_ID_DOC),
        depth: int = Query(1, ge=1, le=3, description="Number of KER hops to follow"),
        format: str | None = Depends(format_query),
        data: DataService = Depends(get_data),
    ) -> Response:
        fmt = negotiate(request, format)
        number = _ke_id(ke_id)
        await require_entity(data, ids.KEY_EVENT, number, KEY_EVENT_TYPE)
        edges = await _walk(data, number, direction, depth)
        return respond(request, data, fmt=fmt, body=collection_body(edges, data))

    return handler


router.add_api_route(
    "/key-events/{ke_id}/downstream",
    _neighbour_route("downstream"),
    methods=["GET"],
    summary="Key Events downstream of a Key Event, following KERs up to `depth` hops",
    response_model=NeighbourCollection,
    responses=NOT_FOUND_RESPONSE,
)
router.add_api_route(
    "/key-events/{ke_id}/upstream",
    _neighbour_route("upstream"),
    methods=["GET"],
    summary="Key Events upstream of a Key Event, following KERs up to `depth` hops",
    response_model=NeighbourCollection,
    responses=NOT_FOUND_RESPONSE,
)


async def _role_links(
    request: Request, data: DataService, ke_id: str, template: str, flag: str | None, fmt_param
) -> Response:
    fmt = negotiate(request, fmt_param)
    ke = await require_entity(data, ids.KEY_EVENT, _ke_id(ke_id), KEY_EVENT_TYPE)
    items: dict[tuple[int, int], dict[str, Any]] = {}
    for row in await data.select(template, flags=(flag,) if flag else (), ke=ke):
        aop_id = ids.id_from_iri(ids.AOP, row["aop"])
        target = ids.id_from_iri(ids.KEY_EVENT, row["target"])
        if aop_id is None or target is None:
            continue
        items.setdefault(
            (aop_id, target),
            {
                "aop_id": aop_id,
                "aop_title": clean(row.get("aop_title")),
                "ke_id": target,
                "ke_title": clean(row.get("target_title")),
            },
        )
    result = [items[k] for k in sorted(items)]
    return respond(request, data, fmt=fmt, body=collection_body(result, data))


@router.get(
    "/key-events/{ke_id}/adverse-outcomes",
    summary="Adverse outcomes of the AOPs this Key Event initiates (or occurs in)",
    response_model=RoleLinkCollection,
    responses=NOT_FOUND_RESPONSE,
)
async def key_event_adverse_outcomes(
    request: Request,
    ke_id: str = Path(description=KE_ID_DOC),
    as_: str = Query(
        "mie",
        alias="as",
        pattern="^(mie|any)$",
        description="`mie`: only AOPs where this KE is the MIE; `any`: every AOP containing it",
    ),
    format: str | None = Depends(format_query),
    data: DataService = Depends(get_data),
) -> Response:
    flag = "as_mie" if as_ == "mie" else None
    return await _role_links(request, data, ke_id, "key_events/adverse_outcomes", flag, format)


@router.get(
    "/key-events/{ke_id}/molecular-initiating-events",
    summary="Molecular initiating events of the AOPs this Key Event is the outcome of",
    response_model=RoleLinkCollection,
    responses=NOT_FOUND_RESPONSE,
)
async def key_event_mies(
    request: Request,
    ke_id: str = Path(description=KE_ID_DOC),
    as_: str = Query(
        "ao",
        alias="as",
        pattern="^(ao|any)$",
        description="`ao`: only AOPs where this KE is the AO; `any`: every AOP containing it",
    ),
    format: str | None = Depends(format_query),
    data: DataService = Depends(get_data),
) -> Response:
    flag = "as_ao" if as_ == "ao" else None
    return await _role_links(request, data, ke_id, "key_events/mies", flag, format)


@router.get(
    "/key-events/{ke_id}/stressors",
    summary="Stressors of the AOPs that contain a Key Event",
    response_model=KeyEventStressorCollection,
    responses=NOT_FOUND_RESPONSE,
)
async def key_event_stressors(
    request: Request,
    ke_id: str = Path(description=KE_ID_DOC),
    format: str | None = Depends(format_query),
    data: DataService = Depends(get_data),
) -> Response:
    fmt = negotiate(request, format)
    ke = await require_entity(data, ids.KEY_EVENT, _ke_id(ke_id), KEY_EVENT_TYPE)
    items: dict[int, dict[str, Any]] = {}
    for row in await data.select("key_events/stressors", ke=ke):
        stressor_id = ids.id_from_iri(ids.STRESSOR, row["stressor"])
        aop_id = ids.id_from_iri(ids.AOP, row["aop"])
        if stressor_id is None:
            continue
        item = items.setdefault(
            stressor_id, {"id": stressor_id, "title": clean(row.get("title")), "aop_ids": []}
        )
        if aop_id is not None and aop_id not in item["aop_ids"]:
            item["aop_ids"].append(aop_id)
    result = [items[k] | {"aop_ids": sorted(items[k]["aop_ids"])} for k in sorted(items)]
    return respond(request, data, fmt=fmt, body=collection_body(result, data))


@router.get(
    "/key-events/{ke_id}/chemicals",
    summary="Chemicals of the stressors of the AOPs that contain a Key Event",
    response_model=KeyEventChemicalCollection,
    responses=NOT_FOUND_RESPONSE,
)
async def key_event_chemicals(
    request: Request,
    ke_id: str = Path(description=KE_ID_DOC),
    format: str | None = Depends(format_query),
    data: DataService = Depends(get_data),
) -> Response:
    fmt = negotiate(request, format)
    ke = await require_entity(data, ids.KEY_EVENT, _ke_id(ke_id), KEY_EVENT_TYPE)
    items: dict[str, dict[str, Any]] = {}
    for row in await data.select("key_events/chemicals", ke=ke):
        cas = clean(row.get("cas")) or local_id(row["chemical"], "cas")
        key = cas or row["chemical"]
        item = items.setdefault(
            key, {"cas": cas, "title": clean(row.get("title")), "stressor_ids": [], "aop_ids": []}
        )
        if (sid := ids.id_from_iri(ids.STRESSOR, row["stressor"])) is not None:
            item["stressor_ids"] = sorted({*item["stressor_ids"], sid})
        if (aid := ids.id_from_iri(ids.AOP, row["aop"])) is not None:
            item["aop_ids"] = sorted({*item["aop_ids"], aid})
    result = sorted(items.values(), key=lambda c: ((c["title"] or "").lower(), c["cas"] or ""))
    return respond(request, data, fmt=fmt, body=collection_body(result, data))
