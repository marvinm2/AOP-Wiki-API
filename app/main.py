"""Application factory."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app import __version__
from app.config import Settings, get_settings
from app.data import DataService
from app.errors import install_error_handlers
from app.middleware import ForwardedPrefixMiddleware, TimingMiddleware
from app.routers import (
    aops,
    chemicals,
    compat,
    dataset,
    genes,
    health,
    kers,
    key_events,
    search,
    stressors,
)
from app.sparql.client import SparqlClient
from app.sparql.loader import QueryLoader

DESCRIPTION = """
REST access to the [AOP-Wiki RDF](https://github.com/marvinm2/AOPWikiRDF) data: Adverse Outcome
Pathways, Key Events, Key Event Relationships, stressors, chemicals and genes.

- Responses are JSON by default; send `Accept: text/csv` or `?format=csv` for CSV.
- Lists are paginated with `limit` and `offset`; totals are in `meta.total` and `X-Total-Count`.
- Every response carries the dataset release in `X-Dataset-Version`, and an `ETag` for
  conditional requests. The data is refreshed weekly.
- Legacy grlc URLs (`/api-git/marvinm2/AOPWikiQueries/...`) are still answered.

Data licence: CC BY-SA 4.0 (AOP-Wiki). Issues: https://github.com/marvinm2/AOP-Wiki-API/issues
"""


def create_app(
    settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None
) -> FastAPI:
    settings = settings or get_settings()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        client = SparqlClient(settings, transport=transport)
        loader = QueryLoader(settings.queries_dir, settings.data_graph)
        data = DataService(settings, client, loader)
        app.state.data = data
        await data.refresh_version()
        poller = (
            asyncio.create_task(data.poll_forever())
            if settings.version_poll_interval_s > 0
            else None
        )
        try:
            yield
        finally:
            if poller is not None:
                poller.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await poller
            await client.aclose()

    app = FastAPI(
        title="AOP-Wiki API",
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
        license_info={
            "name": "Data: CC BY-SA 4.0",
            "url": "https://creativecommons.org/licenses/by-sa/4.0/",
        },
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "HEAD", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["ETag", "Link", "X-Total-Count", "X-Dataset-Version", "X-Dataset-State"],
    )
    app.add_middleware(TimingMiddleware)
    app.add_middleware(ForwardedPrefixMiddleware)
    install_error_handlers(app)

    app.include_router(health.router)
    app.include_router(dataset.router)
    app.include_router(aops.router)
    app.include_router(key_events.router)
    app.include_router(kers.router)
    app.include_router(stressors.router)
    app.include_router(chemicals.router)
    app.include_router(genes.router)
    app.include_router(search.router)
    app.include_router(compat.router)

    @app.get("/", include_in_schema=False)
    async def root(request: Request) -> RedirectResponse:
        prefix = request.scope.get("root_path", "").rstrip("/")
        return RedirectResponse(f"{prefix}/docs", status_code=308)

    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app()
