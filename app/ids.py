"""Validation and normalisation of identifiers accepted by the API.

Every function either returns a canonical value or raises `InvalidIdentifier`. IRIs sent to
Virtuoso are always rebuilt from the canonical value, never passed through from input.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.sparql.terms import Iri

IDENTIFIERS_ORG = "https://identifiers.org/"


class InvalidIdentifier(ValueError):
    def __init__(self, kind: str, value: object) -> None:
        super().__init__(f"invalid {kind} identifier: {value!r}")
        self.kind = kind
        self.value = value


@dataclass(frozen=True)
class EntityKind:
    key: str
    namespace: str  # identifiers.org prefix
    labels: tuple[str, ...]  # accepted label prefixes, e.g. "AOP 37", "KE 18"
    page: str  # AOP-Wiki page URL prefix

    @property
    def pattern(self) -> re.Pattern[str]:
        ns = re.escape(self.namespace)
        labels = "|".join(re.escape(label) for label in self.labels)
        return re.compile(
            rf"^(?:https?://identifiers\.org/{ns}/|{re.escape(self.page)}|{ns}:"
            rf"|(?:{labels})[\s:_-]*)?([1-9]\d{{0,5}})$",
            re.IGNORECASE,
        )


AOP = EntityKind("aop", "aop", ("aop",), "https://aopwiki.org/aops/")
KEY_EVENT = EntityKind(
    "key_event", "aop.events", ("key event", "ke", "event"), "https://aopwiki.org/events/"
)
KER = EntityKind(
    "ker", "aop.relationships", ("ker", "relationship"), "https://aopwiki.org/relationships/"
)
STRESSOR = EntityKind("stressor", "aop.stressor", ("stressor",), "https://aopwiki.org/stressors/")
KINDS = {k.key: k for k in (AOP, KEY_EVENT, KER, STRESSOR)}

_PATTERNS = {k.key: k.pattern for k in KINDS.values()}


def parse_entity_id(kind: EntityKind, raw: object) -> int:
    """`37`, `AOP 37`, `aop:37`, the identifiers.org IRI (http or https) or the AOP-Wiki URL."""
    m = _PATTERNS[kind.key].match(str(raw).strip())
    if not m:
        raise InvalidIdentifier(kind.key, raw)
    return int(m.group(1))


def entity_iri(kind: EntityKind, entity_id: int) -> Iri:
    return Iri(f"{IDENTIFIERS_ORG}{kind.namespace}/{entity_id}")


def entity_page(kind: EntityKind, entity_id: int) -> str:
    return f"{kind.page}{entity_id}"


def id_from_iri(kind: EntityKind, iri: str) -> int | None:
    """Numeric id of an identifiers.org IRI of the given kind, or None if it is another kind."""
    prefix = f"{IDENTIFIERS_ORG}{kind.namespace}/"
    if iri.startswith(prefix) and iri[len(prefix) :].isdigit():
        return int(iri[len(prefix) :])
    return None


_CAS = re.compile(r"^(?:https?://identifiers\.org/cas/|cas:)?([1-9]\d{1,6}-\d{2}-\d)$", re.I)
_INCHIKEY = re.compile(
    r"^(?:https?://identifiers\.org/inchikey/|inchikey:)?([A-Z]{14}-[A-Z]{10}-[A-Z])$", re.I
)
_CHEBI = re.compile(
    r"^(?:https?://identifiers\.org/chebi/|chebi:)?(?:chebi:)?([1-9]\d{0,6})$", re.I
)
_HGNC_ID = re.compile(r"^(?:https?://identifiers\.org/hgnc/|hgnc:)?([1-9]\d{0,5})$", re.I)
_GENE_SYMBOL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,24}$")
_TAXON = re.compile(
    r"^(?:https?://purl\.bioontology\.org/ontology/NCBITAXON/|ncbitaxon:|taxon:)?([1-9]\d{0,7})$",
    re.I,
)


def parse_cas(raw: object) -> str:
    m = _CAS.match(str(raw).strip())
    if not m:
        raise InvalidIdentifier("CAS", raw)
    return m.group(1)


def cas_iri(cas: str) -> Iri:
    return Iri(f"{IDENTIFIERS_ORG}cas/{cas}")


def parse_inchikey(raw: object) -> str:
    m = _INCHIKEY.match(str(raw).strip())
    if not m:
        raise InvalidIdentifier("InChIKey", raw)
    return m.group(1).upper()


def parse_chebi(raw: object) -> str:
    m = _CHEBI.match(str(raw).strip())
    if not m:
        raise InvalidIdentifier("ChEBI", raw)
    return m.group(1)


@dataclass(frozen=True)
class GeneRef:
    hgnc_id: int | None = None
    symbol: str | None = None


def parse_gene(raw: object) -> GeneRef:
    """An HGNC id (`348`, `HGNC:348`, identifiers.org IRI) or a gene symbol (`AHR`)."""
    value = str(raw).strip()
    if m := _HGNC_ID.match(value):
        return GeneRef(hgnc_id=int(m.group(1)))
    if _GENE_SYMBOL.match(value):
        return GeneRef(symbol=value.upper())
    raise InvalidIdentifier("gene", raw)


def hgnc_iri(hgnc_id: int) -> Iri:
    return Iri(f"{IDENTIFIERS_ORG}hgnc/{hgnc_id}")


def parse_taxon(raw: object) -> int:
    m = _TAXON.match(str(raw).strip())
    if not m:
        raise InvalidIdentifier("NCBI taxon", raw)
    return int(m.group(1))


def taxon_iri(taxon_id: int) -> Iri:
    return Iri(f"http://purl.bioontology.org/ontology/NCBITAXON/{taxon_id}")


OBO = "http://purl.obolibrary.org/obo/"


def parse_obo_term(prefix: str, raw: object) -> Iri:
    """An OBO term such as `UBERON:0002107`, `UBERON_0002107` or its PURL, as an IRI."""
    pattern = re.compile(
        rf"^(?:https?://purl\.obolibrary\.org/obo/)?{re.escape(prefix)}[:_](\d{{7}})$", re.I
    )
    m = pattern.match(str(raw).strip())
    if not m:
        raise InvalidIdentifier(prefix, raw)
    return Iri(f"{OBO}{prefix}_{m.group(1)}")


@dataclass(frozen=True)
class XrefKind:
    key: str
    namespace: str
    pattern: re.Pattern[str]


XREFS = {
    x.key: x
    for x in (
        XrefKind("pubchem", "pubchem.compound", re.compile(r"^(?:CID)?([1-9]\d*)$", re.I)),
        XrefKind("chemspider", "chemspider", re.compile(r"^([1-9]\d*)$")),
        XrefKind("wikidata", "wikidata", re.compile(r"^(Q[1-9]\d*)$", re.I)),
        XrefKind("chembl", "chembl.compound", re.compile(r"^(CHEMBL\d+)$", re.I)),
        XrefKind("drugbank", "drugbank", re.compile(r"^(DB\d{5})$", re.I)),
        XrefKind("kegg", "kegg.compound", re.compile(r"^(C\d{5})$", re.I)),
        XrefKind("hmdb", "hmdb", re.compile(r"^(HMDB\d{5,7})$", re.I)),
        XrefKind("lipidmaps", "lipidmaps", re.compile(r"^(LM[A-Z]{2}[0-9A-Z]{8,10})$", re.I)),
    )
}


def parse_xref(key: str, raw: object) -> list[Iri]:
    """identifiers.org IRIs to match for an external chemical identifier.

    Accepts the bare id, the `<namespace>:<id>` CURIE or the identifiers.org IRI. HMDB ids occur
    in the data both zero-padded (HMDB0034436) and unpadded (HMDB34436), so both are returned.
    """
    kind = XREFS[key]
    value = str(raw).strip()
    for prefix in (
        f"https://identifiers.org/{kind.namespace}/",
        f"http://identifiers.org/{kind.namespace}/",
        f"{kind.namespace}:",
    ):
        if value.lower().startswith(prefix.lower()):
            value = value[len(prefix) :]
            break
    m = kind.pattern.match(value)
    if not m:
        raise InvalidIdentifier(key, raw)
    canonical = m.group(1).upper()
    if key == "pubchem" or key == "chemspider":
        canonical = m.group(1)
    variants = [canonical]
    if key == "hmdb":
        digits = int(canonical[4:])
        variants = sorted({f"HMDB{digits:07d}", f"HMDB{digits:05d}"})
    return [Iri(f"{IDENTIFIERS_ORG}{kind.namespace}/{v}") for v in variants]


def parse_search_term(raw: object, *, min_length: int = 2, max_length: int = 200) -> str:
    value = " ".join(str(raw).split()).lower()
    if not min_length <= len(value) <= max_length:
        raise InvalidIdentifier("search term", raw)
    return value
