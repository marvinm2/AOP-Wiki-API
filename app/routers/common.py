"""Helpers shared by the resource routers."""

from __future__ import annotations

import html
from collections import defaultdict
from collections.abc import Callable, Iterable
from typing import Any

from app.data import DataService
from app.errors import ApiError
from app.ids import IDENTIFIERS_ORG, EntityKind, InvalidIdentifier, entity_iri, id_from_iri
from app.sparql.client import Row
from app.sparql.terms import Iri, TermError


def parse_param[T](name: str, parser: Callable[[Any], T], value: Any) -> T:
    """Run a validator and turn failures into a 400 that names the parameter."""
    try:
        return parser(value)
    except (InvalidIdentifier, TermError, ValueError) as exc:
        raise ApiError(
            400, "Invalid request parameters", errors=[{"param": name, "msg": str(exc)}]
        ) from exc


def clean(value: str | None) -> str | None:
    """Unescape the HTML entities carried over from the AOP-Wiki XML (e.g. `PPAR&alpha;`)."""
    if value is None:
        return None
    text = html.unescape(value).strip()
    return text or None


def truthy(value: str | None) -> bool:
    return value is not None and value.lower() in {"1", "true"}


def unique[T](values: Iterable[T | None]) -> list[T]:
    return list(dict.fromkeys(v for v in values if v is not None))


def local_id(iri: str, namespace: str) -> str | None:
    prefix = f"{IDENTIFIERS_ORG}{namespace}/"
    return iri[len(prefix) :] if iri.startswith(prefix) else None


def group_fields(rows: list[Row], key: str = "field") -> dict[str, list[Row]]:
    grouped: dict[str, list[Row]] = defaultdict(list)
    for row in rows:
        grouped[row[key]].append(row)
    return grouped


def first_text(grouped: dict[str, list[Row]], field: str) -> str | None:
    values = grouped.get(field)
    return clean(values[0]["value"]) if values else None


def joined_text(grouped: dict[str, list[Row]], field: str) -> str | None:
    texts = unique(clean(row["value"]) for row in grouped.get(field, []))
    return "\n\n".join(texts) if texts else None


def ids_of(kind: EntityKind, iris: Iterable[str]) -> list[int]:
    return sorted({n for iri in iris if (n := id_from_iri(kind, iri)) is not None})


NCBITAXON = "http://purl.bioontology.org/ontology/NCBITAXON/"
OBO = "http://purl.obolibrary.org/obo/"


def split_taxa(rows: list[Row]) -> tuple[list[dict[str, Any]], list[str]]:
    """NCBI taxon IRIs (with their synonym titles) and free-text applicability values."""
    taxa: dict[int, dict[str, Any]] = {}
    texts: list[str] = []
    for row in rows:
        value = row["value"]
        local = value[len(NCBITAXON) :] if value.startswith(NCBITAXON) else ""
        if local.isdigit():
            taxon = taxa.setdefault(int(local), {"id": int(local), "iri": value, "names": []})
            if (name := clean(row.get("title"))) and name not in taxon["names"]:
                taxon["names"].append(name)
        elif text := clean(value):
            texts.append(text)
    return [taxa[k] for k in sorted(taxa)], unique(texts)


def ontology_term(iri: str | None, title: str | None = None) -> dict[str, Any] | None:
    """`{"id": "UBERON:0002107", "iri": ..., "title": "liver"}` for an OBO IRI."""
    if not iri:
        return None
    curie = None
    if iri.startswith(OBO) and "_" in iri[len(OBO) :]:
        prefix, _, local = iri[len(OBO) :].partition("_")
        curie = f"{prefix}:{local}"
    return {"id": curie, "iri": iri, "title": clean(title)}


def detected_by(ner: str | None, regex: str | None) -> str:
    found_ner, found_regex = truthy(ner), truthy(regex)
    if found_ner and found_regex:
        return "both"
    return "ner" if found_ner else "regex" if found_regex else "unknown"


def xrefs_by_namespace(iris: Iterable[str]) -> dict[str, list[str]]:
    """Group identifiers.org IRIs as {namespace: [local ids]}."""
    grouped: dict[str, list[str]] = {}
    for iri in iris:
        if not iri.startswith(IDENTIFIERS_ORG):
            continue
        namespace, _, local = iri[len(IDENTIFIERS_ORG) :].partition("/")
        if namespace and local and local not in grouped.setdefault(namespace, []):
            grouped[namespace].append(local)
    return {ns: sorted(values) for ns, values in sorted(grouped.items())}


def chunked[T](items: list[T], size: int) -> list[list[T]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def collection_body(items: list[dict[str, Any]], data: DataService) -> dict[str, Any]:
    return {"data": items, "meta": {"total": len(items), "dataset_version": data.token}}


async def require_entity(data: DataService, kind: EntityKind, entity_id: int, rdf_type: Iri) -> Iri:
    """The entity's IRI, or a 404 when no resource of that type exists."""
    iri = entity_iri(kind, entity_id)
    rows = await data.select("meta/exists", entity=iri, type=rdf_type)
    if not rows or int(rows[0].get("found", "0")) == 0:
        label = kind.key.replace("_", " ")
        raise ApiError(404, "Not Found", f"no {label} with id {entity_id}")
    return iri
