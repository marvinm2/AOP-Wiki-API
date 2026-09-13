"""Compare the compatibility layer with the responses recorded from grlc (`pytest -m parity`).

Runs the compat endpoints against the public SPARQL endpoint with the parameters stored in
tests/fixtures/grlc/index.json. Only meaningful while the fixtures and the endpoint hold the same
dataset release; re-record with scripts/record_grlc_fixtures.py after a data reload.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

pytestmark = pytest.mark.parity

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "grlc"
ENDPOINT = os.environ.get(
    "LIVE_SPARQL_ENDPOINT", "https://aopwiki.rdf.bigcat-bioinformatics.org/sparql"
)

# How each query is expected to relate to grlc after its fix.
MODES = {
    "get-all-aos": "set",  # DISTINCT added
    "get-all-mies": "set",  # DISTINCT added
    "get-aop-for-chemical": "superset",  # AOPs without an MIE are kept
    "get-mie-for-ao": "superset",  # ?KE is now bound
    "get-methods-for-aop-simple": "fixed",  # grlc returned no rows
    "get-methods-for-aop": "fixed",
    "get-methods-for-multiple-aops": "fixed",
    "get-matching-identifiers-for-chemical": "fixed",
    "get-chemicals-from-any-key-event": "fixed",
    "get-stressors-for-ao (ID)": "fixed",
    "get-pathways-for-chemicals": "fixed",
    "get-aop-for-ao (literal)": "fixed",
    "get-stressors-for-ao (literal)": "fixed",
}


def _entries() -> list[dict]:
    index = json.loads((FIXTURES / "index.json").read_text())
    return [e for e in index["entries"] if e["format"] == "json" and e["status"] == 200]


def _rows(body: dict, variables: list[str]) -> set[tuple[str, ...]]:
    return {
        tuple(binding.get(v, {}).get("value", "") for v in variables)
        for binding in body["results"]["bindings"]
    }


@pytest.fixture(scope="module")
def live() -> Iterator[TestClient]:
    app = create_app(Settings(sparql_endpoint=ENDPOINT, version_poll_interval_s=0))
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("entry", _entries(), ids=lambda e: f"{e['query']} {e['params']}")
def test_parity(live: TestClient, entry: dict):
    url = urlsplit(entry["url"])
    path = url.path  # the compat layer serves the same paths as grlc
    response = live.get(
        f"{path}?{url.query}" if url.query else path, headers={"Accept": "application/json"}
    )
    assert response.status_code == 200, response.text
    ours = response.json()
    try:
        theirs = json.loads((FIXTURES / entry["file"]).read_text())
    except json.JSONDecodeError:
        theirs = None  # grlc returned an error page

    mode = MODES.get(entry["query"], "equal")
    if mode == "fixed" or theirs is None:
        if not theirs or not theirs["results"]["bindings"]:
            return  # grlc was broken for these parameters; covered by the live tests
        mode = "superset"

    shared = [v for v in theirs["head"]["vars"] if v in ours["head"]["vars"]]
    assert shared, "no common result columns"
    if mode == "equal":
        assert ours["head"]["vars"] == theirs["head"]["vars"]
    ours_rows, theirs_rows = _rows(ours, shared), _rows(theirs, shared)
    if mode in ("equal", "set"):
        assert ours_rows == theirs_rows
    else:
        missing = {row for row in theirs_rows if row not in ours_rows}
        # a bound ?KE column cannot match grlc's empty one; compare the other columns then
        if missing and "KE" in shared:
            idx = [i for i, v in enumerate(shared) if v != "KE"]
            ours_rows = {tuple(r[i] for i in idx) for r in ours_rows}
            missing = {tuple(r[i] for i in idx) for r in missing} - ours_rows
        assert not missing
