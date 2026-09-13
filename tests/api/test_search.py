from fastapi.testclient import TestClient

from tests.fakes import FakeVirtuoso, bindings


def add_search_routes(virtuoso: FakeVirtuoso) -> None:
    virtuoso.add(
        "?entity a aopo:AdverseOutcomePathway .",
        bindings(
            {"entity": "https://identifiers.org/aop/150", "text": "Liver fibrosis", "kind": "title"}
        ),
    )
    virtuoso.add(
        "?entity a aopo:KeyEvent .",
        bindings(
            {
                "entity": "https://identifiers.org/aop.events/344",
                "text": "Liver fibrosis",
                "kind": "title",
            }
        ),
    )
    virtuoso.add("?entity a nci:C54571", bindings())
    virtuoso.add(
        "?entity a cheminf:000000 ;",
        bindings(
            {
                "entity": "https://identifiers.org/cas/83-79-4",
                "text": "Rotenone",
                "aliases": "Derris|||tubatoxin",
            },
        ),
    )
    virtuoso.add(
        "?linked edam:data_1025 ?entity .",
        bindings({"entity": "https://identifiers.org/hgnc/348", "text": "AHR", "kind": "title"}),
    )


def test_search_builds_index_once(client: TestClient, virtuoso: FakeVirtuoso):
    add_search_routes(virtuoso)
    response = client.get("/v1/search?q=liver%20fibrosis", headers={"X-Forwarded-Prefix": "/api"})
    assert response.status_code == 200
    body = response.json()
    assert [(h["type"], h["id"]) for h in body["data"]] == [("aop", 150), ("key_event", 344)]
    assert body["data"][0]["path"] == "/api/v1/aops/150"
    assert body["meta"]["total"] == 2
    index_queries = len(virtuoso.queries)
    derris = client.get("/v1/search?q=tubatoxin").json()["data"]
    assert derris[0]["title"] == "Rotenone" and derris[0]["matched"] == "tubatoxin"
    assert len(virtuoso.queries) == index_queries  # index reused for the same dataset version


def test_search_validation(client: TestClient):
    assert client.get("/v1/search?q=a").status_code == 400
    assert client.get("/v1/search?q=liver&types=aop,planet").json()["errors"][0]["param"] == "types"
    assert client.get("/v1/search").status_code == 400
