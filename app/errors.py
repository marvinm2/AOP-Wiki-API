"""RFC 9457 problem+json error responses."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.data import DatasetUnavailable
from app.ids import InvalidIdentifier
from app.sparql.client import SparqlError
from app.sparql.terms import TermError

log = logging.getLogger(__name__)

PROBLEM_JSON = "application/problem+json"


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        title: str,
        detail: str | None = None,
        *,
        errors: list[dict[str, str]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail or title)
        self.status = status
        self.title = title
        self.detail = detail
        self.errors = errors
        self.headers = headers


def problem(
    request: Request,
    status: int,
    title: str | None = None,
    detail: str | None = None,
    *,
    errors: list[dict[str, str]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": "about:blank",
        "title": title or HTTPStatus(status).phrase,
        "status": status,
        "instance": request.url.path,
    }
    if detail:
        body["detail"] = detail
    if errors:
        body["errors"] = errors
    return JSONResponse(
        body,
        status_code=status,
        media_type=PROBLEM_JSON,
        headers={"Cache-Control": "no-store", **(headers or {})},
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return problem(
            request, exc.status, exc.title, exc.detail, errors=exc.errors, headers=exc.headers
        )

    @app.exception_handler(InvalidIdentifier)
    async def _invalid_id(request: Request, exc: InvalidIdentifier) -> JSONResponse:
        return problem(request, 400, "Invalid identifier", str(exc))

    @app.exception_handler(TermError)
    async def _term_error(request: Request, exc: TermError) -> JSONResponse:
        return problem(request, 400, "Invalid parameter value", str(exc))

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"param": str(err["loc"][-1]) if err.get("loc") else "", "msg": err.get("msg", "")}
            for err in exc.errors()
        ]
        return problem(request, 400, "Invalid request parameters", errors=errors)

    @app.exception_handler(SparqlError)
    async def _sparql(request: Request, exc: SparqlError) -> JSONResponse:
        titles = {
            502: "SPARQL endpoint error",
            503: "SPARQL endpoint unavailable",
            504: "SPARQL endpoint timeout",
        }
        log.warning("SPARQL error on %s: %s", request.url.path, exc.detail)
        headers = {"Retry-After": "30"} if exc.status in (503, 504) else None
        return problem(request, exc.status, titles.get(exc.status), exc.detail, headers=headers)

    @app.exception_handler(DatasetUnavailable)
    async def _unavailable(request: Request, exc: DatasetUnavailable) -> JSONResponse:
        return problem(
            request, 503, "Dataset unavailable", exc.detail, headers={"Retry-After": "60"}
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else None
        if detail == HTTPStatus(exc.status_code).phrase:
            detail = None
        return problem(request, exc.status_code, detail=detail, headers=exc.headers)
