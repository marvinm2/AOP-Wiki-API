import pytest

from app.sparql.loader import QueryLoader, QueryTemplate, QueryTemplateError
from app.sparql.terms import Int, Iri, Lit

TEMPLATE = """\
# summary: List AOPs
# param: limit int
# param: status literal optional
PREFIX aopo: <http://aopkb.org/aop_ontology#>
SELECT ?aop FROM <urn:aopwiki:graph> WHERE {
  ?aop a aopo:AdverseOutcomePathway .
  # if: status
  ?aop <http://ncicb.nci.nih.gov/xml/owl/EVS/Thesaurus.owl#C25688> ?__status .
  # endif
} LIMIT ?__limit
"""


def test_render_with_and_without_optional_block():
    template = QueryTemplate.parse("aops/list", TEMPLATE)
    assert template.summary == "List AOPs"

    without = template.render("http://aopwiki.org/", limit=Int(5))
    assert "C25688" not in without
    assert "FROM <http://aopwiki.org/>" in without
    assert without.rstrip().endswith("LIMIT 5")
    assert "# param" not in without

    with_status = template.render("http://aopwiki.org/", limit=Int(5), status=Lit('Under "Review"'))
    assert 'C25688> "Under \\"Review\\"" .' in with_status


def test_render_rejects_missing_unknown_and_mistyped_terms():
    template = QueryTemplate.parse("aops/list", TEMPLATE)
    with pytest.raises(QueryTemplateError, match="missing"):
        template.render("http://aopwiki.org/")
    with pytest.raises(QueryTemplateError, match="unknown"):
        template.render("http://aopwiki.org/", limit=Int(5), other=Int(1))
    with pytest.raises(QueryTemplateError, match="must be int"):
        template.render("http://aopwiki.org/", limit=Lit("5"))


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("SELECT * WHERE { ?s ?p ?__x }", "undeclared"),
        ("# param: x int\nSELECT * WHERE { ?s ?p ?o }", "unused"),
        ("# param: x int\n# if: x\n?__x\n# endif", "optional"),
        ("# param: x int optional\nSELECT ?__x", "outside"),
        ("# param: x int optional\n# if: x\n?__x", "unterminated"),
        ("# param: x widget\n?__x", "unknown param type"),
    ],
)
def test_parse_rejects_malformed_templates(text, message):
    with pytest.raises(QueryTemplateError, match=message):
        QueryTemplate.parse("bad", text)


def test_flags_toggle_blocks():
    template = QueryTemplate.parse(
        "detail",
        "# param: aop iri\n# flag: evidence\nSELECT * WHERE {\n  { ?__aop ?p ?o }\n"
        "  # if: evidence\n  UNION { ?__aop <urn:evidence> ?o }\n  # endif\n}\n",
    )
    aop = Iri("https://identifiers.org/aop/1")
    assert "urn:evidence" not in template.render("http://g/", aop=aop)
    assert "urn:evidence" in template.render("http://g/", flags={"evidence"}, aop=aop)
    with pytest.raises(QueryTemplateError, match="unknown flags"):
        template.render("http://g/", flags={"other"}, aop=aop)


def test_flag_without_block_is_rejected():
    with pytest.raises(QueryTemplateError, match="flags without a block"):
        QueryTemplate.parse("bad", "# flag: x\nSELECT * WHERE { ?s ?p ?o }")


def test_includes_are_expanded(tmp_path):
    (tmp_path / "aops").mkdir()
    (tmp_path / "aops" / "_filters.rqi").write_text(
        "# param: status literal optional\n  # if: status\n  ?aop <urn:status> ?__status .\n"
        "  # endif\n"
    )
    (tmp_path / "aops" / "count.rq").write_text(
        "SELECT (COUNT(?aop) AS ?n) WHERE {\n  ?aop a <urn:Aop> .\n  # include: aops/_filters\n}\n"
    )
    loader = QueryLoader(tmp_path, "http://aopwiki.org/")
    assert loader.names() == ["aops/count"]  # partials are not templates
    assert "urn:status" not in loader.render("aops/count")
    assert '<urn:status> "WPHA" .' in loader.render("aops/count", status=Lit("WPHA"))


def test_missing_and_cyclic_includes(tmp_path):
    (tmp_path / "a.rq").write_text("# include: missing\nSELECT * WHERE { ?s ?p ?o }")
    with pytest.raises(QueryTemplateError, match="not found"):
        QueryLoader(tmp_path, "http://g/")
    (tmp_path / "a.rq").write_text("# include: loop\nSELECT * WHERE { ?s ?p ?o }")
    (tmp_path / "loop.rqi").write_text("# include: loop\n")
    with pytest.raises(QueryTemplateError, match="cycle"):
        QueryLoader(tmp_path, "http://g/")


def test_loader_names_templates_by_relative_path(tmp_path):
    (tmp_path / "aops").mkdir()
    (tmp_path / "aops" / "list.rq").write_text(TEMPLATE)
    loader = QueryLoader(tmp_path, "http://aopwiki.org/")
    assert loader.names() == ["aops/list"]
    assert "LIMIT 3" in loader.render("aops/list", limit=Int(3))
    with pytest.raises(QueryTemplateError):
        loader.get("aops/missing")
    assert Iri("urn:x")  # urn scheme is a valid IRI
