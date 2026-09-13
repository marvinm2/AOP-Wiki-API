"""Search checks against the public endpoint (`pytest -m live`)."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

pytestmark = pytest.mark.live

ENDPOINT = os.environ.get(
    "LIVE_SPARQL_ENDPOINT", "https://aopwiki.rdf.bigcat-bioinformatics.org/sparql"
)


@pytest.fixture(scope="module")
def live() -> Iterator[TestClient]:
    app = create_app(Settings(sparql_endpoint=ENDPOINT, version_poll_interval_s=0))
    with TestClient(app) as client:
        yield client


def test_search_names_and_synonyms(live: TestClient):
    rotenone = live.get("/v1/search?q=rotenone&types=chemical").json()["data"]
    assert rotenone[0]["id"] == "83-79-4" and rotenone[0]["score"] == 100
    synonym = live.get("/v1/search?q=tubatoxin").json()["data"]
    assert synonym and synonym[0]["id"] == "83-79-4"


def test_search_mixed_types(live: TestClient):
    body = live.get("/v1/search?q=liver%20fibrosis&limit=50").json()
    types = {hit["type"] for hit in body["data"]}
    assert {"aop", "key_event"} <= types
    assert body["meta"]["total"] >= 2


def test_search_identifiers(live: TestClient):
    assert live.get("/v1/search?q=AOP%2037").json()["data"][0] == {
        "type": "aop",
        "id": 37,
        "title": live.get("/v1/aops/37").json()["data"]["title"],
        "matched": None,
        "score": 100,
        "path": "/v1/aops/37",
    }
    assert live.get("/v1/search?q=AHR&types=gene").json()["data"][0]["id"] == 348
