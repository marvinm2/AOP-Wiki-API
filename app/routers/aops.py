"""Adverse Outcome Pathways."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import date
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
    AopChemicalCollection,
    AopDetailEnvelope,
    AopGeneCollection,
    AopKerCollection,
    AopKeyEventCollection,
    AopList,
    AopStressorCollection,
    MethodCollection,
)
from app.routers.common import (
    clean,
    collection_body,
    first_text,
    group_fields,
    ids_of,
    joined_text,
    local_id,
    parse_param,
    require_entity,
    truthy,
    unique,
)
from app.sparql.terms import Int, Iri, IriList, Lit
from app.vocab import AOP_TYPE, NCBITAXON

router = APIRouter(prefix="/v1", tags=["AOPs"])

HYDRATE_CHUNK = 200
MAX_METHOD_AOPS = 50
EVIDENCE_FIELDS = (
    "essentiality",
    "overall_assessment",
    "evidence_summary",
    "quantitative_understanding",
    "potential_applications",
    "context",
)

AOP_ID_DOC = "AOP id, e.g. `37` or `AOP 37`"


def _aop_id(value: str) -> int:
    return parse_param("aop_id", lambda v: ids.parse_entity_id(ids.AOP, v), value)


def _summary(iri: str, fields: dict[str, list[str]]) -> dict[str, Any]:
    aop_id = ids.id_from_iri(ids.AOP, iri) or 0

    def first(name: str) -> str | None:
        values = fields.get(name)
        return clean(values[0]) if values else None

    return {
        "id": aop_id,
        "iri": iri,
        "label": f"AOP {aop_id}",
        "title": first("title"),
        "short_name": first("short_name"),
        "oecd_status": first("oecd_status"),
        "created": first("created"),
        "modified": first("modified"),
        "mie_ids": ids_of(ids.KEY_EVENT, fields.get("mie", [])),
        "ao_ids": ids_of(ids.KEY_EVENT, fields.get("ao", [])),
        "aopwiki_url": ids.entity_page(ids.AOP, aop_id),
    }


async def hydrate_aops(data: DataService, iris: list[str]) -> list[dict[str, Any]]:
    chunks = [iris[i : i + HYDRATE_CHUNK] for i in range(0, len(iris), HYDRATE_CHUNK)]
    results = await asyncio.gather(
        *(
            data.select("aops/hydrate", aops=IriList(tuple(Iri(iri) for iri in chunk)))
            for chunk in chunks
        )
    )
    fields: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for rows in results:
        for row in rows:
            fields[row["aop"]][row["field"]].append(row["value"])
    return [_summary(iri, fields[iri]) for iri in iris]


@router.get(
    "/aops",
    summary="List and filter Adverse Outcome Pathways",
    response_model=AopList,
    responses=CSV_RESPONSE,
)
async def list_aops(
    request: Request,
    page: PageParams = Depends(page_params),
    format: str | None = Depends(format_query),
    q: str | None = Query(None, description="Text in the title or short name (case-insensitive)"),
    status: str | None = Query(None, description="OECD status, e.g. `WPHA/WNT Endorsed`"),
    taxon: str | None = Query(None, description="NCBI taxon id, e.g. `10090`"),
    ke: str | None = Query(None, description="Contains this Key Event (any role), e.g. `18`"),
    mie: str | None = Query(None, description="Has this molecular initiating event"),
    ao: str | None = Query(None, description="Has this adverse outcome"),
    stressor: str | None = Query(None, description="Has this stressor id"),
    chemical: str | None = Query(None, description="Has a stressor with this CAS number"),
    modified_since: date | None = Query(None, description="Modified on or after this date"),
    data: DataService = Depends(get_data),
) -> Response:
    fmt = negotiate(request, format)

    def key_event(name: str, value: str | None) -> Iri | None:
        if value is None:
            return None
        number = parse_param(name, lambda v: ids.parse_entity_id(ids.KEY_EVENT, v), value)
        return ids.entity_iri(ids.KEY_EVENT, number)

    filters = {
        "q": parse_param("q", lambda v: Lit(ids.parse_search_term(v)), q) if q else None,
        "status": parse_param("status", Lit, status) if status else None,
        "taxon": ids.taxon_iri(parse_param("taxon", ids.parse_taxon, taxon)) if taxon else None,
        "ke": key_event("ke", ke),
        "mie": key_event("mie", mie),
        "ao": key_event("ao", ao),
        "stressor": ids.entity_iri(
            ids.STRESSOR,
            parse_param("stressor", lambda v: ids.parse_entity_id(ids.STRESSOR, v), stressor),
        )
        if stressor
        else None,
        "chemical": ids.cas_iri(parse_param("chemical", ids.parse_cas, chemical))
        if chemical
        else None,
        "modified_since": Lit(modified_since.isoformat()) if modified_since else None,
    }

    count_rows = await data.select("aops/count", **filters)
    total = int(count_rows[0]["total"]) if count_rows else 0
    items: list[dict[str, Any]] = []
    if page.offset < total:
        rows = await data.select(
            "aops/list", limit=Int(page.limit), offset=Int(page.offset), **filters
        )
        items = await hydrate_aops(data, [row["aop"] for row in rows])
    return respond(request, data, fmt=fmt, body=list_body(items, page, total, data, request))


def _key_event_role(is_mie: bool, is_ao: bool) -> str:
    return "mie" if is_mie else "ao" if is_ao else "ke"


def _detail(aop_id: int, rows: list[dict[str, str]], evidence: bool) -> dict[str, Any]:
    grouped = group_fields(rows)
    iri = ids.entity_iri(ids.AOP, aop_id).value
    summary = _summary(iri, {field: [r["value"] for r in rs] for field, rs in grouped.items()})
    mie_iris = {r["value"] for r in grouped.get("mie", [])}
    ao_iris = {r["value"] for r in grouped.get("ao", [])}

    taxa: dict[str, list[str]] = {}
    taxa_text: list[str] = []
    for row in grouped.get("taxon", []):
        value = row["value"]
        if value.startswith(NCBITAXON) and value[len(NCBITAXON) :].isdigit():
            names = taxa.setdefault(value, [])
            if (name := clean(row.get("title"))) and name not in names:
                names.append(name)
        elif text := clean(value):
            taxa_text.append(text)

    key_events: dict[str, dict[str, Any]] = {}
    for row in grouped.get("key_event", []):
        ke_iri = row["value"]
        ke_id = ids.id_from_iri(ids.KEY_EVENT, ke_iri)
        if ke_id is None or ke_iri in key_events:
            continue
        key_events[ke_iri] = {
            "id": ke_id,
            "title": clean(row.get("title")),
            "level": clean(row.get("level")),
            "role": _key_event_role(ke_iri in mie_iris, ke_iri in ao_iris),
        }

    titles = {ke["id"]: ke["title"] for ke in key_events.values()}
    kers: dict[int, dict[str, Any]] = {}
    for row in grouped.get("ker", []):
        ker_id = ids.id_from_iri(ids.KER, row["value"])
        up = ids.id_from_iri(ids.KEY_EVENT, row.get("up", ""))
        down = ids.id_from_iri(ids.KEY_EVENT, row.get("down", ""))
        if ker_id is None or up is None or down is None:
            continue
        kers[ker_id] = {
            "id": ker_id,
            "upstream": {"id": up, "title": titles.get(up)},
            "downstream": {"id": down, "title": titles.get(down)},
        }

    stressors: dict[int, dict[str, Any]] = {}
    for row in grouped.get("stressor", []):
        stressor_id = ids.id_from_iri(ids.STRESSOR, row["value"])
        if stressor_id is not None:
            stressors.setdefault(stressor_id, {"id": stressor_id, "title": clean(row.get("title"))})

    detail = {
        **summary,
        "abstract": first_text(grouped, "abstract"),
        "description": joined_text(grouped, "description"),
        "creator": first_text(grouped, "creator"),
        "license": first_text(grouped, "license"),
        "sexes": unique(clean(r["value"]) for r in grouped.get("sex", [])),
        "life_stages": unique(clean(r["value"]) for r in grouped.get("life_stage", [])),
        "taxa": [
            {"id": int(t[len(NCBITAXON) :]), "iri": t, "names": names}
            for t, names in sorted(taxa.items(), key=lambda item: int(item[0][len(NCBITAXON) :]))
        ],
        "taxa_text": unique(taxa_text),
        "key_events": sorted(key_events.values(), key=lambda ke: ke["id"]),
        "key_event_relationships": [kers[k] for k in sorted(kers)],
        "stressors": [stressors[s] for s in sorted(stressors)],
    }
    if evidence:
        detail["evidence"] = {name: joined_text(grouped, name) for name in EVIDENCE_FIELDS}
    return detail


@router.get(
    "/aops/{aop_id}",
    summary="One AOP with its Key Events, relationships, stressors and applicability",
    response_model=AopDetailEnvelope,
    responses=NOT_FOUND_RESPONSE,
)
async def get_aop(
    request: Request,
    aop_id: str = Path(description=AOP_ID_DOC),
    include: str | None = Query(
        None, pattern="^evidence$", description="`evidence` adds the long evidence texts"
    ),
    format: str | None = Depends(format_query),
    data: DataService = Depends(get_data),
) -> Response:
    fmt = negotiate(request, format)
    number = _aop_id(aop_id)
    evidence = include == "evidence"
    rows = await data.select(
        "aops/detail",
        flags=("evidence",) if evidence else (),
        aop=ids.entity_iri(ids.AOP, number),
    )
    if not any(r["field"] == "type" and r["value"] == AOP_TYPE.value for r in rows):
        raise ApiError(404, "Not Found", f"no AOP with id {number}")
    detail = _detail(number, rows, evidence)
    body = {"data": detail, "meta": {"total": 1, "dataset_version": data.token}}
    return respond(request, data, fmt=fmt, body=body, csv_items=[detail])


@router.get(
    "/aops/{aop_id}/key-events",
    summary="Key Events of an AOP, with their role in it",
    response_model=AopKeyEventCollection,
    responses=NOT_FOUND_RESPONSE,
)
async def aop_key_events(
    request: Request,
    aop_id: str = Path(description=AOP_ID_DOC),
    role: str | None = Query(None, pattern="^(mie|ke|ao)$", description="Only this role"),
    format: str | None = Depends(format_query),
    data: DataService = Depends(get_data),
) -> Response:
    fmt = negotiate(request, format)
    aop = await require_entity(data, ids.AOP, _aop_id(aop_id), AOP_TYPE)
    rows = await data.select("aops/key_events", aop=aop)
    items: dict[int, dict[str, Any]] = {}
    for row in rows:
        ke_id = ids.id_from_iri(ids.KEY_EVENT, row["ke"])
        if ke_id is None or ke_id in items:
            continue
        items[ke_id] = {
            "id": ke_id,
            "title": clean(row.get("title")),
            "level": clean(row.get("level")),
            "role": _key_event_role(truthy(row.get("mie")), truthy(row.get("ao"))),
        }
    result = [items[k] for k in sorted(items) if role is None or items[k]["role"] == role]
    return respond(request, data, fmt=fmt, body=collection_body(result, data))


@router.get(
    "/aops/{aop_id}/kers",
    summary="Key Event Relationships of an AOP",
    response_model=AopKerCollection,
    responses=NOT_FOUND_RESPONSE,
)
async def aop_kers(
    request: Request,
    aop_id: str = Path(description=AOP_ID_DOC),
    format: str | None = Depends(format_query),
    data: DataService = Depends(get_data),
) -> Response:
    fmt = negotiate(request, format)
    aop = await require_entity(data, ids.AOP, _aop_id(aop_id), AOP_TYPE)
    items: dict[int, dict[str, Any]] = {}
    for row in await data.select("aops/kers", aop=aop):
        ker_id = ids.id_from_iri(ids.KER, row["ker"])
        up = ids.id_from_iri(ids.KEY_EVENT, row["up"])
        down = ids.id_from_iri(ids.KEY_EVENT, row["down"])
        if ker_id is None or up is None or down is None:
            continue
        items[ker_id] = {
            "id": ker_id,
            "upstream": {"id": up, "title": clean(row.get("up_title"))},
            "downstream": {"id": down, "title": clean(row.get("down_title"))},
        }
    result = [items[k] for k in sorted(items)]
    return respond(request, data, fmt=fmt, body=collection_body(result, data))


@router.get(
    "/aops/{aop_id}/stressors",
    summary="Stressors associated with an AOP",
    response_model=AopStressorCollection,
    responses=NOT_FOUND_RESPONSE,
)
async def aop_stressors(
    request: Request,
    aop_id: str = Path(description=AOP_ID_DOC),
    format: str | None = Depends(format_query),
    data: DataService = Depends(get_data),
) -> Response:
    fmt = negotiate(request, format)
    aop = await require_entity(data, ids.AOP, _aop_id(aop_id), AOP_TYPE)
    items: dict[int, dict[str, Any]] = {}
    for row in await data.select("aops/stressors", aop=aop):
        stressor_id = ids.id_from_iri(ids.STRESSOR, row["stressor"])
        if stressor_id is None:
            continue
        item = items.setdefault(
            stressor_id,
            {"id": stressor_id, "title": clean(row.get("title")), "chemical_cas": []},
        )
        cas = local_id(row.get("chemical", ""), "cas")
        if cas and cas not in item["chemical_cas"]:
            item["chemical_cas"].append(cas)
    result = [items[k] for k in sorted(items)]
    return respond(request, data, fmt=fmt, body=collection_body(result, data))


@router.get(
    "/aops/{aop_id}/chemicals",
    summary="Chemicals of the stressors associated with an AOP",
    response_model=AopChemicalCollection,
    responses=NOT_FOUND_RESPONSE,
)
async def aop_chemicals(
    request: Request,
    aop_id: str = Path(description=AOP_ID_DOC),
    format: str | None = Depends(format_query),
    data: DataService = Depends(get_data),
) -> Response:
    fmt = negotiate(request, format)
    aop = await require_entity(data, ids.AOP, _aop_id(aop_id), AOP_TYPE)
    items: dict[tuple[str | None, int | None], dict[str, Any]] = {}
    for row in await data.select("aops/chemicals", aop=aop):
        cas = clean(row.get("cas")) or local_id(row["chemical"], "cas")
        stressor_id = ids.id_from_iri(ids.STRESSOR, row["stressor"])
        items.setdefault(
            (cas, stressor_id),
            {
                "cas": cas,
                "title": clean(row.get("title")),
                "inchikey": local_id(row.get("inchikey", ""), "inchikey"),
                "stressor_id": stressor_id,
            },
        )
    result = sorted(items.values(), key=lambda c: ((c["title"] or "").lower(), c["cas"] or ""))
    return respond(request, data, fmt=fmt, body=collection_body(result, data))


@router.get(
    "/aops/{aop_id}/genes",
    summary="Genes linked to the Key Events and KERs of an AOP",
    response_model=AopGeneCollection,
    responses=NOT_FOUND_RESPONSE,
)
async def aop_genes(
    request: Request,
    aop_id: str = Path(description=AOP_ID_DOC),
    method: str = Query(
        "any",
        pattern="^(any|regex|ner|both)$",
        description="Detection method: HGNC dictionary `regex`, BERN2 `ner`, `both`, or `any`",
    ),
    format: str | None = Depends(format_query),
    data: DataService = Depends(get_data),
) -> Response:
    fmt = negotiate(request, format)
    aop = await require_entity(data, ids.AOP, _aop_id(aop_id), AOP_TYPE)
    items: dict[tuple[str, int, int], dict[str, Any]] = {}
    for row in await data.select("aops/genes", aop=aop):
        hgnc = local_id(row["gene"], "hgnc")
        if hgnc is None or not hgnc.isdigit():
            continue
        entity = row["entity"]
        if (ke_id := ids.id_from_iri(ids.KEY_EVENT, entity)) is not None:
            kind, entity_id = "key_event", ke_id
        elif (ker_id := ids.id_from_iri(ids.KER, entity)) is not None:
            kind, entity_id = "ker", ker_id
        else:
            continue
        ner, regex = truthy(row.get("ner")), truthy(row.get("regex"))
        detected_by = "both" if ner and regex else "ner" if ner else "regex" if regex else "unknown"
        if method == "both" and detected_by != "both":
            continue
        if method in ("regex", "ner") and detected_by not in (method, "both"):
            continue
        items[(kind, entity_id, int(hgnc))] = {
            "hgnc_id": int(hgnc),
            "symbol": clean(row.get("symbol")),
            "entity_type": kind,
            "entity_id": entity_id,
            "detected_by": detected_by,
        }
    kind_order = {"key_event": 0, "ker": 1}
    result = [items[k] for k in sorted(items, key=lambda k: (k[2], kind_order[k[0]], k[1]))]
    return respond(request, data, fmt=fmt, body=collection_body(result, data))


@router.get(
    "/methods",
    summary="Measurement methods described for the Key Events of one or more AOPs",
    response_model=MethodCollection,
    responses=CSV_RESPONSE,
)
async def methods(
    request: Request,
    aop: str = Query(description=f"Comma-separated AOP ids (at most {MAX_METHOD_AOPS})"),
    format: str | None = Depends(format_query),
    data: DataService = Depends(get_data),
) -> Response:
    fmt = negotiate(request, format)
    parts = [part.strip() for part in aop.split(",") if part.strip()]
    if not parts or len(parts) > MAX_METHOD_AOPS:
        raise ApiError(
            400,
            "Invalid request parameters",
            errors=[{"param": "aop", "msg": f"give between 1 and {MAX_METHOD_AOPS} AOP ids"}],
        )
    numbers = unique(
        parse_param("aop", lambda v: ids.parse_entity_id(ids.AOP, v), p) for p in parts
    )
    iris = IriList(tuple(ids.entity_iri(ids.AOP, n) for n in numbers))
    items = []
    for row in await data.select("aops/methods", aops=iris):
        aop_id = ids.id_from_iri(ids.AOP, row["aop"])
        ke_id = ids.id_from_iri(ids.KEY_EVENT, row["ke"])
        if aop_id is None or ke_id is None or not (text := clean(row.get("method"))):
            continue
        items.append(
            {"aop_id": aop_id, "ke_id": ke_id, "ke_title": clean(row.get("title")), "method": text}
        )
    items.sort(key=lambda m: (m["aop_id"], m["ke_id"]))
    return respond(request, data, fmt=fmt, body=collection_body(items, data))
