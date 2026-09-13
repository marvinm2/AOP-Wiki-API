from fastapi.testclient import TestClient

from tests.fakes import FakeVirtuoso, bindings

AOP = "https://identifiers.org/aop/"
KE = "https://identifiers.org/aop.events/"
KER = "https://identifiers.org/aop.relationships/"
STRESSOR = "https://identifiers.org/aop.stressor/"
AOP_TYPE = "http://aopkb.org/aop_ontology#AdverseOutcomePathway"


def add_list_routes(virtuoso: FakeVirtuoso, total: int = 2) -> None:
    virtuoso.add("COUNT(DISTINCT ?aop) AS ?total", bindings({"total": total}))
    virtuoso.add(
        "SELECT DISTINCT ?aop (xsd:integer",
        bindings({"aop": f"{AOP}1", "number": 1}, {"aop": f"{AOP}37", "number": 37}),
    )
    virtuoso.add(
        "VALUES ?aop {",
        bindings(
            {"aop": f"{AOP}1", "field": "title", "value": "Alkylation of DNA leads to cancer"},
            {"aop": f"{AOP}37", "field": "title", "value": "PPAR&alpha; activation"},
            {"aop": f"{AOP}37", "field": "oecd_status", "value": "Under Development"},
            {"aop": f"{AOP}37", "field": "mie", "value": f"{KE}227"},
            {"aop": f"{AOP}37", "field": "ao", "value": f"{KE}719"},
        ),
    )


def test_list_aops(client: TestClient, virtuoso: FakeVirtuoso):
    add_list_routes(virtuoso, total=250)
    response = client.get("/v1/aops?limit=2&offset=100")
    assert response.status_code == 200
    body = response.json()
    assert body["meta"] == {
        "total": 250,
        "limit": 2,
        "offset": 100,
        "dataset_version": "2026.09.12-77db517",
    }
    first, second = body["data"]
    assert first["id"] == 1 and first["mie_ids"] == [] and first["oecd_status"] is None
    assert second == {
        "id": 37,
        "iri": f"{AOP}37",
        "label": "AOP 37",
        "title": "PPARα activation",
        "short_name": None,
        "oecd_status": "Under Development",
        "created": None,
        "modified": None,
        "mie_ids": [227],
        "ao_ids": [719],
        "aopwiki_url": "https://aopwiki.org/aops/37",
    }
    assert body["links"]["next"].endswith("offset=102")
    assert "offset=98" in body["links"]["prev"]
    assert response.headers["x-total-count"] == "250"
    assert 'rel="next"' in response.headers["link"]


def test_list_filters_are_rendered_as_typed_terms(client: TestClient, virtuoso: FakeVirtuoso):
    add_list_routes(virtuoso)
    response = client.get(
        "/v1/aops",
        params={
            "q": 'Liver" } ; DROP',
            "status": "WPHA/WNT Endorsed",
            "ke": "KE 18",
            "chemical": "cas:107-18-6",
            "taxon": "9606",
            "modified_since": "2024-01-01",
        },
    )
    assert response.status_code == 200
    count_query = next(q for q in virtuoso.queries if "?total" in q)
    assert 'CONTAINS(LCASE(STR(?filter_text)), "liver\\" } ; drop")' in count_query
    assert '?aop nci:C25688 "WPHA/WNT Endorsed" .' in count_query
    assert "?aop aopo:has_key_event <https://identifiers.org/aop.events/18> ." in count_query
    assert "aopo:has_chemical_entity <https://identifiers.org/cas/107-18-6> ." in count_query
    assert "ncbitaxon:131567 <http://purl.bioontology.org/ontology/NCBITAXON/9606>" in count_query
    assert '>= "2024-01-01"' in count_query
    assert "has_adverse_outcome" not in count_query  # unused filters are left out


def test_list_skips_page_query_past_the_end(client: TestClient, virtuoso: FakeVirtuoso):
    add_list_routes(virtuoso, total=2)
    response = client.get("/v1/aops?offset=10")
    assert response.status_code == 200
    assert response.json()["data"] == []
    assert not any("OFFSET" in q for q in virtuoso.queries)


def test_list_rejects_bad_parameters(client: TestClient):
    response = client.get("/v1/aops?ke=AOP%2037")
    assert response.status_code == 400
    assert response.json()["errors"][0]["param"] == "ke"
    assert client.get("/v1/aops?limit=5000").status_code == 400
    assert client.get("/v1/aops?chemical=12345").json()["errors"][0]["param"] == "chemical"


def test_list_csv(client: TestClient, virtuoso: FakeVirtuoso):
    add_list_routes(virtuoso)
    response = client.get("/v1/aops", headers={"Accept": "text/csv"})
    lines = response.text.splitlines()
    assert lines[0].startswith("id,iri,label,title")
    assert lines[2].startswith("37,https://identifiers.org/aop/37,AOP 37,PPARα activation")
    assert "227" in lines[2]


DETAIL_ROWS = bindings(
    {"field": "type", "value": AOP_TYPE},
    {"field": "title", "value": "PPARα activation leading to tumours"},
    {"field": "description", "value": "First part."},
    {"field": "description", "value": "Second &amp; last."},
    {"field": "sex", "value": "Male"},
    {"field": "sex", "value": "Female"},
    {
        "field": "taxon",
        "value": "http://purl.bioontology.org/ontology/NCBITAXON/10090",
        "title": "mouse",
    },
    {
        "field": "taxon",
        "value": "http://purl.bioontology.org/ontology/NCBITAXON/10090",
        "title": "Mus musculus",
    },
    {"field": "taxon", "value": "rodents"},
    {"field": "key_event", "value": f"{KE}227", "title": "Activation, PPARα", "level": "Molecular"},
    {"field": "key_event", "value": f"{KE}719", "title": "Tumours", "level": "Organ"},
    {"field": "key_event", "value": f"{KE}1170", "title": "Proliferation", "level": "Cellular"},
    {"field": "mie", "value": f"{KE}227"},
    {"field": "ao", "value": f"{KE}719"},
    {"field": "ker", "value": f"{KER}1229", "up": f"{KE}227", "down": f"{KE}1170"},
    {"field": "stressor", "value": f"{STRESSOR}11", "title": "DEHP"},
    {"field": "essentiality", "value": "Knockout mice."},
)


def test_aop_detail(client: TestClient, virtuoso: FakeVirtuoso):
    virtuoso.add('BIND("type" AS ?field)', DETAIL_ROWS)
    response = client.get("/v1/aops/AOP%2037?include=evidence")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == 37 and data["mie_ids"] == [227] and data["ao_ids"] == [719]
    assert data["description"] == "First part.\n\nSecond & last."
    assert data["sexes"] == ["Male", "Female"]
    assert data["taxa"] == [
        {
            "id": 10090,
            "iri": "http://purl.bioontology.org/ontology/NCBITAXON/10090",
            "names": ["mouse", "Mus musculus"],
        }
    ]
    assert data["taxa_text"] == ["rodents"]
    assert [(k["id"], k["role"]) for k in data["key_events"]] == [
        (227, "mie"),
        (719, "ao"),
        (1170, "ke"),
    ]
    assert data["key_event_relationships"] == [
        {
            "id": 1229,
            "upstream": {"id": 227, "title": "Activation, PPARα"},
            "downstream": {"id": 1170, "title": "Proliferation"},
        }
    ]
    assert data["stressors"] == [{"id": 11, "title": "DEHP"}]
    assert data["evidence"]["essentiality"] == "Knockout mice."
    detail_query = next(q for q in virtuoso.queries if 'BIND("type"' in q)
    assert "nci:C48192" in detail_query


def test_aop_detail_without_evidence_flag(client: TestClient, virtuoso: FakeVirtuoso):
    virtuoso.add('BIND("type" AS ?field)', DETAIL_ROWS)
    data = client.get("/v1/aops/37").json()["data"]
    assert "evidence" not in data
    detail_query = next(q for q in virtuoso.queries if 'BIND("type"' in q)
    assert "nci:C48192" not in detail_query


def test_aop_detail_404(client: TestClient, virtuoso: FakeVirtuoso):
    virtuoso.add('BIND("type" AS ?field)', bindings())
    response = client.get("/v1/aops/999999")
    assert response.status_code == 404
    assert response.json()["detail"] == "no AOP with id 999999"


def test_sub_resources_404_for_unknown_aop(client: TestClient, virtuoso: FakeVirtuoso):
    virtuoso.add("(COUNT(*) AS ?found)", bindings({"found": 0}))
    for path in ("key-events", "kers", "stressors", "chemicals", "genes"):
        assert client.get(f"/v1/aops/12345/{path}").status_code == 404


def test_aop_key_events_roles(client: TestClient, virtuoso: FakeVirtuoso):
    virtuoso.add("(COUNT(*) AS ?found)", bindings({"found": 1}))
    virtuoso.add(
        "SELECT ?ke ?title ?level ?mie ?ao",
        bindings(
            {"ke": f"{KE}719", "title": "Tumours", "mie": "0", "ao": "1"},
            {"ke": f"{KE}227", "title": "Activation", "level": "Molecular", "mie": "1", "ao": "0"},
            {"ke": f"{KE}1170", "title": "Proliferation", "mie": "0", "ao": "0"},
        ),
    )
    body = client.get("/v1/aops/37/key-events").json()
    assert [(k["id"], k["role"]) for k in body["data"]] == [(227, "mie"), (719, "ao"), (1170, "ke")]
    assert body["meta"]["total"] == 3
    only_ao = client.get("/v1/aops/37/key-events?role=ao").json()["data"]
    assert [k["id"] for k in only_ao] == [719]


def test_aop_chemicals_and_stressors(client: TestClient, virtuoso: FakeVirtuoso):
    virtuoso.add("(COUNT(*) AS ?found)", bindings({"found": 1}))
    virtuoso.add(
        "SELECT DISTINCT ?chemical ?cas",
        bindings(
            {
                "chemical": "https://identifiers.org/cas/117-81-7",
                "cas": "117-81-7",
                "title": "Di(2-ethylhexyl) phthalate",
                "inchikey": "https://identifiers.org/inchikey/BJQHLKABXJIVAM-UHFFFAOYSA-N",
                "stressor": f"{STRESSOR}11",
            }
        ),
    )
    virtuoso.add(
        "SELECT DISTINCT ?stressor ?title ?chemical",
        bindings(
            {
                "stressor": f"{STRESSOR}11",
                "title": "DEHP",
                "chemical": "https://identifiers.org/cas/117-81-7",
            },
            {
                "stressor": f"{STRESSOR}11",
                "title": "DEHP",
                "chemical": "https://identifiers.org/cas/117-81-8",
            },
        ),
    )
    chemicals = client.get("/v1/aops/37/chemicals").json()["data"]
    assert chemicals == [
        {
            "cas": "117-81-7",
            "title": "Di(2-ethylhexyl) phthalate",
            "inchikey": "BJQHLKABXJIVAM-UHFFFAOYSA-N",
            "stressor_id": 11,
        }
    ]
    stressors = client.get("/v1/aops/37/stressors").json()["data"]
    assert stressors == [{"id": 11, "title": "DEHP", "chemical_cas": ["117-81-7", "117-81-8"]}]


def test_aop_genes_method_filter(client: TestClient, virtuoso: FakeVirtuoso):
    virtuoso.add("(COUNT(*) AS ?found)", bindings({"found": 1}))
    virtuoso.add(
        "SELECT ?entity ?gene ?symbol ?ner ?regex",
        bindings(
            {
                "entity": f"{KE}18",
                "gene": "https://identifiers.org/hgnc/348",
                "symbol": "AHR",
                "ner": "1",
                "regex": "1",
            },
            {
                "entity": f"{KE}18",
                "gene": "https://identifiers.org/hgnc/2595",
                "symbol": "CYP1A1",
                "ner": "1",
                "regex": "0",
            },
            {
                "entity": f"{KER}5",
                "gene": "https://identifiers.org/hgnc/348",
                "symbol": "AHR",
                "ner": "0",
                "regex": "1",
            },
        ),
    )
    genes = client.get("/v1/aops/3/genes").json()["data"]
    assert [(g["symbol"], g["entity_type"], g["detected_by"]) for g in genes] == [
        ("AHR", "key_event", "both"),
        ("AHR", "ker", "regex"),
        ("CYP1A1", "key_event", "ner"),
    ]
    regex = client.get("/v1/aops/3/genes?method=regex").json()["data"]
    assert [(g["symbol"], g["detected_by"]) for g in regex] == [("AHR", "both"), ("AHR", "regex")]
    both = client.get("/v1/aops/3/genes?method=both").json()["data"]
    assert len(both) == 1


def test_methods(client: TestClient, virtuoso: FakeVirtuoso):
    virtuoso.add(
        "SELECT ?aop ?ke ?title ?method",
        bindings(
            {"aop": f"{AOP}4", "ke": f"{KE}2", "title": "B", "method": "Assay &lt;x&gt;"},
            {"aop": f"{AOP}3", "ke": f"{KE}9", "title": "A", "method": "ELISA"},
        ),
    )
    response = client.get("/v1/methods?aop=3,%20AOP%204,3")
    assert response.status_code == 200
    assert [(m["aop_id"], m["ke_id"], m["method"]) for m in response.json()["data"]] == [
        (3, 9, "ELISA"),
        (4, 2, "Assay <x>"),
    ]
    query = next(q for q in virtuoso.queries if "mmo:0000000" in q)
    assert (
        "VALUES ?aop { <https://identifiers.org/aop/3> <https://identifiers.org/aop/4> }" in query
    )


def test_methods_rejects_too_many_or_invalid(client: TestClient):
    too_many = ",".join(str(n) for n in range(1, 52))
    assert client.get(f"/v1/methods?aop={too_many}").status_code == 400
    assert client.get("/v1/methods?aop=3,KE%205").json()["errors"][0]["param"] == "aop"
