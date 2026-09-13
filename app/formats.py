"""Content negotiation, CSV serialisation, pagination links and HTTP caching headers."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from fastapi import Query, Request
from fastapi.responses import Response

from app.data import DataService
from app.errors import ApiError

CACHE_CONTROL = "public, max-age=3600, stale-while-revalidate=86400"
MEDIA_TYPES = {"json": "application/json", "csv": "text/csv; charset=utf-8"}
_JSON_RANGES = {
    "application/json",
    "application/problem+json",
    "application/*",
    "*/*",
    "text/html",
    "application/xhtml+xml",
}
_CSV_RANGES = {"text/csv", "text/*"}


def negotiate(request: Request, fmt: str | None) -> str:
    """`?format=` wins; otherwise the highest-q Accept range we can serve."""
    if fmt is not None:
        if fmt not in MEDIA_TYPES:
            raise ApiError(
                400,
                "Invalid request parameters",
                errors=[{"param": "format", "msg": f"must be one of {', '.join(MEDIA_TYPES)}"}],
            )
        return fmt

    header = request.headers.get("accept")
    if not header:
        return "json"
    ranges: list[tuple[float, int, str]] = []
    for index, part in enumerate(header.split(",")):
        pieces = [p.strip() for p in part.split(";")]
        quality = 1.0
        for piece in pieces[1:]:
            if piece.startswith("q="):
                try:
                    quality = float(piece[2:])
                except ValueError:
                    quality = 0.0
        if pieces[0] and quality > 0:
            ranges.append((-quality, index, pieces[0].lower()))
    for _q, _i, media in sorted(ranges):
        if media in _CSV_RANGES:
            return "csv"
        if media in _JSON_RANGES:
            return "json"
    raise ApiError(406, "Not Acceptable", "Supported media types: application/json, text/csv")


def format_query(
    format: str | None = Query(
        None, description="Response format; overrides the Accept header.", pattern="^(json|csv)$"
    ),
) -> str | None:
    return format


@dataclass(frozen=True)
class PageParams:
    limit: int
    offset: int


def page_params(
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of items to return."),
    offset: int = Query(0, ge=0, le=1_000_000, description="Number of items to skip."),
) -> PageParams:
    return PageParams(limit=limit, offset=offset)


def public_url(request: Request, **overrides: Any) -> str:
    """The request URL as the client sees it (including a proxy prefix such as /api)."""
    root = request.scope.get("root_path", "").rstrip("/")
    path = request.url.path
    if root and not path.startswith(root + "/") and path != root:
        path = root + path
    params = dict(request.query_params)
    for key, value in overrides.items():
        if value is None:
            params.pop(key, None)
        else:
            params[key] = str(value)
    return str(request.url.replace(path=path, query=urlencode(params)))


def page_links(request: Request, page: PageParams, total: int) -> dict[str, str | None]:
    return {
        "self": public_url(request),
        "next": public_url(request, offset=page.offset + page.limit)
        if page.offset + page.limit < total
        else None,
        "prev": public_url(request, offset=max(page.offset - page.limit, 0) or None)
        if page.offset > 0
        else None,
    }


def list_body(
    items: list[dict[str, Any]], page: PageParams, total: int, data: DataService, request: Request
) -> dict[str, Any]:
    return {
        "data": items,
        "meta": {
            "total": total,
            "limit": page.limit,
            "offset": page.offset,
            "dataset_version": data.token,
        },
        "links": page_links(request, page, total),
    }


def _flatten(obj: dict[str, Any], prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in obj.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(_flatten(value, f"{name}_"))
        elif isinstance(value, list):
            parts = []
            for item in value:
                if isinstance(item, dict):
                    parts.append(str(item.get("id", json.dumps(item, ensure_ascii=False))))
                else:
                    parts.append("" if item is None else str(item))
            out[name] = "|".join(parts)
        elif value is None:
            out[name] = ""
        elif isinstance(value, bool):
            out[name] = "true" if value else "false"
        else:
            out[name] = str(value)
    return out


def to_csv(items: list[dict[str, Any]]) -> str:
    rows = [_flatten(item) for item in items]
    columns: dict[str, None] = {}
    for row in rows:
        columns.update(dict.fromkeys(row))
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(columns), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def etag_for(request: Request, token: str, fmt: str) -> str:
    items = sorted(request.query_params.multi_items())
    digest = hashlib.sha1(f"{fmt}|{request.url.path}|{items}".encode()).hexdigest()[:16]
    return f'W/"{token}-{digest}"'


def _matches(if_none_match: str | None, etag: str) -> bool:
    if not if_none_match:
        return False
    if if_none_match.strip() == "*":
        return True
    wanted = etag.removeprefix("W/")
    return any(tag.strip().removeprefix("W/") == wanted for tag in if_none_match.split(","))


def respond(
    request: Request,
    data: DataService,
    *,
    fmt: str,
    body: dict[str, Any],
    csv_items: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> Response:
    """Serialise `body` (JSON) or `csv_items` (CSV, defaults to body["data"]) with cache headers."""
    token = data.token
    etag = etag_for(request, token, fmt)
    out_headers = {
        "ETag": etag,
        "Cache-Control": CACHE_CONTROL,
        "Vary": "Accept",
        "X-Dataset-Version": token,
    }
    if data.stale:
        out_headers["X-Dataset-State"] = "stale"
    if "meta" in body and isinstance(body["meta"], dict) and "total" in body["meta"]:
        out_headers["X-Total-Count"] = str(body["meta"]["total"])
    links = body.get("links") or {}
    link_values = [f'<{url}>; rel="{rel}"' for rel, url in links.items() if url and rel != "self"]
    if link_values:
        out_headers["Link"] = ", ".join(link_values)
    out_headers.update(headers or {})

    if _matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=out_headers)

    if fmt == "csv":
        items = csv_items if csv_items is not None else body.get("data", [])
        if isinstance(items, dict):
            items = [items]
        return Response(to_csv(items), media_type=MEDIA_TYPES["csv"], headers=out_headers)
    content = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    return Response(content, media_type=MEDIA_TYPES["json"], headers=out_headers)
