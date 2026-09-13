"""A fake Virtuoso that answers SPARQL requests by matching query fragments."""

from __future__ import annotations

import urllib.parse
from collections.abc import Callable
from typing import Any

import httpx

ENDPOINT = "http://virtuoso.test/sparql"

VERSION_ROW = {
    "version": "2026.09.12",
    "created": "2026-09-12",
    "commit": "https://github.com/marvinm2/AOPWikiRDF/commit/77db517ddc6bcc0e378dd667f358d3e4b1994d66",
}
VERSION_FRAGMENT = "pav:version ?version .\n  OPTIONAL"


def bindings(*rows: dict[str, Any]) -> dict[str, Any]:
    variables: list[str] = []
    for row in rows:
        for key in row:
            if key not in variables:
                variables.append(key)
    return {
        "head": {"vars": variables},
        "results": {
            "bindings": [
                {
                    key: {
                        "type": "uri"
                        if str(value).startswith(("http://", "https://"))
                        else "literal",
                        "value": str(value),
                    }
                    for key, value in row.items()
                    if value is not None
                }
                for row in rows
            ]
        },
    }


Responder = dict[str, Any] | httpx.Response | Callable[[str], httpx.Response]


class FakeVirtuoso:
    def __init__(self) -> None:
        self.routes: list[tuple[str, Responder]] = []
        self.queries: list[str] = []

    def add(self, fragment: str, response: Responder) -> None:
        """Later registrations win, so a test can override a default route."""
        self.routes.append((fragment, response))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        form = urllib.parse.parse_qs(request.content.decode())
        query = form["query"][0]
        self.queries.append(query)
        for fragment, response in reversed(self.routes):
            if fragment in query:
                if callable(response):
                    return response(query)
                if isinstance(response, httpx.Response):
                    return response
                return httpx.Response(200, json=response)
        return httpx.Response(400, text=f"Virtuoso 37000 Error SP030: no fake route for\n{query}")
