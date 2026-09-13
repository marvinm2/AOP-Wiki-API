from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.fakes import ENDPOINT, VERSION_FRAGMENT, VERSION_ROW, FakeVirtuoso, bindings


@pytest.fixture
def virtuoso() -> FakeVirtuoso:
    fake = FakeVirtuoso()
    fake.add(VERSION_FRAGMENT, bindings(VERSION_ROW))
    fake.add("ASK", {"head": {}, "boolean": True})
    return fake


@pytest.fixture
def settings() -> Settings:
    return Settings(sparql_endpoint=ENDPOINT, version_poll_interval_s=0)


@pytest.fixture
def client(virtuoso: FakeVirtuoso, settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings, transport=httpx.MockTransport(virtuoso))
    with TestClient(app) as test_client:
        yield test_client
