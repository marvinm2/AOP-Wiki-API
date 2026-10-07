"""Stressors, chemicals and genes against the fake Virtuoso."""

from fastapi.testclient import TestClient

from tests.fakes import FakeVirtuoso, bindings

AOP = "https://identifiers.org/aop/"
KE = "https://identifiers.org/aop.events/"
KER = "https://identifiers.org/aop.relationships/"
STRESSOR = "https://identifiers.org/aop.stressor/"
CAS = "https://identifiers.org/cas/"
IDS = "https://identifiers.org/"


def test_stressor_list_and_has_chemical_flag(client: TestClient, virtuoso: FakeVirtuoso):
    virtuoso.add("COUNT(DISTINCT ?stressor) AS ?total", bindings({"total": 1}))
    virtuoso.add("SELECT DISTINCT ?stressor (xsd:integer", bindings({"stressor": f"{STRESSOR}11"}))
    virtuoso.add(
        "VALUES ?stressor {",
        bindings(
            {"stressor": f"{STRESSOR}11", "field": "title", "value": "DEHP"},
            {"stressor": f"{STRESSOR}11", "field": "chemical", "value": f"{CAS}117-81-7"},
            {"stressor": f"{STRESSOR}11", "field": "aop", "value": f"{AOP}37"},
            {"stressor": f"{STRESSOR}11", "field": "aop", "value": f"{AOP}8"},
        ),
    )
    body = client.get("/v1/stressors?has_chemical=true&chemical=117-81-7").json()
    assert body["data"] == [
        {
            "id": 11,
            "iri": f"{STRESSOR}11",
            "label": "Stressor 11",
            "title": "DEHP",
            "created": None,
            "modified": None,
            "chemical_cas": ["117-81-7"],
            "aop_ids": [8, 37],
            "aopwiki_url": "https://aopwiki.org/stressors/11",
        }
    ]
    count_query = next(q for q in virtuoso.queries if "?total" in q)
    assert "FILTER EXISTS { ?stressor aopo:has_chemical_entity" in count_query
    assert f"aopo:has_chemical_entity <{CAS}117-81-7>" in count_query


def test_stressor_detail_404(client: TestClient, virtuoso: FakeVirtuoso):
    virtuoso.add("SELECT ?field ?value ?title ?cas ?inchikey", bindings())
    assert client.get("/v1/stressors/99999").status_code == 404


CHEMICAL_DETAIL = bindings(
    {"field": "type", "value": "http://semanticscience.org/resource/CHEMINF_000000"},
    {"field": "title", "value": "Rotenone"},
    {"field": "cas", "value": "83-79-4"},
    {"field": "inchikey", "value": f"{IDS}inchikey/JUVIOZPCNVVQFO-HBGVWJBISA-N"},
    {"field": "comptox", "value": f"{IDS}comptox/DTXSID6021248"},
    {"field": "synonym", "value": "tubatoxin"},
    {"field": "synonym", "value": "Derris"},
    {"field": "xref", "value": f"{IDS}chebi/CHEBI:28201"},
    {"field": "xref", "value": f"{IDS}hmdb/HMDB34436"},
    {"field": "xref", "value": f"{IDS}hmdb/HMDB0034436"},
    {"field": "stressor", "value": f"{STRESSOR}50", "title": "Rotenone"},
    {"field": "aop", "value": f"{AOP}326", "title": "B"},
    {"field": "aop", "value": f"{AOP}3", "title": "A"},
)


def test_chemical_detail(client: TestClient, virtuoso: FakeVirtuoso):
    virtuoso.add('BIND("synonym" AS ?field)', CHEMICAL_DETAIL)
    data = client.get("/v1/chemicals/cas:83-79-4").json()["data"]
    assert data["cas"] == "83-79-4"
    assert data["inchikey"] == "JUVIOZPCNVVQFO-HBGVWJBISA-N"
    assert data["comptox_id"] == "DTXSID6021248"
    assert data["synonyms"] == ["Derris", "tubatoxin"]
    assert data["xrefs"] == {"chebi": ["28201"], "hmdb": ["HMDB0034436", "HMDB34436"]}
    assert data["stressor_ids"] == [50]
    assert [a["id"] for a in data["aops"]] == [3, 326]
    assert client.get("/v1/chemicals/not-a-cas").status_code == 400


def test_chemical_xref_filters(client: TestClient, virtuoso: FakeVirtuoso):
    virtuoso.add("COUNT(DISTINCT ?chemical) AS ?total", bindings({"total": 0}))
    assert client.get("/v1/chemicals?chebi=CHEBI:28201").status_code == 200
    query = next(q for q in virtuoso.queries if "?total" in q)
    assert f"VALUES ?filter_xref {{ <{IDS}chebi/CHEBI:28201> <{IDS}chebi/28201> }}" in query
    virtuoso.queries.clear()
    client.get("/v1/chemicals?hmdb=HMDB34436")
    query = next(q for q in virtuoso.queries if "?total" in q)
    assert f"<{IDS}hmdb/HMDB0034436> <{IDS}hmdb/HMDB34436>" in query
    both = client.get("/v1/chemicals?chebi=28201&wikidata=Q42")
    assert both.status_code == 400
    assert client.get("/v1/chemicals?inchikey=nope").json()["errors"][0]["param"] == "inchikey"


def test_chemical_key_events_role_aggregation(client: TestClient, virtuoso: FakeVirtuoso):
    virtuoso.add("(COUNT(*) AS ?found)", bindings({"found": 1}))
    virtuoso.add(
        "SELECT DISTINCT ?ke ?title ?aop ?is_mie ?is_ao",
        bindings(
            {
                "ke": f"{KE}888",
                "title": "Complex I inhibition",
                "aop": f"{AOP}3",
                "is_mie": "1",
                "is_ao": "0",
            },
            {
                "ke": f"{KE}888",
                "title": "Complex I inhibition",
                "aop": f"{AOP}9",
                "is_mie": "0",
                "is_ao": "0",
            },
            {
                "ke": f"{KE}890",
                "title": "Parkinsonian motor deficits",
                "aop": f"{AOP}3",
                "is_mie": "0",
                "is_ao": "1",
            },
        ),
    )
    all_kes = client.get("/v1/chemicals/83-79-4/key-events").json()["data"]
    assert all_kes[0] == {
        "id": 888,
        "title": "Complex I inhibition",
        "aop_ids": [3, 9],
        "mie_in_aop_ids": [3],
        "ao_in_aop_ids": [],
    }
    assert [
        k["id"] for k in client.get("/v1/chemicals/83-79-4/key-events?role=ao").json()["data"]
    ] == [890]
    assert [
        k["id"] for k in client.get("/v1/chemicals/83-79-4/key-events?role=ke").json()["data"]
    ] == [888]


def test_chemical_404_for_sub_resources(client: TestClient, virtuoso: FakeVirtuoso):
    virtuoso.add("(COUNT(*) AS ?found)", bindings({"found": 0}))
    for path in ("aops", "key-events", "pathways"):
        response = client.get(f"/v1/chemicals/50-00-0/{path}")
        assert response.status_code == 404
        assert "50-00-0" in response.json()["detail"]


def test_gene_list_and_method_flags(client: TestClient, virtuoso: FakeVirtuoso):
    virtuoso.add("COUNT(DISTINCT ?gene) AS ?total", bindings({"total": 1}))
    virtuoso.add(
        "(COUNT(DISTINCT ?ke) AS ?ke_count)",
        bindings({"gene": f"{IDS}hgnc/9232", "symbol": "PPARA", "ke_count": 24, "ker_count": 28}),
    )
    body = client.get("/v1/genes?q=ppar&method=both&aop=37").json()
    assert body["data"] == [
        {
            "hgnc_id": 9232,
            "iri": f"{IDS}hgnc/9232",
            "symbol": "PPARA",
            "ke_count": 24,
            "ker_count": 28,
            "hgnc_url": "https://www.genenames.org/data/gene-symbol-report/#!/hgnc_id/HGNC:9232",
        }
    ]
    query = next(q for q in virtuoso.queries if "?total" in q)
    assert "aopwiki:geneDetectedByNER ?gene" in query and "geneDetectedByRegex ?gene" in query
    assert 'STRSTARTS(LCASE(STR(?filter_symbol)), "ppar")' in query
    virtuoso.queries.clear()
    client.get("/v1/genes")
    query = next(q for q in virtuoso.queries if "?total" in q)
    assert "geneDetectedBy" not in query


def test_gene_detail_by_symbol(client: TestClient, virtuoso: FakeVirtuoso):
    virtuoso.add("rdfs:label ?label .", bindings({"gene": f"{IDS}hgnc/348"}))
    virtuoso.add(
        'BIND("symbol" AS ?field)',
        bindings(
            {"field": "type", "value": "http://edamontology.org/data_2298"},
            {"field": "symbol", "value": "AHR"},
            {"field": "xref", "value": f"{IDS}uniprot/P35869"},
            {"field": "xref", "value": f"{IDS}ncbigene/196"},
            {
                "field": "key_event",
                "value": f"{KE}18",
                "title": "Activation, AhR",
                "ner": "1",
                "regex": "1",
            },
            {
                "field": "ker",
                "value": f"{KER}5",
                "up": f"{KE}18",
                "down": f"{KE}20",
                "ner": "0",
                "regex": "1",
            },
            {"field": "aop", "value": f"{AOP}21", "title": "X"},
            {"field": "aop", "value": f"{AOP}21", "title": "X"},
        ),
    )
    data = client.get("/v1/genes/ahr").json()["data"]
    assert data["hgnc_id"] == 348 and data["symbol"] == "AHR"
    assert data["xrefs"] == {"ncbigene": ["196"], "uniprot": ["P35869"]}
    assert data["key_events"] == [{"id": 18, "title": "Activation, AhR", "detected_by": "both"}]
    assert data["kers"] == [
        {"id": 5, "upstream_id": 18, "downstream_id": 20, "detected_by": "regex"}
    ]
    assert data["aops"] == [{"id": 21, "title": "X"}]


def test_unknown_gene_is_404(client: TestClient, virtuoso: FakeVirtuoso):
    virtuoso.add("rdfs:label ?label .", bindings())
    assert client.get("/v1/genes/NOTAGENE").status_code == 404
