import pytest

from app.sparql.terms import Int, Iri, IriList, Lit, LitList, TermError


def test_iri_serialises_in_angle_brackets():
    assert Iri("https://identifiers.org/aop/37").n3() == "<https://identifiers.org/aop/37>"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "no-scheme",
        "https://x.org/a b",
        "https://x.org/>; DROP",
        'https://x.org/"',
        "https://x.org/{x}",
        "https://x.org/\x00",
        "https://x.org/a\\b",
    ],
)
def test_iri_rejects_unsafe_values(value):
    with pytest.raises(TermError):
        Iri(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("liver", '"liver"'),
        ('"} ; DROP', '"\\"} ; DROP"'),
        ("a\\b", '"a\\\\b"'),
        ("line\nbreak\ttab\r", '"line\\nbreak\\ttab\\r"'),
    ],
)
def test_literal_escapes(value, expected):
    assert Lit(value).n3() == expected


@pytest.mark.parametrize("value", ["\x00", "bell\x07", "x" * 201])
def test_literal_rejects_control_chars_and_long_values(value):
    with pytest.raises(TermError):
        Lit(value)


def test_literal_max_length_can_be_raised():
    assert Lit("x" * 500, max_length=1000).n3().startswith('"x')


@pytest.mark.parametrize("value", [-1, True, 1.5, "3"])
def test_int_rejects_non_integers(value):
    with pytest.raises(TermError):
        Int(value)


def test_lists():
    iris = IriList((Iri("https://identifiers.org/aop/3"), Iri("https://identifiers.org/aop/4")))
    assert iris.n3() == "<https://identifiers.org/aop/3> <https://identifiers.org/aop/4>"
    assert LitList((Lit("a"), Lit("b"))).n3() == '"a" "b"'
    with pytest.raises(TermError):
        IriList(())
