"""KER checks against the public endpoint (`pytest -m live`)."""

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


def test_ker_filters(live: TestClient):
    assert live.get("/v1/kers?limit=1").json()["meta"]["total"] >= 2300
    assert live.get("/v1/kers?aop=37").json()["meta"]["total"] == 7
    from_18 = live.get("/v1/kers?upstream=18").json()
    assert from_18["meta"]["total"] >= 20
    assert all(k["upstream"]["id"] == 18 for k in from_18["data"])
    assert live.get("/v1/kers?gene=AHR&limit=1").json()["meta"]["total"] >= 30


def test_ker_1229(live: TestClient):
    data = live.get("/v1/kers/1229").json()["data"]
    assert data["upstream"]["id"] == 227 and data["downstream"]["id"] == 1170
    assert 37 in data["aop_ids"]
    assert data["evidence"]["biological_plausibility"]
    assert data["quantitative_understanding"]["time_scale"]
