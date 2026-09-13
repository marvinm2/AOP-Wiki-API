import httpx
from fastapi.testclient import TestClient

from tests.fakes import FakeVirtuoso, bindings

AOP = "https://identifiers.org/aop/"
KE = "https://identifiers.org/aop.events/"
KER = "https://identifiers.org/aop.relationships/"
KE_TYPE = "http://aopkb.org/aop_ontology#KeyEvent"
OBO = "http://purl.obolibrary.org/obo/"


def add_list_routes(virtuoso: FakeVirtuoso) -> None:
    virtuoso.add("COUNT(DISTINCT ?ke) AS ?total", bindings({"total": 1}))
    virtuoso.add("SELECT DISTINCT ?ke (xsd:integer", bindings({"ke": f"{KE}18", "number": 18}))
    virtuoso.add(
        "VALUES ?ke {",
        bindings(
            {"ke": f"{KE}18", "field": "title", "value": "Activation, AhR"},
            {"ke": f"{KE}18", "field": "level", "value": "Molecular"},
            {"ke": f"{KE}18", "field": "aop", "value": f"{AOP}21"},
            {"ke": f"{KE}18", "field": "aop", "value": f"{AOP}131"},
            {"ke": f"{KE}18", "field": "mie_of", "value": f"{AOP}21"},
        ),
    )


def test_list_key_events_with_role_and_filters(client: TestClient, virtuoso: FakeVirtuoso):
    add_list_routes(virtuoso)
    response = client.get(
        "/v1/key-events",
        params={"role": "mie", "level": "molecular", "organ": "UBERON:0002107", "aop": "21"},
    )
    assert response.status_code == 200
    item = response.json()["data"][0]
    assert item == {
        "id": 18,
        "iri": f"{KE}18",
        "label": "KE 18",
        "title": "Activation, AhR",
        "short_name": None,
        "level": "Molecular",
        "aop_ids": [21, 131],
        "mie_in_aop_ids": [21],
        "ao_in_aop_ids": [],
        "is_mie": True,
        "is_ao": False,
        "aopwiki_url": "https://aopwiki.org/events/18",
    }
    count_query = next(q for q in virtuoso.queries if "?total" in q)
    assert "aopo:has_molecular_initiating_event ?ke }" in count_query
    assert "has_adverse_outcome" not in count_query
    assert '?ke nci:C25664 "Molecular" .' in count_query
    assert f"aopo:OrganContext <{OBO}UBERON_0002107>" in count_query
    assert "<https://identifiers.org/aop/21> aopo:has_key_event ?ke" in count_query


def test_aos_alias_uses_ao_role(client: TestClient, virtuoso: FakeVirtuoso):
    add_list_routes(virtuoso)
    assert client.get("/v1/aos").status_code == 200
    count_query = next(q for q in virtuoso.queries if "?total" in q)
    assert "has_adverse_outcome ?ke }" in count_query
    assert "has_molecular_initiating_event" not in count_query


def test_invalid_key_event_filters(client: TestClient):
    assert client.get("/v1/key-events?level=Galaxy").json()["errors"][0]["param"] == "level"
    assert client.get("/v1/key-events?organ=liver").json()["errors"][0]["param"] == "organ"
    assert client.get("/v1/key-events?role=boss").status_code == 400


def test_unknown_gene_symbol_gives_empty_list(client: TestClient, virtuoso: FakeVirtuoso):
    virtuoso.add("rdfs:label ?label .", bindings())
    response = client.get("/v1/key-events?gene=NOTAGENE1")
    assert response.status_code == 200
    assert response.json()["data"] == [] and response.json()["meta"]["total"] == 0
    assert not any("?total" in q for q in virtuoso.queries)


def test_gene_symbol_is_resolved_case_insensitively(client: TestClient, virtuoso: FakeVirtuoso):
    add_list_routes(virtuoso)
    virtuoso.add("rdfs:label ?label .", bindings({"gene": "https://identifiers.org/hgnc/348"}))
    assert client.get("/v1/key-events?gene=ahr").status_code == 200
    lookup = next(q for q in virtuoso.queries if "rdfs:label ?label ." in q)
    assert '= "ahr")' in lookup
    count_query = next(q for q in virtuoso.queries if "?total" in q)
    assert "edam:data_1025 <https://identifiers.org/hgnc/348>" in count_query


DETAIL_ROWS = bindings(
    {"field": "type", "value": KE_TYPE},
    {"field": "title", "value": "Activation, AhR"},
    {"field": "level", "value": "Molecular"},
    {"field": "organ", "value": f"{OBO}UBERON_0002107", "title": "liver"},
    {
        "field": "biological_event",
        "value": "18_bioevent_0",
        "process": f"{OBO}GO_0004874",
        "process_title": "aryl hydrocarbon receptor activity",
        "object": f"{OBO}PR_000003858",
        "object_title": "aryl hydrocarbon receptor",
        "action": "increased",
    },
    {"field": "aop", "value": f"{AOP}21", "title": "AhR to mortality", "is_mie": "1", "is_ao": "0"},
    {"field": "aop", "value": f"{AOP}131", "title": "Other", "is_mie": "0", "is_ao": "0"},
    {
        "field": "gene",
        "value": "https://identifiers.org/hgnc/348",
        "title": "AHR",
        "ner": "1",
        "regex": "1",
    },
    {"field": "method", "value": "Reporter &amp; binding assays"},
)


def test_key_event_detail(client: TestClient, virtuoso: FakeVirtuoso):
    virtuoso.add('BIND("biological_event" AS ?field)', DETAIL_ROWS)
    response = client.get("/v1/key-events/KE%2018")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["mie_in_aop_ids"] == [21] and data["is_mie"] is True
    assert data["organ"] == {
        "id": "UBERON:0002107",
        "iri": f"{OBO}UBERON_0002107",
        "title": "liver",
    }
    assert data["cell_type"] is None
    assert data["biological_events"] == [
        {
            "process": {
                "id": "GO:0004874",
                "iri": f"{OBO}GO_0004874",
                "title": "aryl hydrocarbon receptor activity",
            },
            "object": {
                "id": "PR:000003858",
                "iri": f"{OBO}PR_000003858",
                "title": "aryl hydrocarbon receptor",
            },
            "action": "increased",
        }
    ]
    assert data["aops"] == [
        {"id": 21, "title": "AhR to mortality", "role": "mie"},
        {"id": 131, "title": "Other", "role": "ke"},
    ]
    assert data["genes"] == [{"hgnc_id": 348, "symbol": "AHR", "detected_by": "both"}]
    assert data["measurement_methods"] == "Reporter & binding assays"


def test_key_event_detail_404(client: TestClient, virtuoso: FakeVirtuoso):
    virtuoso.add('BIND("biological_event" AS ?field)', bindings())
    assert client.get("/v1/key-events/99999").status_code == 404


def test_downstream_walk_depth_two(client: TestClient, virtuoso: FakeVirtuoso):
    virtuoso.add("(COUNT(*) AS ?found)", bindings({"found": 1}))

    def downstream(query: str) -> httpx.Response:
        if f"VALUES ?from {{ <{KE}18> }}" in query:
            return httpx.Response(
                200,
                json=bindings(
                    {
                        "from": f"{KE}18",
                        "ker": f"{KER}1",
                        "to": f"{KE}20",
                        "to_title": "B",
                        "aop": f"{AOP}5",
                    },
                    {
                        "from": f"{KE}18",
                        "ker": f"{KER}1",
                        "to": f"{KE}20",
                        "to_title": "B",
                        "aop": f"{AOP}3",
                    },
                    {"from": f"{KE}18", "ker": f"{KER}2", "to": f"{KE}21", "to_title": "C"},
                ),
            )
        # second hop: KE 20 -> 22 and a cycle back to 18
        return httpx.Response(
            200,
            json=bindings(
                {"from": f"{KE}20", "ker": f"{KER}3", "to": f"{KE}22", "to_title": "D"},
                {"from": f"{KE}21", "ker": f"{KER}4", "to": f"{KE}18", "to_title": "A"},
            ),
        )

    virtuoso.add("aopo:has_upstream_key_event ?from", downstream)
    body = client.get("/v1/key-events/18/downstream?depth=2").json()
    assert [(e["ker_id"], e["from_ke_id"], e["ke_id"], e["depth"]) for e in body["data"]] == [
        (1, 18, 20, 1),
        (2, 18, 21, 1),
        (4, 21, 18, 2),
        (3, 20, 22, 2),
    ]
    assert body["data"][0]["aop_ids"] == [3, 5]
    hop_queries = [q for q in virtuoso.queries if "aopo:has_upstream_key_event ?from" in q]
    assert len(hop_queries) == 2  # KE 18 is not expanded twice
    assert client.get("/v1/key-events/18/downstream?depth=4").status_code == 400


def test_adverse_outcomes_flag(client: TestClient, virtuoso: FakeVirtuoso):
    virtuoso.add("(COUNT(*) AS ?found)", bindings({"found": 1}))
    virtuoso.add(
        "aopo:has_adverse_outcome ?target",
        bindings(
            {"aop": f"{AOP}21", "aop_title": "X", "target": f"{KE}351", "target_title": "Mortality"}
        ),
    )
    as_mie = client.get("/v1/key-events/18/adverse-outcomes").json()["data"]
    assert as_mie == [{"aop_id": 21, "aop_title": "X", "ke_id": 351, "ke_title": "Mortality"}]
    assert "has_molecular_initiating_event <https://identifiers.org/aop.events/18>" in next(
        q for q in virtuoso.queries if "?target" in q
    )
    virtuoso.queries.clear()
    client.get("/v1/key-events/18/adverse-outcomes?as=any")
    assert "has_molecular_initiating_event" not in next(
        q for q in virtuoso.queries if "?target" in q
    )


def test_key_event_chemicals_are_aggregated(client: TestClient, virtuoso: FakeVirtuoso):
    virtuoso.add("(COUNT(*) AS ?found)", bindings({"found": 1}))
    virtuoso.add(
        "SELECT DISTINCT ?chemical ?cas ?title ?stressor ?aop",
        bindings(
            {
                "chemical": "https://identifiers.org/cas/50-00-0",
                "cas": "50-00-0",
                "title": "Formaldehyde",
                "stressor": "https://identifiers.org/aop.stressor/9",
                "aop": f"{AOP}7",
            },
            {
                "chemical": "https://identifiers.org/cas/50-00-0",
                "cas": "50-00-0",
                "title": "Formaldehyde",
                "stressor": "https://identifiers.org/aop.stressor/9",
                "aop": f"{AOP}2",
            },
        ),
    )
    data = client.get("/v1/key-events/341/chemicals").json()["data"]
    assert data == [
        {"cas": "50-00-0", "title": "Formaldehyde", "stressor_ids": [9], "aop_ids": [2, 7]}
    ]
