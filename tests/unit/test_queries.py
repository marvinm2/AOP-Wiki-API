"""Every shipped query template must render and parse as SPARQL 1.1."""

import pytest
from rdflib.plugins.sparql.parser import parseQuery

from app.config import QUERIES_DIR
from app.sparql.loader import QueryLoader
from app.sparql.terms import Int, Iri, IriList, Lit, LitList

SAMPLES = {
    "int": Int(1),
    "literal": Lit("sample"),
    "iri": Iri("https://identifiers.org/aop/1"),
    "iri_list": IriList(
        (Iri("https://identifiers.org/aop/1"), Iri("https://identifiers.org/aop/2"))
    ),
    "literal_list": LitList((Lit("a"), Lit("b"))),
}

LOADER = QueryLoader(QUERIES_DIR, "http://aopwiki.org/")


@pytest.mark.parametrize("name", LOADER.names())
def test_template_renders_and_parses(name):
    template = LOADER.get(name)
    required = {n: SAMPLES[s.type] for n, s in template.params.items() if not s.optional}
    everything = {n: SAMPLES[s.type] for n, s in template.params.items()}
    for terms, flags in ((required, ()), (everything, template.flags)):
        query = template.render("http://aopwiki.org/", flags, **terms)
        assert "?__" not in query
        assert "urn:aopwiki:graph" not in query
        parseQuery(query)


def test_there_are_templates():
    assert "meta/version" in LOADER.names()
