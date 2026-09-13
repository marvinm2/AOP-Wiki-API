"""Async SPARQL client for the AOP-Wiki Virtuoso endpoint."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass

import httpx

from app.config import Settings

JSON_RESULTS = "application/sparql-results+json"


class SparqlError(Exception):
    """Base class; `status` is the HTTP status the API should answer with."""

    status = 502

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class SparqlUnavailable(SparqlError):
    status = 503


class SparqlTimeout(SparqlError):
    status = 504


class SparqlTruncated(SparqlError):
    status = 502


Row = dict[str, str]


@dataclass(frozen=True)
class RawResult:
    content_type: str
    body: bytes


class SparqlClient:
    def __init__(
        self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(
                settings.sparql_timeout_s, connect=settings.sparql_connect_timeout_s
            ),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            headers={"User-Agent": "aop-wiki-api"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _post(
        self, query: str, accept: str, *, federated: bool, timeout: float | None = None
    ) -> httpx.Response:
        if timeout is None:
            timeout = (
                self.settings.federated_timeout_s if federated else self.settings.sparql_timeout_s
            )
        try:
            response = await self._client.post(
                self.settings.sparql_endpoint,
                data={"query": query},
                headers={"Accept": accept},
                timeout=httpx.Timeout(timeout, connect=self.settings.sparql_connect_timeout_s),
            )
        except httpx.TimeoutException as exc:
            raise SparqlTimeout(f"SPARQL endpoint timed out after {timeout:g}s") from exc
        except httpx.TransportError as exc:
            raise SparqlUnavailable(
                f"SPARQL endpoint unreachable: {exc.__class__.__name__}"
            ) from exc
        if response.status_code >= 500 and response.status_code != 500:
            # 502/503/504 from a proxy or a restarting Virtuoso
            raise SparqlUnavailable(f"SPARQL endpoint returned HTTP {response.status_code}")
        if response.status_code != 200:
            # Virtuoso reports query errors as 400/500 with a plain-text message.
            raise SparqlError(response.text.strip()[:500] or f"HTTP {response.status_code}")
        return response

    def _guard(self, rows: int) -> None:
        if rows >= self.settings.virtuoso_row_cap:
            raise SparqlTruncated(
                f"result reached the endpoint row cap ({self.settings.virtuoso_row_cap}) "
                "and is probably truncated"
            )

    async def select(self, query: str, *, federated: bool = False) -> list[Row]:
        """Run a SELECT query; each row maps variable name to the string value of its binding."""
        response = await self._post(query, JSON_RESULTS, federated=federated)
        try:
            bindings = response.json()["results"]["bindings"]
        except (ValueError, KeyError) as exc:
            raise SparqlError("unparseable SPARQL JSON response") from exc
        self._guard(len(bindings))
        return [{var: b["value"] for var, b in row.items()} for row in bindings]

    async def ask(self, query: str, *, timeout: float | None = None) -> bool:
        response = await self._post(query, JSON_RESULTS, federated=False, timeout=timeout)
        try:
            return bool(response.json()["boolean"])
        except (ValueError, KeyError) as exc:
            raise SparqlError("unparseable SPARQL ASK response") from exc

    async def select_raw(self, query: str, accept: str, *, federated: bool = False) -> RawResult:
        """Run a SELECT query and return the endpoint's serialisation untouched (compat layer)."""
        response = await self._post(query, accept, federated=federated)
        body = response.content
        self._guard(count_raw_rows(response.headers.get("Content-Type", accept), body))
        return RawResult(response.headers.get("Content-Type", accept), body)


def count_raw_rows(content_type: str, body: bytes) -> int:
    if "json" in content_type:
        try:
            return len(json.loads(body)["results"]["bindings"])
        except (ValueError, KeyError):
            return 0
    if "csv" in content_type:
        return max(sum(1 for _ in csv.reader(io.StringIO(body.decode("utf-8", "replace")))) - 1, 0)
    return 0
