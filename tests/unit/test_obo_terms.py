import pytest

from app import ids


@pytest.mark.parametrize(
    "raw",
    [
        "UBERON:0002107",
        "uberon_0002107",
        " UBERON_0002107 ",
        "http://purl.obolibrary.org/obo/UBERON_0002107",
        "https://purl.obolibrary.org/obo/UBERON_0002107",
    ],
)
def test_obo_term_forms(raw):
    assert (
        ids.parse_obo_term("UBERON", raw).value == "http://purl.obolibrary.org/obo/UBERON_0002107"
    )


@pytest.mark.parametrize("raw", ["liver", "UBERON:2107", "CL:0000182", "UBERON:0002107>"])
def test_obo_term_rejects(raw):
    with pytest.raises(ids.InvalidIdentifier):
        ids.parse_obo_term("UBERON", raw)
