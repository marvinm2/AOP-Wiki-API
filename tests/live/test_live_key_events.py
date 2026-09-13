"""Key Event checks against the public endpoint (`pytest -m live`)."""

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


def test_role_lists(live: TestClient):
    assert 250 <= live.get("/v1/mies?limit=1").json()["meta"]["total"] <= 400
    assert 200 <= live.get("/v1/aos?limit=1").json()["meta"]["total"] <= 350
    intermediates = live.get("/v1/key-events?role=ke&limit=1").json()["meta"]["total"]
    assert intermediates >= 800


def test_key_event_filters(live: TestClient):
    liver = live.get("/v1/key-events?organ=UBERON:0002107&limit=1").json()["meta"]["total"]
    assert liver >= 30
    ahr = live.get("/v1/key-events?gene=ahr").json()
    assert ahr["meta"]["total"] >= 10
    assert any(item["id"] == 18 for item in ahr["data"])
    molecular = live.get("/v1/key-events?level=Molecular&limit=5").json()
    assert all(item["level"] == "Molecular" for item in molecular["data"])


def test_key_event_18(live: TestClient):
    data = live.get("/v1/key-events/18").json()["data"]
    assert data["title"] == "Activation, AhR"
    assert data["is_mie"] is True and len(data["aops"]) >= 20
    processes = {e["process"]["id"] for e in data["biological_events"] if e["process"]}
    assert "GO:0004874" in processes
    assert any(g["symbol"] == "AHR" for g in data["genes"])


def test_key_event_18_relations(live: TestClient):
    downstream = live.get("/v1/key-events/18/downstream").json()
    assert downstream["meta"]["total"] >= 20
    assert (
        live.get("/v1/key-events/18/downstream?depth=2").json()["meta"]["total"]
        > downstream["meta"]["total"]
    )
    outcomes = live.get("/v1/key-events/18/adverse-outcomes").json()["data"]
    assert len({o["ke_id"] for o in outcomes}) >= 5
    assert live.get("/v1/key-events/18/aops?role=mie").json()["meta"]["total"] >= 10


def test_key_event_341_chemicals_via_aops(live: TestClient):
    # grlc's get-chemicals-from-any-key-event returned nothing for this KE
    assert live.get("/v1/key-events/341/chemicals").json()["meta"]["total"] >= 1


def test_mies_for_ao_341(live: TestClient):
    mies = live.get("/v1/key-events/341/molecular-initiating-events").json()["data"]
    assert len({m["ke_id"] for m in mies}) >= 5
