"""Dataset state and cached query execution.

The dataset version token (from the VoID `pav:version` / `pav:createdWith` triples) is part of
every cache key, so a weekly reload invalidates everything at once. While the store is unreachable
or empty (Virtuoso restarting, or `RDF_GLOBAL_RESET` during a reload), cached answers keep being
served and flagged as stale; uncached queries fail with 503 instead of returning empty results.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Hashable, Iterable
from dataclasses import dataclass
from typing import Any

from cachetools import TTLCache

from app.config import Settings
from app.sparql.client import RawResult, Row, SparqlClient, SparqlError
from app.sparql.loader import QueryLoader
from app.sparql.terms import Iri, Term

log = logging.getLogger(__name__)

CACHE_TTL_S = 7 * 24 * 3600
UNAVAILABLE_POLL_S = 15.0


class DatasetUnavailable(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class DatasetVersion:
    version: str
    created_on: str | None = None
    commit: str | None = None

    @property
    def commit_short(self) -> str | None:
        return self.commit.rstrip("/").rsplit("/", 1)[-1][:7] if self.commit else None

    @property
    def token(self) -> str:
        return f"{self.version}-{self.commit_short}" if self.commit_short else self.version


class QueryCache:
    """TTL/LRU cache where concurrent misses on the same key share one computation."""

    def __init__(self, maxsize: int, ttl: float = CACHE_TTL_S) -> None:
        self._cache: TTLCache[Hashable, Any] = TTLCache(maxsize=maxsize, ttl=ttl)
        self._inflight: dict[Hashable, asyncio.Future[Any]] = {}

    def __len__(self) -> int:
        return len(self._cache)

    def clear(self) -> None:
        self._cache.clear()

    async def get(self, key: Hashable, compute: Callable[[], Awaitable[Any]]) -> tuple[Any, bool]:
        try:
            return self._cache[key], True
        except KeyError:
            pass
        if (pending := self._inflight.get(key)) is not None:
            return await asyncio.shield(pending), False

        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        try:
            value = await compute()
        except BaseException as exc:
            future.set_exception(exc)
            future.exception()  # mark as retrieved when nobody else is waiting
            raise
        else:
            self._cache[key] = value
            future.set_result(value)
            return value, False
        finally:
            self._inflight.pop(key, None)


def _terms_key(terms: dict[str, Term | None]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((name, term.n3()) for name, term in terms.items() if term is not None))


class DataService:
    def __init__(self, settings: Settings, client: SparqlClient, loader: QueryLoader) -> None:
        self.settings = settings
        self.client = client
        self.loader = loader
        self.cache = QueryCache(settings.cache_max_entries)
        self.version: DatasetVersion | None = None
        self.available = False
        self.last_error: str | None = "dataset version not loaded yet"
        self._listeners: list[Callable[[], Awaitable[None]]] = []

    @property
    def dataset_iri(self) -> Iri:
        return Iri(self.settings.dataset_iri)

    @property
    def token(self) -> str:
        if self.version is None:
            raise DatasetUnavailable(self.last_error or "dataset version unknown")
        return self.version.token

    @property
    def stale(self) -> bool:
        return not self.available

    def on_version_change(self, callback: Callable[[], Awaitable[None]]) -> None:
        self._listeners.append(callback)

    async def fetch_version(self) -> DatasetVersion | None:
        rows = await self.client.select(
            self.loader.render("meta/version", dataset=self.dataset_iri)
        )
        if not rows:
            return None
        row = rows[0]
        return DatasetVersion(row["version"], row.get("created"), row.get("commit"))

    def _mark_unavailable(self, detail: str) -> None:
        if self.available:
            log.warning("dataset unavailable: %s", detail)
        self.available = False
        self.last_error = detail

    async def refresh_version(self) -> bool:
        """Re-read the version token. Returns True when it changed (cache cleared)."""
        try:
            current = await self.fetch_version()
        except SparqlError as exc:
            self._mark_unavailable(exc.detail)
            return False
        if current is None:
            self._mark_unavailable("dataset version triple missing (store empty or reloading)")
            return False

        changed = self.version is None or current.token != self.version.token
        self.version = current
        self.available = True
        self.last_error = None
        if changed:
            log.info("dataset version %s: clearing cache", current.token)
            self.cache.clear()
            for callback in self._listeners:
                try:
                    await callback()
                except Exception:  # a failing warm-up must not stop the poller
                    log.exception("version-change callback failed")
        return changed

    async def poll_forever(self) -> None:
        while True:
            interval = self.settings.version_poll_interval_s
            await asyncio.sleep(interval if self.available else min(interval, UNAVAILABLE_POLL_S))
            await self.refresh_version()

    async def readiness(self, timeout: float = 2.0) -> tuple[bool, str | None]:
        try:
            present = await self.client.ask(
                self.loader.render("meta/ready", dataset=self.dataset_iri), timeout=timeout
            )
        except SparqlError as exc:
            return False, exc.detail
        if not present:
            return False, "dataset version triple missing (store empty or reloading)"
        if self.version is None or not self.available:
            await self.refresh_version()
        return self.available, self.last_error

    async def _confirm_available(self) -> None:
        """Called on empty results: make sure the store was not emptied since the last poll."""
        ok, detail = await self.readiness(timeout=self.settings.sparql_timeout_s)
        if not ok:
            self._mark_unavailable(detail or "dataset unavailable")
            raise DatasetUnavailable(self.last_error or "dataset unavailable")

    def _require_available(self) -> None:
        if not self.available:
            raise DatasetUnavailable(self.last_error or "dataset unavailable")

    async def select(
        self,
        name: str,
        *,
        federated: bool = False,
        flags: Iterable[str] = (),
        **terms: Term | None,
    ) -> list[Row]:
        active = tuple(sorted(flags))
        key = (self.token, "select", name, active, _terms_key(terms))

        async def compute() -> list[Row]:
            self._require_available()
            query = self.loader.render(name, active, **terms)
            rows = await self.client.select(query, federated=federated)
            if not rows:
                await self._confirm_available()
            return rows

        rows, _hit = await self.cache.get(key, compute)
        return rows

    async def select_raw(
        self, name: str, accept: str, *, federated: bool = False, **terms: Term | None
    ) -> RawResult:
        key = (self.token, "raw", accept, name, _terms_key(terms))

        async def compute() -> RawResult:
            self._require_available()
            return await self.client.select_raw(
                self.loader.render(name, **terms), accept, federated=federated
            )

        result, _hit = await self.cache.get(key, compute)
        return result
