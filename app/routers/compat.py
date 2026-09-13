"""Legacy grlc URLs: `/api-git/marvinm2/AOPWikiQueries/<query>`.

The fixed queries run against the same endpoint and their SPARQL results are passed through as
grlc did (SPARQL JSON as application/json, or CSV), with `Deprecation` and successor `Link` headers.
"""

from __future__ import annotations

import hashlib
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import RedirectResponse, Response

from app.compat.registry import QUERIES, parse, successor_path
from app.data import DataService
from app.deps import get_data
from app.errors import ApiError
from app.formats import CACHE_CONTROL
from app.ids import InvalidIdentifier
from app.sparql.client import JSON_RESULTS
from app.sparql.terms import Term, TermError

router = APIRouter(tags=["Legacy grlc API"])

BASE = "/api-git/marvinm2/AOPWikiQueries"
SPEC_NAMES = {"swagger", "spec", "api-docs", "swagger.json", "openapi.json"}

# requested format -> (Accept sent to Virtuoso, Content-Type returned, as grlc did)
FORMATS = {
    "json": (JSON_RESULTS, "application/json"),
    "csv": ("text/csv", "text/csv; charset=UTF-8"),
    "xml": ("application/sparql-results+xml", "application/sparql-results+xml; charset=UTF-8"),
}


def _prefix(request: Request) -> str:
    return request.scope.get("root_path", "").rstrip("/")


def _redirect(request: Request, target: str) -> RedirectResponse:
    return RedirectResponse(f"{_prefix(request)}{target}", status_code=308)


@router.get(BASE, include_in_schema=False)
@router.get(f"{BASE}/", include_in_schema=False)
@router.get("/api/marvinm2/AOPWikiQueries", include_in_schema=False)
@router.get("/api/marvinm2/AOPWikiQueries/", include_in_schema=False)
async def legacy_docs(request: Request) -> RedirectResponse:
    return _redirect(request, "/docs")


def _format(request: Request) -> str:
    accept = request.headers.get("accept", "").lower()
    if "text/csv" in accept:
        return "csv"
    if "sparql-results+xml" in accept:
        return "xml"
    return "json"


def _etag(request: Request, token: str, fmt: str) -> str:
    items = sorted((k.lower(), v) for k, v in request.query_params.multi_items())
    digest = hashlib.sha1(f"{fmt}|{request.url.path}|{items}".encode()).hexdigest()[:16]
    return f'W/"{token}-{digest}"'


@router.get(
    f"{BASE}/{{name:path}}",
    summary="Deprecated: legacy grlc query endpoint",
    description=(
        "Answers the URLs of the retired grlc API with the same result columns, as SPARQL JSON "
        "(`Accept: application/json`) or CSV (`Accept: text/csv`). Known queries: "
        + ", ".join(f"`{name}`" for name in QUERIES)
        + ". Each response links to the replacement endpoint in its `Link` header."
    ),
    deprecated=True,
    responses={200: {"content": {"application/json": {}, "text/csv": {}}}, 404: {}},
)
async def legacy_query(
    request: Request,
    name: str = Path(description="grlc query name, e.g. `get-all-aops`"),
    data: DataService = Depends(get_data),
) -> Response:
    path = unquote(name).strip("/")
    parts = path.split("/")
    if len(parts) >= 3 and parts[0] == "commit":
        path = "/".join(parts[2:])
    if path in SPEC_NAMES:
        return _redirect(request, "/openapi.json")
    query = QUERIES.get(path)
    if query is None:
        raise ApiError(404, "Not Found", f"no legacy query named {path!r}")

    supplied = {key.lower(): value for key, value in request.query_params.items()}
    terms: dict[str, Term] = {}
    normalised: dict[str, str] = {}
    for param in query.params:
        raw = next(
            (supplied[n.lower()] for n in (param.name, *param.aliases) if n.lower() in supplied),
            param.default,
        )
        try:
            param_terms, value = parse(param, raw)
        except (InvalidIdentifier, TermError, ValueError) as exc:
            raise ApiError(
                400, "Invalid request parameters", errors=[{"param": param.name, "msg": str(exc)}]
            ) from exc
        terms.update(param_terms)
        normalised[param.name] = value

    fmt = _format(request)
    accept, media_type = FORMATS[fmt]
    token = data.token
    etag = _etag(request, token, fmt)
    headers = {
        "ETag": etag,
        "Cache-Control": CACHE_CONTROL,
        "Vary": "Accept",
        "X-Dataset-Version": token,
        "Deprecation": "true",
        "Link": f'<{_prefix(request)}{successor_path(query, normalised)}>; rel="successor-version"',
    }
    if data.stale:
        headers["X-Dataset-State"] = "stale"
    if_none_match = request.headers.get("if-none-match", "")
    if etag.removeprefix("W/") in {t.strip().removeprefix("W/") for t in if_none_match.split(",")}:
        return Response(status_code=304, headers=headers)

    result = await data.select_raw(query.template, accept, federated=query.federated, **terms)
    return Response(result.body, media_type=media_type, headers=headers)
