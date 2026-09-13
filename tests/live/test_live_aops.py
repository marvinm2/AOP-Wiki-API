"""Checks against the public AOP-Wiki SPARQL endpoint (`pytest -m live`).

Expected values come from the 2026-09 release; they use lower bounds where the data grows.
"""

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


def test_ready(live: TestClient):
    response = live.get("/health/ready")
    assert response.status_code == 200, response.text


def test_dataset_counts(live: TestClient):
    counts = live.get("/v1/dataset").json()["data"]["counts"]
    assert counts["aops"] >= 590
    assert counts["key_events"] >= 1600
    assert counts["kers"] >= 2300
    assert counts["chemicals"] >= 400


def test_aop_list_pages_and_totals(live: TestClient):
    body = live.get("/v1/aops?limit=50&offset=100").json()
    assert body["meta"]["total"] >= 590
    assert len(body["data"]) == 50
    ids = [item["id"] for item in body["data"]]
    assert ids == sorted(ids)
    last_page = live.get(f"/v1/aops?limit=1000&offset={body['meta']['total'] - 3}").json()
    assert len(last_page["data"]) == 3


def test_aop_filters(live: TestClient):
    endorsed = live.get("/v1/aops", params={"status": "WPHA/WNT Endorsed"}).json()
    assert endorsed["meta"]["total"] >= 40
    assert all(item["oecd_status"] == "WPHA/WNT Endorsed" for item in endorsed["data"])
    with_mie = live.get("/v1/aops?mie=18").json()
    assert with_mie["meta"]["total"] >= 10
    assert all(18 in item["mie_ids"] for item in with_mie["data"])
    liver = live.get("/v1/aops?q=liver").json()
    assert liver["meta"]["total"] >= 20


def test_aop_37(live: TestClient):
    data = live.get("/v1/aops/37?include=evidence").json()["data"]
    assert data["mie_ids"] == [227]
    assert {ke["id"]: ke["role"] for ke in data["key_events"]}[227] == "mie"
    assert len(data["key_event_relationships"]) >= 7
    assert {t["id"] for t in data["taxa"]} >= {10090, 10116}
    assert data["evidence"]["essentiality"]
    assert "&alpha;" not in (data["description"] or "")


def test_aop_37_sub_resources(live: TestClient):
    chemicals = live.get("/v1/aops/37/chemicals").json()["data"]
    assert {c["cas"] for c in chemicals} >= {"117-81-7", "25812-30-0"}
    assert live.get("/v1/aops/37/stressors").json()["meta"]["total"] >= 9
    genes = live.get("/v1/aops/37/genes").json()["data"]
    assert any(g["symbol"] == "PPARA" for g in genes)
    assert live.get("/v1/aops/999999/kers").status_code == 404


def test_methods_for_aop_3(live: TestClient):
    body = live.get("/v1/methods?aop=3").json()
    assert body["meta"]["total"] >= 5


def test_csv_export(live: TestClient):
    response = live.get("/v1/aops?limit=5&format=csv")
    assert response.headers["content-type"].startswith("text/csv")
    assert len(response.text.strip().splitlines()) == 6
