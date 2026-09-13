import pytest
from starlette.requests import Request

from app.errors import ApiError
from app.formats import negotiate, to_csv


def make_request(accept: str | None = None) -> Request:
    headers = [] if accept is None else [(b"accept", accept.encode())]
    return Request(
        {"type": "http", "method": "GET", "path": "/", "headers": headers, "query_string": b""}
    )


@pytest.mark.parametrize(
    ("accept", "expected"),
    [
        (None, "json"),
        ("*/*", "json"),
        ("application/json", "json"),
        ("text/csv", "csv"),
        ("text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "json"),
        ("text/csv;q=0.5, application/json", "json"),
        ("application/json;q=0.2, text/csv", "csv"),
    ],
)
def test_negotiate(accept, expected):
    assert negotiate(make_request(accept), None) == expected


def test_format_param_overrides_accept():
    assert negotiate(make_request("application/json"), "csv") == "csv"


def test_negotiate_rejects_unservable_types():
    with pytest.raises(ApiError) as exc:
        negotiate(make_request("application/rdf+xml"), None)
    assert exc.value.status == 406


def test_to_csv_flattens_nested_values():
    text = to_csv(
        [
            {"id": 1, "upstream": {"id": 2, "title": "A, b"}, "aop_ids": [3, 4], "is_mie": True},
            {"id": 5, "extra": None, "roles": [{"aop_id": 7, "role": "ao"}]},
        ]
    )
    lines = text.splitlines()
    assert lines[0] == "id,upstream_id,upstream_title,aop_ids,is_mie,extra,roles"
    assert lines[1] == '1,2,"A, b",3|4,true,,'
    assert lines[2].startswith("5,,,,,,")
