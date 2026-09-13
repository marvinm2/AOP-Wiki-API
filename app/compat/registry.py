"""The 23 grlc queries of github.com/marvinm2/AOPWikiQueries, mapped to fixed templates.

URL parameter names are the grlc ones (SPARQL variable `?_MIEfilter_integer` became `MIEfilter`),
matched case-insensitively. Defaults are the `#+ defaults:` values of the original decorators.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from app import ids
from app.sparql.terms import Int, IriList, Lit, Term

MAX_LIST = 50


@dataclass(frozen=True)
class CompatParam:
    name: str
    placeholder: str
    kind: str  # ke | aop | aop_with_number | aop_list | cas | chebi | text
    default: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompatQuery:
    name: str
    template: str
    successor: str
    params: tuple[CompatParam, ...] = ()
    federated: bool = False


def parse(param: CompatParam, raw: str) -> tuple[dict[str, Term], str]:
    """Typed terms for the template and a normalised value for the successor link."""
    value = raw.strip()
    if param.kind == "ke":
        number = ids.parse_entity_id(ids.KEY_EVENT, value)
        return {param.placeholder: ids.entity_iri(ids.KEY_EVENT, number)}, str(number)
    if param.kind in ("aop", "aop_with_number"):
        number = ids.parse_entity_id(ids.AOP, value)
        terms: dict[str, Term] = {param.placeholder: ids.entity_iri(ids.AOP, number)}
        if param.kind == "aop_with_number":
            terms[f"{param.placeholder}_number"] = Int(number)
        return terms, str(number)
    if param.kind == "aop_list":
        parts = [p.strip() for p in value.split(",") if p.strip()]
        if not parts or len(parts) > MAX_LIST:
            raise ValueError(f"give between 1 and {MAX_LIST} AOPs")
        numbers = list(dict.fromkeys(ids.parse_entity_id(ids.AOP, p) for p in parts))
        iris = IriList(tuple(ids.entity_iri(ids.AOP, n) for n in numbers))
        return {param.placeholder: iris}, ",".join(str(n) for n in numbers)
    if param.kind == "cas":
        cas = ids.parse_cas(value)
        return {param.placeholder: ids.cas_iri(cas)}, cas
    if param.kind == "chebi":
        chebi = ids.parse_chebi(value)
        return {param.placeholder: Lit(chebi)}, chebi
    if param.kind == "text":
        text = " ".join(value.split()).lower()
        if not text:
            raise ValueError("must not be empty")
        return {param.placeholder: Lit(text)}, text
    raise ValueError(f"unknown compat parameter kind {param.kind!r}")


def successor_path(query: CompatQuery, normalised: dict[str, str]) -> str:
    return query.successor.format(**{k: quote(v, safe=",") for k, v in normalised.items()})


def _p(name: str, placeholder: str, kind: str, default: str, *aliases: str) -> CompatParam:
    return CompatParam(name, placeholder, kind, default, aliases)


QUERIES: dict[str, CompatQuery] = {
    q.name: q
    for q in (
        CompatQuery("get-all-aops", "compat/get_all_aops", "/v1/aops"),
        CompatQuery("get-all-aos", "compat/get_all_aos", "/v1/aos"),
        CompatQuery("get-all-chemicals", "compat/get_all_chemicals", "/v1/chemicals"),
        CompatQuery("get-all-kers", "compat/get_all_kers", "/v1/kers"),
        CompatQuery("get-all-kes", "compat/get_all_kes", "/v1/key-events"),
        CompatQuery("get-all-mies", "compat/get_all_mies", "/v1/mies"),
        CompatQuery(
            "get-ao-for-mie",
            "compat/get_ao_for_mie",
            "/v1/key-events/{MIEfilter}/adverse-outcomes",
            (_p("MIEfilter", "mie", "ke", "18"),),
        ),
        CompatQuery(
            "get-aop-for-ao (literal)",
            "compat/get_aop_for_ao_literal",
            "/v1/search?types=key_event&q={AOfilter}",
            (_p("AOfilter", "text", "text", "341"),),
        ),
        CompatQuery(
            "get-aop-for-chebi",
            "compat/get_aop_for_chebi",
            "/v1/chemicals?chebi={ChEBIfilter}",
            (_p("ChEBIfilter", "chebi", "chebi", "16605"),),
        ),
        CompatQuery(
            "get-aop-for-chemical",
            "compat/get_aop_for_chemical",
            "/v1/chemicals/{CASfilter}/aops",
            (_p("CASfilter", "chemical", "cas", "107-18-6"),),
        ),
        CompatQuery(
            "get-chemicals-for-ao (id)",
            "compat/get_chemicals_for_ao_id",
            "/v1/key-events/{aopfilter}/chemicals",
            (_p("aopfilter", "ao", "ke", "341", "aofilter"),),
        ),
        CompatQuery(
            "get-chemicals-for-ao (literal)",
            "compat/get_chemicals_for_ao_literal",
            "/v1/search?types=key_event&q={KEfilter}",
            (_p("KEfilter", "text", "text", "fibrosis"),),
        ),
        CompatQuery(
            "get-chemicals-for-aop",
            "compat/get_chemicals_for_aop",
            "/v1/aops/{aopfilter}/chemicals",
            (_p("aopfilter", "aop", "aop", "37"),),
        ),
        CompatQuery(
            "get-chemicals-from-any-key-event",
            "compat/get_chemicals_from_any_key_event",
            "/v1/key-events/{KEfilter}/chemicals",
            (_p("KEfilter", "ke", "ke", "341"),),
        ),
        CompatQuery(
            "get-keyevents-from-chemical",
            "compat/get_keyevents_from_chemical",
            "/v1/chemicals/{CASfilter}/key-events",
            (_p("CASfilter", "chemical", "cas", "107-18-6"),),
        ),
        CompatQuery(
            "get-matching-identifiers-for-chemical",
            "compat/get_matching_identifiers_for_chemical",
            "/v1/chemicals/{casfilter}",
            (_p("casfilter", "chemical", "cas", "http://identifiers.org/cas/107-18-6"),),
        ),
        CompatQuery(
            "get-methods-for-aop-simple",
            "compat/get_methods_for_aop_simple",
            "/v1/methods?aop={aopfilter}",
            (_p("aopfilter", "aop", "aop_with_number", "3"),),
        ),
        CompatQuery(
            "get-methods-for-aop",
            "compat/get_methods_for_aop",
            "/v1/methods?aop={aopfilter}",
            (_p("aopfilter", "aop", "aop", "http://identifiers.org/aop/3"),),
        ),
        CompatQuery(
            "get-methods-for-multiple-aops",
            "compat/get_methods_for_multiple_aops",
            "/v1/methods?aop={aopfilter}",
            (_p("aopfilter", "aops", "aop_list", "http://identifiers.org/aop/3"),),
        ),
        CompatQuery(
            "get-mie-for-ao",
            "compat/get_mie_for_ao",
            "/v1/key-events/{AOfilter}/molecular-initiating-events",
            (_p("AOfilter", "ao", "ke", "341"),),
        ),
        CompatQuery(
            "get-pathways-for-chemicals",
            "compat/get_pathways_for_chemicals",
            "/v1/search?types=chemical&q={Chemfilter}",
            (_p("Chemfilter", "text", "text", "rotenone", "KEfilter"),),
            federated=True,
        ),
        CompatQuery(
            "get-stressors-for-ao (ID)",
            "compat/get_stressors_for_ao_id",
            "/v1/key-events/{aofilter}/stressors",
            (_p("aofilter", "ao", "ke", "344"),),
        ),
        CompatQuery(
            "get-stressors-for-ao (literal)",
            "compat/get_stressors_for_ao_literal",
            "/v1/search?types=key_event&q={AOfilter}",
            (_p("AOfilter", "text", "text", "341"),),
        ),
    )
}
