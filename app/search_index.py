"""In-memory name index behind /v1/search.

Built from five small SPARQL queries (about 8,000 texts) the first time it is used after each
dataset release, then searched in Python: exact > prefix > word start > substring, plus direct hits
for identifiers such as `AOP 37`, `KE 18`, `KER 1229`, CAS numbers and HGNC ids.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from dataclasses import dataclass, field
from typing import Any

from app import ids
from app.data import DataService
from app.routers.common import clean, local_id

TYPES = ("aop", "key_event", "ker", "stressor", "chemical", "gene")
COLLECTIONS = {
    "aop": "aops",
    "key_event": "key-events",
    "ker": "kers",
    "stressor": "stressors",
    "chemical": "chemicals",
    "gene": "genes",
}
SOURCES = {
    "aop": "search/aops",
    "key_event": "search/key_events",
    "stressor": "search/stressors",
    "chemical": "search/chemicals",
    "gene": "search/genes",
}
TYPE_ORDER = {t: i for i, t in enumerate(TYPES)}
ALIAS_SEPARATOR = "|||"

EXACT, ID_HIT, PREFIX, WORD, SUBSTRING = 100, 90, 80, 60, 40

_PREFIXED_ID = re.compile(
    r"^(aop|ke|key\s*event|ker|relationship|stressor)\s*[:#_-]?\s*([1-9]\d{0,5})$", re.I
)
_PREFIX_KIND = {
    "aop": "aop",
    "ke": "key_event",
    "keyevent": "key_event",
    "ker": "ker",
    "relationship": "ker",
    "stressor": "stressor",
}


@dataclass
class Entry:
    type: str
    id: int | str
    title: str | None = None
    texts: list[str] = field(default_factory=list)
    lowered: list[str] = field(default_factory=list)

    def add(self, text: str, is_title: bool) -> None:
        if is_title and self.title is None:
            self.title = text
        lower = text.lower()
        if lower not in self.lowered:
            self.texts.append(text)
            self.lowered.append(lower)


def _entity_id(type_: str, iri: str) -> int | str | None:
    if type_ == "aop":
        return ids.id_from_iri(ids.AOP, iri)
    if type_ == "key_event":
        return ids.id_from_iri(ids.KEY_EVENT, iri)
    if type_ == "stressor":
        return ids.id_from_iri(ids.STRESSOR, iri)
    if type_ == "chemical":
        return local_id(iri, "cas")
    hgnc = local_id(iri, "hgnc")
    return int(hgnc) if hgnc and hgnc.isdigit() else None


class SearchIndex:
    def __init__(self) -> None:
        self.token: str | None = None
        self.entries: dict[tuple[str, int | str], Entry] = {}
        self._lock = asyncio.Lock()

    async def ensure(self, data: DataService) -> None:
        token = data.token
        if self.token == token:
            return
        async with self._lock:
            if self.token == token:
                return
            names = list(SOURCES)
            results = await asyncio.gather(*(data.select(SOURCES[n]) for n in names))
            entries: dict[tuple[str, int | str], Entry] = {}
            for type_, rows in zip(names, results, strict=True):
                for row in rows:
                    entity_id = _entity_id(type_, row["entity"])
                    text = clean(row.get("text"))
                    if entity_id is None or text is None:
                        continue
                    entry = entries.setdefault((type_, entity_id), Entry(type_, entity_id))
                    entry.add(text, row.get("kind", "title") == "title")
                    for alias in (row.get("aliases") or "").split(ALIAS_SEPARATOR):
                        if alias := clean(alias):
                            entry.add(alias, False)
            self.entries = entries
            self.token = token

    def _id_hits(self, query: str) -> dict[tuple[str, int | str], tuple[int, str | None]]:
        hits: dict[tuple[str, int | str], tuple[int, str | None]] = {}
        compact = query.strip()
        if m := _PREFIXED_ID.match(compact):
            kind = _PREFIX_KIND[re.sub(r"\s+", "", m.group(1).lower())]
            hits[(kind, int(m.group(2)))] = (EXACT, None)
        elif compact.isdigit():
            for kind in ("aop", "key_event", "stressor"):
                if (kind, int(compact)) in self.entries:
                    hits[(kind, int(compact))] = (ID_HIT, None)
        with contextlib.suppress(ids.InvalidIdentifier):
            hits[("chemical", ids.parse_cas(compact))] = (EXACT, None)
        if compact.lower().startswith("hgnc:") and compact[5:].isdigit():
            hits[("gene", int(compact[5:]))] = (EXACT, None)
        return hits

    def search(self, query: str, types: set[str], limit: int) -> tuple[list[dict[str, Any]], int]:
        needle = " ".join(query.lower().split())
        word = re.compile(rf"(?<![0-9a-z]){re.escape(needle)}")
        scored: dict[tuple[str, int | str], tuple[int, str | None]] = {}

        for key, (score, matched) in self._id_hits(query).items():
            if key[0] in types and (key[0] == "ker" or key in self.entries):
                scored[key] = (score, matched)

        for key, entry in self.entries.items():
            if entry.type not in types:
                continue
            best, matched = scored.get(key, (0, None))
            for text, lower in zip(entry.texts, entry.lowered, strict=True):
                if lower == needle:
                    score = EXACT
                elif lower.startswith(needle):
                    score = PREFIX
                elif word.search(lower):
                    score = WORD
                elif needle in lower:
                    score = SUBSTRING
                else:
                    continue
                if score > best:
                    best, matched = score, text
            if best:
                scored[key] = (best, matched)

        def sort_key(item: tuple[tuple[str, int | str], tuple[int, str | None]]) -> tuple:
            (type_, entity_id), (score, _) = item
            entry = self.entries.get((type_, entity_id))
            title = entry.title if entry else None
            return (-score, len(title or ""), TYPE_ORDER[type_], str(entity_id))

        ranked = sorted(scored.items(), key=sort_key)
        results = []
        for (type_, entity_id), (score, matched) in ranked[:limit]:
            entry = self.entries.get((type_, entity_id))
            results.append(
                {
                    "type": type_,
                    "id": entity_id,
                    "title": entry.title if entry else None,
                    "matched": matched,
                    "score": score,
                    "path": f"/v1/{COLLECTIONS[type_]}/{entity_id}",
                }
            )
        return results, len(ranked)
