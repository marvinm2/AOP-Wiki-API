import httpx
from fastapi.testclient import TestClient

from app.main import create_app
from tests.fakes import VERSION_FRAGMENT, FakeVirtuoso, bindings

DATASET = "https://aopwiki.rdf.bigcat-bioinformatics.org/AOPWikiRDF"


def add_dataset_routes(virtuoso: FakeVirtuoso) -> None:
    virtuoso.add(
        "void:dataDump }",
        bindings(
            {
                "p": "http://purl.org/dc/terms/license",
                "o": "https://creativecommons.org/licenses/by-sa/4.0/",
            },
            {
                "p": "http://rdfs.org/ns/void#sparqlEndpoint",
                "o": "https://aopwiki.rdf.bigcat-bioinformatics.org/sparql/",
            },
            {
                "p": "http://rdfs.org/ns/void#dataDump",
                "o": "https://raw.githubusercontent.com/marvinm2/AOPWikiRDF/master/data/AOPWikiRDF.ttl",
            },
        ),
    )
    virtuoso.add(
        '("genes" AS ?type)',
        bindings(
            {"type": "http://aopkb.org/aop_ontology#AdverseOutcomePathway", "n": 597},
            {"type": "http://aopkb.org/aop_ontology#KeyEvent", "n": 1602},
            {"type": "genes", "n": 2726},
        ),
    )


def test_health_is_static(client: TestClient, virtuoso: FakeVirtuoso):
    before = len(virtuoso.queries)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["cache-control"] == "no-store"
    assert len(virtuoso.queries) == before


def test_ready_reports_version_token(client: TestClient):
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["dataset_version"] == "2026.09.12-77db517"


def test_ready_is_503_when_store_is_empty(client: TestClient, virtuoso: FakeVirtuoso):
    virtuoso.add("ASK", {"head": {}, "boolean": False})
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "store empty" in response.json()["detail"]


def test_dataset_json_and_conditional_request(client: TestClient, virtuoso: FakeVirtuoso):
    add_dataset_routes(virtuoso)
    response = client.get("/v1/dataset")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["version"] == "2026.09.12"
    assert data["license"] == "https://creativecommons.org/licenses/by-sa/4.0/"
    assert data["counts"] == {"aops": 597, "key_events": 1602, "genes": 2726}
    assert response.headers["x-dataset-version"] == "2026.09.12-77db517"
    etag = response.headers["etag"]
    assert etag.startswith('W/"2026.09.12-77db517-')

    queries_before = len(virtuoso.queries)
    cached = client.get("/v1/dataset", headers={"If-None-Match": etag})
    assert cached.status_code == 304
    assert len(virtuoso.queries) == queries_before  # served from cache, no SPARQL


def test_dataset_csv(client: TestClient, virtuoso: FakeVirtuoso):
    add_dataset_routes(virtuoso)
    by_param = client.get("/v1/dataset?format=csv")
    by_accept = client.get("/v1/dataset", headers={"Accept": "text/csv"})
    for response in (by_param, by_accept):
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        header = response.text.splitlines()[0]
        assert "counts_aops" in header and "data_dumps" in header


def test_unsupported_accept_is_406(client: TestClient):
    response = client.get("/v1/dataset", headers={"Accept": "application/rdf+xml"})
    assert response.status_code == 406


def test_unavailable_dataset_is_503(settings, virtuoso: FakeVirtuoso):
    virtuoso.add(VERSION_FRAGMENT, bindings())
    app = create_app(settings, transport=httpx.MockTransport(virtuoso))
    with TestClient(app) as client:
        response = client.get("/v1/dataset")
    assert response.status_code == 503
    assert response.json()["title"] == "Dataset unavailable"
    assert response.headers["retry-after"] == "60"


def test_sparql_error_is_502(client: TestClient):
    # no fake route for the dataset queries -> Virtuoso-style 400 error
    response = client.get("/v1/dataset")
    assert response.status_code == 502
    assert "SP030" in response.json()["detail"]


def test_unknown_route_is_problem_json(client: TestClient):
    response = client.get("/v1/nope")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


def test_forwarded_prefix(client: TestClient):
    root = client.get("/", headers={"X-Forwarded-Prefix": "/api"}, follow_redirects=False)
    assert root.status_code == 308
    assert root.headers["location"] == "/api/docs"
    docs = client.get("/docs", headers={"X-Forwarded-Prefix": "/api"})
    assert "/api/openapi.json" in docs.text
    assert client.get("/", follow_redirects=False).headers["location"] == "/docs"
