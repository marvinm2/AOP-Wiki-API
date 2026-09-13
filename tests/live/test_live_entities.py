"""Stressor, chemical and gene checks against the public endpoint (`pytest -m live`)."""

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


def test_stressors(live: TestClient):
    assert live.get("/v1/stressors?limit=1").json()["meta"]["total"] >= 700
    with_chemical = live.get("/v1/stressors?has_chemical=true&limit=1").json()["meta"]["total"]
    assert 400 <= with_chemical < 700
    data = live.get("/v1/stressors/11").json()["data"]
    assert "117-81-7" in data["chemical_cas"]
    assert {a["id"] for a in data["aops"]} >= {37, 307}
    assert data["aop_ids"] == sorted(a["id"] for a in data["aops"])


def test_chemical_lookups(live: TestClient):
    assert live.get("/v1/chemicals?limit=1").json()["meta"]["total"] >= 400
    for params in (
        {"chebi": "CHEBI:28201"},
        {"inchikey": "JUVIOZPCNVVQFO-HBGVWJBISA-N"},
        {"wikidata": "Q412388"},
        {"hmdb": "HMDB34436"},
    ):
        data = live.get("/v1/chemicals", params=params).json()["data"]
        assert [c["cas"] for c in data] == ["83-79-4"], params
    # name search also matches synonyms of other chemicals
    by_name = live.get("/v1/chemicals", params={"q": "rotenone"}).json()["data"]
    assert "83-79-4" in {c["cas"] for c in by_name}


def test_rotenone(live: TestClient):
    data = live.get("/v1/chemicals/83-79-4").json()["data"]
    assert data["comptox_id"] == "DTXSID6021248"
    assert len(data["synonyms"]) >= 20
    assert data["xrefs"]["chebi"] == ["28201"]
    aops = live.get("/v1/chemicals/83-79-4/aops").json()["data"]
    assert {a["id"] for a in aops} >= {3}
    kes = live.get("/v1/chemicals/83-79-4/key-events?role=mie").json()["data"]
    assert kes


def test_rotenone_pathways_federated(live: TestClient):
    pathways = live.get("/v1/chemicals/83-79-4/pathways").json()["data"]
    assert len(pathways) >= 1
    assert all(p["wp_id"].startswith("WP") for p in pathways)


def test_genes(live: TestClient):
    total = live.get("/v1/genes?limit=1").json()["meta"]["total"]
    assert total >= 2500
    ner_only = live.get("/v1/genes?method=ner&limit=1").json()["meta"]["total"]
    assert ner_only < total
    ppar = live.get("/v1/genes?q=ppar").json()["data"]
    assert "PPARA" in {g["symbol"] for g in ppar}
    in_aop = live.get("/v1/genes?aop=37&limit=1000").json()["data"]
    assert "PPARA" in {g["symbol"] for g in in_aop}


def test_ahr(live: TestClient):
    data = live.get("/v1/genes/AHR").json()["data"]
    assert data["hgnc_id"] == 348
    assert "P35869" in data["xrefs"]["uniprot"]
    assert len(data["key_events"]) >= 10 and len(data["kers"]) >= 30
    assert len(data["aops"]) >= 30
    assert live.get("/v1/genes/HGNC:348").json()["data"]["symbol"] == "AHR"
