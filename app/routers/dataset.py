"""Dataset metadata."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel

from app.data import DataService
from app.deps import get_data
from app.formats import format_query, negotiate, respond

router = APIRouter(tags=["Dataset"])

DCTERMS = "http://purl.org/dc/terms/"
VOID = "http://rdfs.org/ns/void#"
PAV = "http://purl.org/pav/"

ENTITY_TYPES = {
    "http://aopkb.org/aop_ontology#AdverseOutcomePathway": "aops",
    "http://aopkb.org/aop_ontology#KeyEvent": "key_events",
    "http://aopkb.org/aop_ontology#KeyEventRelationship": "kers",
    "http://ncicb.nci.nih.gov/xml/owl/EVS/Thesaurus.owl#C54571": "stressors",
    "http://semanticscience.org/resource/CHEMINF_000000": "chemicals",
    "genes": "genes",
}


class DatasetInfo(BaseModel):
    title: str | None
    version: str
    created_on: str | None
    generator_commit: str | None
    license: str | None
    sparql_endpoint: str | None
    data_dumps: list[str]
    counts: dict[str, int]


class DatasetEnvelope(BaseModel):
    data: DatasetInfo


@router.get(
    "/v1/dataset",
    summary="Version, licence, dumps and entity counts of the served AOP-Wiki RDF release",
    response_model=DatasetEnvelope,
    responses={200: {"content": {"text/csv": {}}}},
)
async def dataset(
    request: Request,
    format: str | None = Depends(format_query),
    data: DataService = Depends(get_data),
) -> Response:
    fmt = negotiate(request, format)
    props = await data.select("meta/dataset", dataset=data.dataset_iri)
    count_rows = await data.select("meta/counts")

    values: dict[str, list[str]] = {}
    for row in props:
        values.setdefault(row["p"], []).append(row["o"])

    def first(predicate: str) -> str | None:
        found = values.get(predicate)
        return found[0] if found else None

    counts = {
        ENTITY_TYPES[row["type"]]: int(row["n"])
        for row in count_rows
        if row["type"] in ENTITY_TYPES
    }
    version = data.version
    info = DatasetInfo(
        title=first(f"{DCTERMS}title"),
        version=version.version if version else "",
        created_on=version.created_on if version else None,
        generator_commit=version.commit if version else None,
        license=first(f"{DCTERMS}license"),
        sparql_endpoint=first(f"{VOID}sparqlEndpoint"),
        data_dumps=sorted(values.get(f"{VOID}dataDump", [])),
        counts=counts,
    )
    body = {"data": info.model_dump()}
    return respond(request, data, fmt=fmt, body=body, csv_items=[info.model_dump()])
