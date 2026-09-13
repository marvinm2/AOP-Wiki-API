from fastapi.testclient import TestClient

from tests.fakes import FakeVirtuoso, bindings

AOP = "https://identifiers.org/aop/"
KE = "https://identifiers.org/aop.events/"
KER = "https://identifiers.org/aop.relationships/"
KER_TYPE = "http://aopkb.org/aop_ontology#KeyEventRelationship"


def add_list_routes(virtuoso: FakeVirtuoso) -> None:
    virtuoso.add("COUNT(DISTINCT ?ker) AS ?total", bindings({"total": 1}))
    virtuoso.add("SELECT DISTINCT ?ker (xsd:integer", bindings({"ker": f"{KER}1229"}))
    virtuoso.add(
        "VALUES ?ker {",
        bindings(
            {"ker": f"{KER}1229", "field": "up", "value": f"{KE}227", "title": "Activation, PPARα"},
            {"ker": f"{KER}1229", "field": "down", "value": f"{KE}1170", "title": "Proliferation"},
            {"ker": f"{KER}1229", "field": "aop", "value": f"{AOP}37"},
            {"ker": f"{KER}1229", "field": "modified", "value": "2020-12-31T11:42:29"},
        ),
    )


def test_list_kers(client: TestClient, virtuoso: FakeVirtuoso):
    add_list_routes(virtuoso)
    body = client.get("/v1/kers?aop=37&ke=KE%20227").json()
    assert body["data"] == [
        {
            "id": 1229,
            "iri": f"{KER}1229",
            "label": "KER 1229",
            "upstream": {"id": 227, "title": "Activation, PPARα"},
            "downstream": {"id": 1170, "title": "Proliferation"},
            "aop_ids": [37],
            "created": None,
            "modified": "2020-12-31T11:42:29",
            "aopwiki_url": "https://aopwiki.org/relationships/1229",
        }
    ]
    count_query = next(q for q in virtuoso.queries if "?total" in q)
    assert f"<{AOP}37> aopo:has_key_event_relationship ?ker" in count_query
    assert f"{{ ?ker aopo:has_upstream_key_event <{KE}227> }} UNION" in count_query


def test_ker_list_csv_flattens_ends(client: TestClient, virtuoso: FakeVirtuoso):
    add_list_routes(virtuoso)
    lines = client.get("/v1/kers?format=csv").text.splitlines()
    assert "upstream_id" in lines[0] and "downstream_title" in lines[0]
    assert ",227," in lines[1]


def test_ker_list_unknown_gene_is_empty(client: TestClient, virtuoso: FakeVirtuoso):
    virtuoso.add("rdfs:label ?label .", bindings())
    body = client.get("/v1/kers?gene=NOPE1").json()
    assert body["meta"]["total"] == 0 and body["data"] == []
    assert not any("?total" in q for q in virtuoso.queries)


def test_ker_detail(client: TestClient, virtuoso: FakeVirtuoso):
    virtuoso.add(
        'BIND("biological_plausibility" AS ?field)',
        bindings(
            {"field": "type", "value": KER_TYPE},
            {"field": "up", "value": f"{KE}227", "title": "Activation, PPARα"},
            {"field": "down", "value": f"{KE}1170", "title": "Proliferation"},
            {"field": "biological_plausibility", "value": "Similar to other nuclear receptors"},
            {"field": "uncertainties", "value": "Vanishingly few."},
            {"field": "time_scale", "value": "1 week"},
            {"field": "applicability", "value": "Rodents"},
            {"field": "sex", "value": "Mixed"},
            {
                "field": "gene",
                "value": "https://identifiers.org/hgnc/9232",
                "title": "PPARA",
                "ner": "1",
                "regex": "0",
            },
            {"field": "aop", "value": f"{AOP}37", "title": "PPARα to tumours"},
        ),
    )
    data = client.get("/v1/kers/1229").json()["data"]
    assert data["upstream"] == {"id": 227, "title": "Activation, PPARα"}
    assert data["evidence"]["biological_plausibility"] == "Similar to other nuclear receptors"
    assert data["evidence"]["empirical_support"] is None
    assert data["quantitative_understanding"]["time_scale"] == "1 week"
    assert data["domain_of_applicability"] == "Rodents"
    assert data["genes"] == [{"hgnc_id": 9232, "symbol": "PPARA", "detected_by": "ner"}]
    assert data["aops"] == [{"id": 37, "title": "PPARα to tumours"}]


def test_ker_detail_404(client: TestClient, virtuoso: FakeVirtuoso):
    virtuoso.add('BIND("biological_plausibility" AS ?field)', bindings())
    assert client.get("/v1/kers/999999").status_code == 404
    assert client.get("/v1/kers/AOP%201").status_code == 400
