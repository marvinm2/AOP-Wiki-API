"""Chemicals (stressor chemical entities, identified by CAS number)."""

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
    ChemicalAopCollection,
    ChemicalDetailEnvelope,
    ChemicalKeyEventCollection,
    ChemicalList,
    PathwayCollection,
)
from app.routers.common import (
    chunked,
    clean,
    collection_body,
    group_fields,
    ids_of,
    local_id,
    parse_param,
    truthy,
    unique,
    xrefs_by_namespace,
)
from app.sparql.terms import Int, Iri, IriList, Lit, Term
from app.vocab import CHEMICAL_TYPE

router = APIRouter(prefix="/v1", tags=["Chemicals"])

HYDRATE_CHUNK = 200
CAS_DOC = "CAS registry number, e.g. `83-79-4`"
XREF_PARAMS = ("chebi", *ids.XREFS)


def _cas(value: str) -> str:
    return parse_param("cas", ids.parse_cas, value)


def _summary(iri: str, fields: dict[str, list[str]]) -> dict[str, Any]:
    def first(name: str) -> str | None:
        values = fields.get(name)
        return clean(values[0]) if values else None

    return {
        "cas": first("cas") or local_id(iri, "cas"),
        "iri": iri,
        "title": first("title"),
        "inchikey": local_id(fields.get("inchikey", [""])[0], "inchikey"),
        "comptox_id": local_id(fields.get("comptox", [""])[0], "comptox"),
        "stressor_ids": ids_of(ids.STRESSOR, fields.get("stressor", [])),
    }


def _xref_filter(request: Request) -> tuple[str, IriList] | None:
    given = [
        (name, request.query_params[name]) for name in XREF_PARAMS if name in request.query_params
    ]
    if not given:
        return None
    if len(given) > 1:
        raise ApiError(
            400,
            "Invalid request parameters",
            errors=[{"param": given[1][0], "msg": "use only one external identifier filter"}],
        )
    name, value = given[0]
    if name == "chebi":
        chebi = parse_param(name, ids.parse_chebi, value)
        # AOPWikiRDF moved to the resolvable `chebi/CHEBI:<n>` form; match the older
        # bare `chebi/<n>` form too until every loaded graph uses the new one.
        return name, IriList(
            (
                Iri(f"{ids.IDENTIFIERS_ORG}chebi/CHEBI:{chebi}"),
                Iri(f"{ids.IDENTIFIERS_ORG}chebi/{chebi}"),
            )
        )
    return name, IriList(tuple(parse_param(name, lambda v: ids.parse_xref(name, v), value)))


@router.get(
    "/chemicals",
    summary="List chemicals, search by name or synonym, or look up by an external identifier",
    response_model=ChemicalList,
    responses=CSV_RESPONSE,
)
async def list_chemicals(
    request: Request,
    q: str | None = Query(None, description="Text in the name or a synonym (case-insensitive)"),
    aop: str | None = Query(None, description="Chemicals of the stressors of this AOP"),
    stressor: str | None = Query(None, description="Chemicals of this stressor"),
    inchikey: str | None = Query(None, description="InChIKey"),
    chebi: str | None = Query(None, description="ChEBI id, e.g. `CHEBI:28201`"),
    pubchem: str | None = Query(None, description="PubChem CID"),
    chemspider: str | None = Query(None, description="ChemSpider id"),
    wikidata: str | None = Query(None, description="Wikidata item, e.g. `Q412388`"),
    chembl: str | None = Query(None, description="ChEMBL compound id"),
    drugbank: str | None = Query(None, description="DrugBank id"),
    kegg: str | None = Query(None, description="KEGG compound id"),
    hmdb: str | None = Query(None, description="HMDB id (padded or unpadded)"),
    lipidmaps: str | None = Query(None, description="LIPID MAPS id"),
    page: PageParams = Depends(page_params),
    format: str | None = Depends(format_query),
    data: DataService = Depends(get_data),
) -> Response:
    fmt = negotiate(request, format)
    xref = _xref_filter(request)
    filters: dict[str, Term | None] = {
        "q": parse_param("q", lambda v: Lit(ids.parse_search_term(v)), q) if q else None,
        "aop": ids.entity_iri(
            ids.AOP, parse_param("aop", lambda v: ids.parse_entity_id(ids.AOP, v), aop)
        )
        if aop
        else None,
        "stressor": ids.entity_iri(
            ids.STRESSOR,
            parse_param("stressor", lambda v: ids.parse_entity_id(ids.STRESSOR, v), stressor),
        )
        if stressor
        else None,
        "inchikey": Iri(
            f"{ids.IDENTIFIERS_ORG}inchikey/{parse_param('inchikey', ids.parse_inchikey, inchikey)}"
        )
        if inchikey
        else None,
        "xrefs": xref[1] if xref else None,
    }
    count_rows = await data.select("chemicals/count", **filters)
    total = int(count_rows[0]["total"]) if count_rows else 0
    items: list[dict[str, Any]] = []
    if page.offset < total:
        rows = await data.select(
            "chemicals/list", limit=Int(page.limit), offset=Int(page.offset), **filters
        )
        iris = [row["chemical"] for row in rows]
        results = await asyncio.gather(
            *(
                data.select("chemicals/hydrate", chemicals=IriList(tuple(Iri(i) for i in chunk)))
                for chunk in chunked(iris, HYDRATE_CHUNK)
            )
        )
        fields: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        for result in results:
            for row in result:
                fields[row["chemical"]][row["field"]].append(row["value"])
        items = [_summary(iri, fields[iri]) for iri in iris]
    return respond(request, data, fmt=fmt, body=list_body(items, page, total, data, request))


@router.get(
    "/chemicals/{cas}",
    summary="One chemical with synonyms, external identifiers, stressors and AOPs",
    response_model=ChemicalDetailEnvelope,
    responses=NOT_FOUND_RESPONSE,
)
async def get_chemical(
    request: Request,
    cas: str = Path(description=CAS_DOC),
    format: str | None = Depends(format_query),
    data: DataService = Depends(get_data),
) -> Response:
    fmt = negotiate(request, format)
    number = _cas(cas)
    iri = ids.cas_iri(number)
    rows = await data.select("chemicals/detail", chemical=iri)
    if not any(r["field"] == "type" and r["value"] == CHEMICAL_TYPE.value for r in rows):
        raise ApiError(404, "Not Found", f"no chemical with CAS number {number}")
    grouped = group_fields(rows)
    summary = _summary(
        iri.value, {field: [r["value"] for r in rs] for field, rs in grouped.items()}
    )

    def refs(field: str, kind: ids.EntityKind) -> list[dict[str, Any]]:
        found: dict[int, dict[str, Any]] = {}
        for row in grouped.get(field, []):
            if (n := ids.id_from_iri(kind, row["value"])) is not None:
                found.setdefault(n, {"id": n, "title": clean(row.get("title"))})
        return [found[k] for k in sorted(found)]

    detail = {
        **summary,
        "synonyms": sorted(
            unique(clean(r["value"]) for r in grouped.get("synonym", [])), key=str.lower
        ),
        "xrefs": xrefs_by_namespace(r["value"] for r in grouped.get("xref", [])),
        "stressors": refs("stressor", ids.STRESSOR),
        "aops": refs("aop", ids.AOP),
    }
    body = {"data": detail, "meta": {"total": 1, "dataset_version": data.token}}
    return respond(request, data, fmt=fmt, body=body, csv_items=[detail])


@router.get(
    "/chemicals/{cas}/aops",
    summary="AOPs with a stressor containing the chemical",
    response_model=ChemicalAopCollection,
    responses=NOT_FOUND_RESPONSE,
)
async def chemical_aops(
    request: Request,
    cas: str = Path(description=CAS_DOC),
    format: str | None = Depends(format_query),
    data: DataService = Depends(get_data),
) -> Response:
    fmt = negotiate(request, format)
    chemical = ids.cas_iri(_cas(cas))
    await _require_chemical(data, chemical)
    items: dict[int, dict[str, Any]] = {}
    for row in await data.select("chemicals/aops", chemical=chemical):
        aop_id = ids.id_from_iri(ids.AOP, row["aop"])
        if aop_id is None:
            continue
        item = items.setdefault(
            aop_id,
            {
                "id": aop_id,
                "title": clean(row.get("title")),
                "stressor_ids": set(),
                "mie_ids": set(),
            },
        )
        if (sid := ids.id_from_iri(ids.STRESSOR, row["stressor"])) is not None:
            item["stressor_ids"].add(sid)
        if (mie := ids.id_from_iri(ids.KEY_EVENT, row.get("mie", ""))) is not None:
            item["mie_ids"].add(mie)
    result = [
        items[k]
        | {"stressor_ids": sorted(items[k]["stressor_ids"]), "mie_ids": sorted(items[k]["mie_ids"])}
        for k in sorted(items)
    ]
    return respond(request, data, fmt=fmt, body=collection_body(result, data))


@router.get(
    "/chemicals/{cas}/key-events",
    summary="Key Events of the AOPs with a stressor containing the chemical",
    response_model=ChemicalKeyEventCollection,
    responses=NOT_FOUND_RESPONSE,
)
async def chemical_key_events(
    request: Request,
    cas: str = Path(description=CAS_DOC),
    role: str | None = Query(
        None, pattern="^(mie|ke|ao)$", description="Only KEs with this role in at least one AOP"
    ),
    format: str | None = Depends(format_query),
    data: DataService = Depends(get_data),
) -> Response:
    fmt = negotiate(request, format)
    chemical = ids.cas_iri(_cas(cas))
    await _require_chemical(data, chemical)
    items: dict[int, dict[str, Any]] = {}
    for row in await data.select("chemicals/key_events", chemical=chemical):
        ke_id = ids.id_from_iri(ids.KEY_EVENT, row["ke"])
        aop_id = ids.id_from_iri(ids.AOP, row["aop"])
        if ke_id is None or aop_id is None:
            continue
        item = items.setdefault(
            ke_id,
            {
                "id": ke_id,
                "title": clean(row.get("title")),
                "aops": set(),
                "mie": set(),
                "ao": set(),
            },
        )
        item["aops"].add(aop_id)
        if truthy(row.get("is_mie")):
            item["mie"].add(aop_id)
        if truthy(row.get("is_ao")):
            item["ao"].add(aop_id)
    result = []
    for ke_id in sorted(items):
        item = items[ke_id]
        is_ke = bool(item["aops"] - item["mie"] - item["ao"])
        if (
            role == "mie"
            and not item["mie"]
            or role == "ao"
            and not item["ao"]
            or role == "ke"
            and not is_ke
        ):
            continue
        result.append(
            {
                "id": ke_id,
                "title": item["title"],
                "aop_ids": sorted(item["aops"]),
                "mie_in_aop_ids": sorted(item["mie"]),
                "ao_in_aop_ids": sorted(item["ao"]),
            }
        )
    return respond(request, data, fmt=fmt, body=collection_body(result, data))


@router.get(
    "/chemicals/{cas}/pathways",
    summary="WikiPathways pathways containing the chemical (federated query on ChEBI)",
    response_model=PathwayCollection,
    responses=NOT_FOUND_RESPONSE,
)
async def chemical_pathways(
    request: Request,
    cas: str = Path(description=CAS_DOC),
    format: str | None = Depends(format_query),
    data: DataService = Depends(get_data),
) -> Response:
    fmt = negotiate(request, format)
    chemical = ids.cas_iri(_cas(cas))
    await _require_chemical(data, chemical)
    items: dict[str, dict[str, Any]] = {}
    for row in await data.select("chemicals/pathways", federated=True, chemical=chemical):
        items.setdefault(
            row["pathway"],
            {
                "wp_id": row["wp_id"],
                "title": clean(row.get("wp_title")),
                "organism": clean(row.get("organism")),
                "iri": row["pathway"],
                "chebi": row["chebi"].rsplit("/", 1)[-1],
            },
        )
    result = sorted(items.values(), key=lambda p: (p["organism"] or "", p["wp_id"]))
    return respond(request, data, fmt=fmt, body=collection_body(result, data))


async def _require_chemical(data: DataService, chemical: Iri) -> None:
    """404 unless the chemical exists; chemicals are keyed by CAS, not a numeric id."""
    rows = await data.select("meta/exists", entity=chemical, type=CHEMICAL_TYPE)
    if not rows or int(rows[0].get("found", "0")) == 0:
        cas = local_id(chemical.value, "cas")
        raise ApiError(404, "Not Found", f"no chemical with CAS number {cas}")
