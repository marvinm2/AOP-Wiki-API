"""Response models. They document the JSON shapes in OpenAPI; handlers serialise directly."""

from __future__ import annotations

from pydantic import BaseModel, Field

CSV_RESPONSE: dict[int | str, dict] = {
    200: {"content": {"text/csv": {"schema": {"type": "string"}}}},
    400: {"description": "Invalid parameter (application/problem+json)"},
}
NOT_FOUND_RESPONSE: dict[int | str, dict] = {
    **CSV_RESPONSE,
    404: {"description": "Unknown entity (application/problem+json)"},
}


class Meta(BaseModel):
    total: int
    limit: int | None = None
    offset: int | None = None
    dataset_version: str


class Links(BaseModel):
    self: str
    next: str | None = None
    prev: str | None = None


class Ref(BaseModel):
    id: int
    title: str | None = None


class AopSummary(BaseModel):
    id: int
    iri: str
    label: str
    title: str | None
    short_name: str | None
    oecd_status: str | None
    created: str | None
    modified: str | None
    mie_ids: list[int]
    ao_ids: list[int]
    aopwiki_url: str


class AopList(BaseModel):
    data: list[AopSummary]
    meta: Meta
    links: Links


class Taxon(BaseModel):
    id: int
    iri: str
    names: list[str]


class AopKeyEvent(BaseModel):
    id: int
    title: str | None
    level: str | None = Field(None, description="Level of biological organisation")
    role: str = Field(description="mie, ao or ke: the role of the Key Event in this AOP")


class AopKer(BaseModel):
    id: int
    upstream: Ref
    downstream: Ref


class AopEvidence(BaseModel):
    essentiality: str | None = None
    overall_assessment: str | None = None
    evidence_summary: str | None = None
    quantitative_understanding: str | None = None
    potential_applications: str | None = None
    context: str | None = None


class AopDetail(AopSummary):
    abstract: str | None
    description: str | None
    creator: str | None
    license: str | None
    sexes: list[str]
    life_stages: list[str]
    taxa: list[Taxon]
    taxa_text: list[str] = Field(description="Taxonomic applicability given as free text")
    key_events: list[AopKeyEvent]
    key_event_relationships: list[AopKer]
    stressors: list[Ref]
    evidence: AopEvidence | None = Field(None, description="Only with include=evidence")


class AopDetailEnvelope(BaseModel):
    data: AopDetail
    meta: Meta


class AopChemical(BaseModel):
    cas: str | None
    title: str | None
    inchikey: str | None
    stressor_id: int | None


class AopStressor(BaseModel):
    id: int
    title: str | None
    chemical_cas: list[str]


class AopGene(BaseModel):
    hgnc_id: int
    symbol: str | None
    entity_type: str = Field(description="key_event or ker")
    entity_id: int
    detected_by: str = Field(description="regex, ner, both, or unknown")


class Method(BaseModel):
    aop_id: int
    ke_id: int
    ke_title: str | None
    method: str


class OntologyTerm(BaseModel):
    id: str | None = Field(description="CURIE, e.g. UBERON:0002107")
    iri: str
    title: str | None


class KeyEventSummary(BaseModel):
    id: int
    iri: str
    label: str
    title: str | None
    short_name: str | None
    level: str | None = Field(description="Level of biological organisation")
    aop_ids: list[int]
    mie_in_aop_ids: list[int] = Field(description="AOPs in which this KE is the MIE")
    ao_in_aop_ids: list[int] = Field(description="AOPs in which this KE is the adverse outcome")
    is_mie: bool
    is_ao: bool
    aopwiki_url: str


class KeyEventList(BaseModel):
    data: list[KeyEventSummary]
    meta: Meta
    links: Links


class BiologicalEvent(BaseModel):
    process: OntologyTerm | None
    object: OntologyTerm | None
    action: str | None


class KeyEventAop(BaseModel):
    id: int
    title: str | None
    role: str = Field(description="mie, ao or ke: the role of the Key Event in that AOP")


class KeyEventGene(BaseModel):
    hgnc_id: int
    symbol: str | None
    detected_by: str


class KeyEventDetail(KeyEventSummary):
    description: str | None
    measurement_methods: str | None
    domain_of_applicability: str | None
    sexes: list[str]
    life_stages: list[str]
    taxa: list[Taxon]
    taxa_text: list[str]
    organ: OntologyTerm | None
    cell_type: OntologyTerm | None
    biological_events: list[BiologicalEvent]
    aops: list[KeyEventAop]
    genes: list[KeyEventGene]


class KeyEventDetailEnvelope(BaseModel):
    data: KeyEventDetail
    meta: Meta


class Neighbour(BaseModel):
    ker_id: int
    from_ke_id: int
    ke_id: int
    ke_title: str | None
    depth: int
    aop_ids: list[int]


class RoleLink(BaseModel):
    aop_id: int
    aop_title: str | None
    ke_id: int
    ke_title: str | None


class KeyEventStressor(BaseModel):
    id: int
    title: str | None
    aop_ids: list[int]


class KeyEventChemical(BaseModel):
    cas: str | None
    title: str | None
    stressor_ids: list[int]
    aop_ids: list[int]


class KerSummary(BaseModel):
    id: int
    iri: str
    label: str
    upstream: Ref | None
    downstream: Ref | None
    aop_ids: list[int]
    created: str | None
    modified: str | None
    aopwiki_url: str


class KerList(BaseModel):
    data: list[KerSummary]
    meta: Meta
    links: Links


class KerEvidence(BaseModel):
    biological_plausibility: str | None
    empirical_support: str | None
    uncertainties: str | None
    evidence_collection_strategy: str | None
    known_modulating_factors: str | None


class KerQuantitativeUnderstanding(BaseModel):
    description: str | None
    response_response_relationship: str | None
    time_scale: str | None
    feedback_loops: str | None = Field(description="Feedforward/feedback loops")


class KerDetail(KerSummary):
    description: str | None
    evidence: KerEvidence
    quantitative_understanding: KerQuantitativeUnderstanding
    domain_of_applicability: str | None
    sexes: list[str]
    life_stages: list[str]
    taxa: list[Taxon]
    taxa_text: list[str]
    genes: list[KeyEventGene]
    aops: list[Ref]


class KerDetailEnvelope(BaseModel):
    data: KerDetail
    meta: Meta


class StressorSummary(BaseModel):
    id: int
    iri: str
    label: str
    title: str | None
    created: str | None
    modified: str | None
    chemical_cas: list[str]
    aop_ids: list[int]
    aopwiki_url: str


class StressorList(BaseModel):
    data: list[StressorSummary]
    meta: Meta
    links: Links


class ChemicalRef(BaseModel):
    cas: str | None
    title: str | None
    inchikey: str | None


class StressorDetail(StressorSummary):
    description: str | None
    chemicals: list[ChemicalRef]
    aops: list[Ref]


class StressorDetailEnvelope(BaseModel):
    data: StressorDetail
    meta: Meta


class ChemicalSummary(BaseModel):
    cas: str | None
    iri: str
    title: str | None
    inchikey: str | None
    comptox_id: str | None = Field(description="EPA CompTox DTXSID")
    stressor_ids: list[int]


class ChemicalList(BaseModel):
    data: list[ChemicalSummary]
    meta: Meta
    links: Links


class ChemicalDetail(ChemicalSummary):
    synonyms: list[str]
    xrefs: dict[str, list[str]] = Field(
        description="External ids by identifiers.org namespace, e.g. chebi, pubchem.compound"
    )
    stressors: list[Ref]
    aops: list[Ref]


class ChemicalDetailEnvelope(BaseModel):
    data: ChemicalDetail
    meta: Meta


class ChemicalAop(BaseModel):
    id: int
    title: str | None
    stressor_ids: list[int]
    mie_ids: list[int]


class ChemicalKeyEvent(BaseModel):
    id: int
    title: str | None
    aop_ids: list[int]
    mie_in_aop_ids: list[int]
    ao_in_aop_ids: list[int]


class Pathway(BaseModel):
    wp_id: str
    title: str | None
    organism: str | None
    iri: str
    chebi: str


class GeneSummary(BaseModel):
    hgnc_id: int
    iri: str
    symbol: str | None
    ke_count: int
    ker_count: int
    hgnc_url: str


class GeneList(BaseModel):
    data: list[GeneSummary]
    meta: Meta
    links: Links


class GeneKeyEvent(BaseModel):
    id: int
    title: str | None
    detected_by: str


class GeneKer(BaseModel):
    id: int
    upstream_id: int | None
    downstream_id: int | None
    detected_by: str


class GeneDetail(BaseModel):
    hgnc_id: int
    iri: str
    symbol: str | None
    hgnc_url: str
    xrefs: dict[str, list[str]]
    key_events: list[GeneKeyEvent]
    kers: list[GeneKer]
    aops: list[Ref]


class GeneDetailEnvelope(BaseModel):
    data: GeneDetail
    meta: Meta


class Collection(BaseModel):
    meta: Meta


class AopKeyEventCollection(Collection):
    data: list[AopKeyEvent]


class AopKerCollection(Collection):
    data: list[AopKer]


class AopStressorCollection(Collection):
    data: list[AopStressor]


class AopChemicalCollection(Collection):
    data: list[AopChemical]


class AopGeneCollection(Collection):
    data: list[AopGene]


class MethodCollection(Collection):
    data: list[Method]


class KeyEventAopCollection(Collection):
    data: list[KeyEventAop]


class NeighbourCollection(Collection):
    data: list[Neighbour]


class RoleLinkCollection(Collection):
    data: list[RoleLink]


class KeyEventStressorCollection(Collection):
    data: list[KeyEventStressor]


class KeyEventChemicalCollection(Collection):
    data: list[KeyEventChemical]


class ChemicalAopCollection(Collection):
    data: list[ChemicalAop]


class ChemicalKeyEventCollection(Collection):
    data: list[ChemicalKeyEvent]


class PathwayCollection(Collection):
    data: list[Pathway]
