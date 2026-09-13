"""Load `.rq` query templates and render them with typed terms.

Template conventions (see `queries/README.md`):

- `# summary: <text>` describes the query.
- `# param: <name> <type> [optional]` declares a placeholder. Types: int, literal, iri,
  iri_list, literal_list. Placeholders are written `?__name` in the query body.
- `# flag: <name>` declares a boolean switch for `# if:` blocks that need no value.
- Lines between `# if: <name>` and `# endif` are kept only when the optional parameter is given
  or the flag is set.
- `# include: <name>` inlines the partial `<name>.rqi` (filters shared by list and count queries).
- `<urn:aopwiki:graph>` is replaced with the configured data graph.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from app.sparql.terms import Int, Iri, IriList, Lit, LitList, Term

GRAPH_TOKEN = "<urn:aopwiki:graph>"
PLACEHOLDER = re.compile(r"\?__([a-z][a-z0-9_]*)\b")
TERM_TYPES: dict[str, type[Term]] = {
    "int": Int,
    "literal": Lit,
    "iri": Iri,
    "iri_list": IriList,
    "literal_list": LitList,
}

_SUMMARY = re.compile(r"^\s*#\s*summary:\s*(.+?)\s*$")
_PARAM = re.compile(r"^\s*#\s*param:\s*([a-z][a-z0-9_]*)\s+([a-z_]+)(\s+optional)?\s*$")
_FLAG = re.compile(r"^\s*#\s*flag:\s*([a-z][a-z0-9_]*)\s*$")
_IF = re.compile(r"^\s*#\s*if:\s*([a-z][a-z0-9_]*)\s*$")
_ENDIF = re.compile(r"^\s*#\s*endif\s*$")
_INCLUDE = re.compile(r"^\s*#\s*include:\s*([a-z0-9_]+(?:/[a-z0-9_]+)*)\s*$")


class QueryTemplateError(ValueError):
    """A template is malformed, or was rendered with the wrong terms."""


@dataclass(frozen=True)
class ParamSpec:
    name: str
    type: str
    optional: bool


@dataclass(frozen=True)
class QueryTemplate:
    name: str
    text: str
    summary: str = ""
    params: dict[str, ParamSpec] = field(default_factory=dict)
    flags: frozenset[str] = frozenset()

    @classmethod
    def parse(cls, name: str, text: str) -> QueryTemplate:
        summary = ""
        params: dict[str, ParamSpec] = {}
        flags: set[str] = set()
        block: str | None = None
        used_outside: set[str] = set()
        used_inside: dict[str, set[str]] = {}

        for lineno, line in enumerate(text.splitlines(), start=1):
            if m := _SUMMARY.match(line):
                summary = summary or m.group(1)
                continue
            if m := _PARAM.match(line):
                spec = ParamSpec(m.group(1), m.group(2), bool(m.group(3)))
                if spec.type not in TERM_TYPES:
                    raise QueryTemplateError(f"{name}:{lineno}: unknown param type {spec.type!r}")
                if spec.name in params and params[spec.name] != spec:
                    raise QueryTemplateError(f"{name}:{lineno}: conflicting param {spec.name!r}")
                params[spec.name] = spec
                continue
            if m := _FLAG.match(line):
                flags.add(m.group(1))
                continue
            if m := _IF.match(line):
                if block is not None:
                    raise QueryTemplateError(f"{name}:{lineno}: nested '# if:' blocks")
                block = m.group(1)
                used_inside.setdefault(block, set())
                continue
            if _ENDIF.match(line):
                if block is None:
                    raise QueryTemplateError(f"{name}:{lineno}: '# endif' without '# if:'")
                block = None
                continue
            names = set(PLACEHOLDER.findall(line))
            if block is None:
                used_outside |= names
            else:
                used_inside[block] |= names

        if block is not None:
            raise QueryTemplateError(f"{name}: unterminated '# if: {block}' block")
        if clash := flags & params.keys():
            raise QueryTemplateError(f"{name}: names used as both flag and param {sorted(clash)}")

        used = used_outside.union(*used_inside.values()) if used_inside else used_outside
        undeclared = used - params.keys()
        if undeclared:
            raise QueryTemplateError(f"{name}: undeclared placeholders {sorted(undeclared)}")
        unused = params.keys() - used
        if unused:
            raise QueryTemplateError(f"{name}: declared but unused params {sorted(unused)}")
        for cond in used_inside:
            if cond in flags:
                continue
            spec = params.get(cond)
            if spec is None or not spec.optional:
                raise QueryTemplateError(
                    f"{name}: '# if: {cond}' needs an optional param or a flag"
                )
        if unused_flags := flags - used_inside.keys():
            raise QueryTemplateError(f"{name}: flags without a block {sorted(unused_flags)}")
        for spec in params.values():
            if spec.optional and spec.name in used_outside:
                raise QueryTemplateError(
                    f"{name}: optional param {spec.name!r} used outside its '# if:' block"
                )
            if spec.optional and spec.name not in used_inside:
                raise QueryTemplateError(f"{name}: optional param {spec.name!r} has no block")

        return cls(name=name, text=text, summary=summary, params=params, flags=frozenset(flags))

    def render(self, graph: str, flags: Iterable[str] = (), **terms: Term | None) -> str:
        active = frozenset(flags)
        if unknown_flags := active - self.flags:
            raise QueryTemplateError(f"{self.name}: unknown flags {sorted(unknown_flags)}")
        unknown = terms.keys() - self.params.keys()
        if unknown:
            raise QueryTemplateError(f"{self.name}: unknown params {sorted(unknown)}")
        for spec in self.params.values():
            term = terms.get(spec.name)
            if term is None:
                if not spec.optional:
                    raise QueryTemplateError(f"{self.name}: missing required param {spec.name!r}")
                continue
            if not isinstance(term, TERM_TYPES[spec.type]):
                raise QueryTemplateError(
                    f"{self.name}: param {spec.name!r} must be {spec.type}, "
                    f"got {type(term).__name__}"
                )

        out: list[str] = []
        keep = True
        for line in self.text.splitlines():
            if _SUMMARY.match(line) or _PARAM.match(line) or _FLAG.match(line):
                continue
            if m := _IF.match(line):
                cond = m.group(1)
                keep = cond in active if cond in self.flags else terms.get(cond) is not None
                continue
            if _ENDIF.match(line):
                keep = True
                continue
            if keep:
                out.append(line)

        body = "\n".join(out).strip() + "\n"
        body = PLACEHOLDER.sub(lambda m: terms[m.group(1)].n3(), body)  # type: ignore[union-attr]
        return body.replace(GRAPH_TOKEN, Iri(graph).n3())


class QueryLoader:
    """All templates under a directory, addressed as `<subdir>/<stem>` (e.g. `aops/list`)."""

    def __init__(self, root: Path, graph: str) -> None:
        self.root = root
        self.graph = graph
        self._templates: dict[str, QueryTemplate] = {}
        for path in sorted(root.rglob("*.rq")):
            name = path.relative_to(root).with_suffix("").as_posix()
            text = self._expand(path.read_text(encoding="utf-8"), (name,))
            self._templates[name] = QueryTemplate.parse(name, text)

    def _expand(self, text: str, stack: tuple[str, ...]) -> str:
        lines: list[str] = []
        for line in text.splitlines():
            m = _INCLUDE.match(line)
            if not m:
                lines.append(line)
                continue
            include = m.group(1)
            if include in stack:
                raise QueryTemplateError(f"{stack[0]}: include cycle via {include!r}")
            path = self.root / f"{include}.rqi"
            if not path.is_file():
                raise QueryTemplateError(f"{stack[0]}: include {include!r} not found")
            lines.append(self._expand(path.read_text(encoding="utf-8"), (*stack, include)))
        return "\n".join(lines)

    def names(self) -> list[str]:
        return list(self._templates)

    def get(self, name: str) -> QueryTemplate:
        try:
            return self._templates[name]
        except KeyError:
            raise QueryTemplateError(f"no query template named {name!r}") from None

    def render(self, name: str, flags: Iterable[str] = (), **terms: Term | None) -> str:
        return self.get(name).render(self.graph, flags, **terms)
