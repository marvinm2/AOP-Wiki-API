from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from app.compat.registry import QUERIES
from app.config import Settings
from app.main import create_app
from tests.fakes import FakeVirtuoso, bindings

BASE = "/api-git/marvinm2/AOPWikiQueries"


@pytest.fixture
def accepts() -> list[str]:
    return []


@pytest.fixture
def compat_client(
    virtuoso: FakeVirtuoso, settings: Settings, accepts: list[str]
) -> Iterator[TestClient]:
    def handler(request: httpx.Request) -> httpx.Response:
        accepts.append(request.headers.get("accept", ""))
        return virtuoso(request)

    app = create_app(settings, transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        yield client


def test_registry_covers_all_23_grlc_queries():
    assert len(QUERIES) == 23


def test_get_all_aops_json_passthrough(compat_client, virtuoso, accepts):
    virtuoso.add(
        "SELECT ?AOP ?AOPTitle ?AOPID",
        bindings({"AOP": "https://identifiers.org/aop/1", "AOPTitle": "T", "AOPID": "AOP 1"}),
    )
    response = compat_client.get(f"{BASE}/get-all-aops", headers={"Accept": "application/json"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json()["head"]["vars"] == ["AOP", "AOPTitle", "AOPID"]
    assert response.headers["deprecation"] == "true"
    assert response.headers["link"] == '</v1/aops>; rel="successor-version"'
    assert accepts[-1] == "application/sparql-results+json"


def test_csv_is_requested_from_the_endpoint(compat_client, virtuoso, accepts):
    virtuoso.add(
        "SELECT ?CAS ?ChemicalName",
        httpx.Response(
            200,
            text='"CAS","ChemicalName"\n"50-00-0","Formaldehyde"\n',
            headers={"Content-Type": "text/csv"},
        ),
    )
    response = compat_client.get(f"{BASE}/get-all-chemicals", headers={"Accept": "text/csv"})
    assert response.headers["content-type"] == "text/csv; charset=UTF-8"
    assert response.text.startswith('"CAS","ChemicalName"')
    assert accepts[-1] == "text/csv"


def test_parameters_are_case_insensitive_and_normalised(compat_client, virtuoso):
    virtuoso.add("VALUES ?MIE", bindings())
    response = compat_client.get(f"{BASE}/get-ao-for-mie?mieFILTER=KE%20167")
    assert response.status_code == 200
    query = next(q for q in virtuoso.queries if "VALUES ?MIE" in q)
    assert "VALUES ?MIE { <https://identifiers.org/aop.events/167> }" in query
    assert response.headers["link"] == (
        '</v1/key-events/167/adverse-outcomes>; rel="successor-version"'
    )


def test_defaults_apply_when_parameter_is_missing(compat_client, virtuoso):
    virtuoso.add("VALUES ?aop", bindings())
    compat_client.get(f"{BASE}/get-chemicals-for-aop")
    assert any("VALUES ?aop { <https://identifiers.org/aop/37> }" in q for q in virtuoso.queries)


def test_http_iris_are_rebuilt_as_https(compat_client, virtuoso):
    virtuoso.add("skos:exactMatch ?MatchingIDs", bindings())
    virtuoso.add("VALUES ?aopid", bindings())
    virtuoso.add("(3 AS ?aopfilter)", bindings())
    compat_client.get(
        f"{BASE}/get-matching-identifiers-for-chemical?casfilter=http://identifiers.org/cas/107-18-6"
    )
    compat_client.get(
        f"{BASE}/get-methods-for-multiple-aops?aopfilter=http://identifiers.org/aop/3,AOP%204"
    )
    compat_client.get(f"{BASE}/get-methods-for-aop-simple?aopfilter=3")
    text = "\n".join(virtuoso.queries)
    assert "VALUES ?chemical { <https://identifiers.org/cas/107-18-6> }" in text
    assert (
        "VALUES ?aopid { <https://identifiers.org/aop/3> <https://identifiers.org/aop/4> }" in text
    )
    assert "(3 AS ?aopfilter)" in text


def test_aliases_chebi_and_text_params(compat_client, virtuoso):
    virtuoso.add("cheminf:000407 ?ChEBI", bindings())
    virtuoso.add("VALUES ?AO", bindings())
    virtuoso.add("SERVICE <https://sparql.wikipathways.org/sparql>", bindings())
    compat_client.get(f"{BASE}/get-aop-for-chebi?ChEBIfilter=CHEBI:16605")
    compat_client.get(f"{BASE}/get-chemicals-for-ao%20(id)?aofilter=341")
    compat_client.get(f"{BASE}/get-pathways-for-chemicals?KEfilter=%20Rotenone%20")
    text = "\n".join(virtuoso.queries)
    assert 'FILTER(STR(?ChEBI) = "16605")' in text
    assert "VALUES ?AO { <https://identifiers.org/aop.events/341> }" in text
    assert 'CONTAINS(LCASE(STR(?ChemicalName)), "rotenone")' in text


def test_commit_paths_and_encoded_names(compat_client, virtuoso):
    virtuoso.add("VALUES ?KE", bindings())
    virtuoso.add("VALUES ?AO", bindings())
    ok = compat_client.get(f"{BASE}/commit/abc123/get-mie-for-ao?AOfilter=341")
    encoded = compat_client.get(f"{BASE}/get-stressors-for-ao%20(ID)?aofilter=344")
    assert ok.status_code == 200 and encoded.status_code == 200


def test_errors(compat_client):
    assert compat_client.get(f"{BASE}/get-everything").status_code == 404
    bad = compat_client.get(f"{BASE}/get-ao-for-mie?MIEfilter=abc")
    assert bad.status_code == 400
    assert bad.json()["errors"][0]["param"] == "MIEfilter"
    too_many = ",".join(str(n) for n in range(1, 60))
    assert (
        compat_client.get(f"{BASE}/get-methods-for-multiple-aops?aopfilter={too_many}").status_code
        == 400
    )


def test_redirects(compat_client):
    for path in ("/api/marvinm2/AOPWikiQueries", f"{BASE}/", BASE):
        response = compat_client.get(path, follow_redirects=False)
        assert response.status_code == 308 and response.headers["location"] == "/docs"
    swagger = compat_client.get(
        f"{BASE}/swagger", headers={"X-Forwarded-Prefix": "/api"}, follow_redirects=False
    )
    assert swagger.headers["location"] == "/api/openapi.json"


def test_conditional_request_skips_the_endpoint(compat_client, virtuoso):
    virtuoso.add("SELECT ?KE ?KETitle ?KEID", bindings())
    first = compat_client.get(f"{BASE}/get-all-kes")
    before = len(virtuoso.queries)
    again = compat_client.get(
        f"{BASE}/get-all-kes", headers={"If-None-Match": first.headers["etag"]}
    )
    assert again.status_code == 304
    assert len(virtuoso.queries) == before
