"""Typed SPARQL terms.

User input only ever reaches a query through these classes. Each one validates its value on
construction and knows how to serialise itself safely, so query templates never concatenate raw
strings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_LITERAL_LENGTH = 200

# Characters that may not appear inside an IRIREF (SPARQL 1.1 grammar, production [139]).
_IRI_FORBIDDEN = re.compile(r'[\x00-\x20<>"{}|^`\\]')
# Control characters other than tab, newline and carriage return (those are escaped instead).
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


class TermError(ValueError):
    """Raised when a value cannot be turned into a safe SPARQL term."""


class Term:
    def n3(self) -> str:
        raise NotImplementedError


@dataclass(frozen=True)
class Iri(Term):
    value: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.value, str)
            or not _SCHEME.match(self.value)
            or _IRI_FORBIDDEN.search(self.value)
        ):
            raise TermError(f"invalid IRI: {self.value!r}")

    def n3(self) -> str:
        return f"<{self.value}>"


@dataclass(frozen=True)
class Lit(Term):
    value: str
    max_length: int = MAX_LITERAL_LENGTH

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise TermError("literal must be a string")
        if len(self.value) > self.max_length:
            raise TermError(f"literal longer than {self.max_length} characters")
        if _CONTROL.search(self.value):
            raise TermError("literal contains control characters")

    def n3(self) -> str:
        escaped = (
            self.value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )
        return f'"{escaped}"'


@dataclass(frozen=True)
class Int(Term):
    value: int

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or not isinstance(self.value, int) or self.value < 0:
            raise TermError(f"invalid non-negative integer: {self.value!r}")

    def n3(self) -> str:
        return str(self.value)


@dataclass(frozen=True)
class IriList(Term):
    values: tuple[Iri, ...]

    def __post_init__(self) -> None:
        if not self.values or not all(isinstance(v, Iri) for v in self.values):
            raise TermError("IRI list must contain at least one Iri")

    def n3(self) -> str:
        return " ".join(v.n3() for v in self.values)


@dataclass(frozen=True)
class LitList(Term):
    values: tuple[Lit, ...]

    def __post_init__(self) -> None:
        if not self.values or not all(isinstance(v, Lit) for v in self.values):
            raise TermError("literal list must contain at least one Lit")

    def n3(self) -> str:
        return " ".join(v.n3() for v in self.values)
