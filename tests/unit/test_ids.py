import pytest

from app import ids


@pytest.mark.parametrize(
    "raw",
    [
        37,
        "37",
        " 37 ",
        "AOP 37",
        "aop37",
        "aop:37",
        "AOP:37",
        "https://identifiers.org/aop/37",
        "http://identifiers.org/aop/37",
        "https://aopwiki.org/aops/37",
    ],
)
def test_aop_id_forms(raw):
    assert ids.parse_entity_id(ids.AOP, raw) == 37


@pytest.mark.parametrize(
    ("kind", "raw", "expected"),
    [
        (ids.KEY_EVENT, "KE 18", 18),
        (ids.KEY_EVENT, "Key Event 18", 18),
        (ids.KEY_EVENT, "aop.events:18", 18),
        (ids.KEY_EVENT, "https://identifiers.org/aop.events/18", 18),
        (ids.KER, "KER 2373", 2373),
        (ids.KER, "http://identifiers.org/aop.relationships/5", 5),
        (ids.STRESSOR, "stressor 50", 50),
    ],
)
def test_other_entity_forms(kind, raw, expected):
    assert ids.parse_entity_id(kind, raw) == expected


@pytest.mark.parametrize(
    ("kind", "raw"),
    [
        (ids.AOP, "0"),
        (ids.AOP, "-3"),
        (ids.AOP, "KE 18"),
        (ids.AOP, "https://identifiers.org/aop.events/18"),
        (ids.AOP, "37; DROP"),
        (ids.AOP, "1234567"),
        (ids.KEY_EVENT, "aop:18"),
        (ids.AOP, ""),
    ],
)
def test_entity_id_rejects(kind, raw):
    with pytest.raises(ids.InvalidIdentifier):
        ids.parse_entity_id(kind, raw)


def test_entity_iri_is_https():
    assert ids.entity_iri(ids.KEY_EVENT, 18).value == "https://identifiers.org/aop.events/18"
    assert ids.id_from_iri(ids.AOP, "https://identifiers.org/aop/3") == 3
    assert ids.id_from_iri(ids.AOP, "https://identifiers.org/aop.events/3") is None


@pytest.mark.parametrize("raw", ["107-18-6", "cas:107-18-6", "http://identifiers.org/cas/107-18-6"])
def test_cas(raw):
    assert ids.parse_cas(raw) == "107-18-6"


@pytest.mark.parametrize("raw", ["107186", "107-18-66", "abc", "07-18-6"])
def test_cas_rejects(raw):
    with pytest.raises(ids.InvalidIdentifier):
        ids.parse_cas(raw)


def test_inchikey_and_chebi():
    assert ids.parse_inchikey("juvIOZPCNVVQFO-HBGVWJBISA-N") == "JUVIOZPCNVVQFO-HBGVWJBISA-N"
    assert ids.parse_chebi("CHEBI:16236") == "16236"
    assert ids.parse_chebi("https://identifiers.org/chebi/16236") == "16236"
    with pytest.raises(ids.InvalidIdentifier):
        ids.parse_inchikey("JUVIOZPCNVVQFO")


def test_gene():
    assert ids.parse_gene("HGNC:348") == ids.GeneRef(hgnc_id=348)
    assert ids.parse_gene("348") == ids.GeneRef(hgnc_id=348)
    assert ids.parse_gene("ahr") == ids.GeneRef(symbol="AHR")
    with pytest.raises(ids.InvalidIdentifier):
        ids.parse_gene("A HR")


def test_taxon():
    assert ids.parse_taxon("9606") == 9606
    assert ids.taxon_iri(9606).value.endswith("/NCBITAXON/9606")


def test_xrefs():
    assert [i.value for i in ids.parse_xref("wikidata", "q42")] == [
        "https://identifiers.org/wikidata/Q42"
    ]
    assert [i.value for i in ids.parse_xref("pubchem", "pubchem.compound:702")] == [
        "https://identifiers.org/pubchem.compound/702"
    ]
    assert [i.value for i in ids.parse_xref("hmdb", "HMDB34436")] == [
        "https://identifiers.org/hmdb/HMDB0034436",
        "https://identifiers.org/hmdb/HMDB34436",
    ]
    with pytest.raises(ids.InvalidIdentifier):
        ids.parse_xref("drugbank", "DB12")


def test_search_term():
    assert ids.parse_search_term("  Liver   Fibrosis ") == "liver fibrosis"
    with pytest.raises(ids.InvalidIdentifier):
        ids.parse_search_term("a")
