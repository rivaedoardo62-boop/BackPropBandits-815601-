import pytest

from extraction.sources.filings_api import ApiError
from tests.conftest import BASE_URL, FakeResponse


def page(ids, next_url=None, count=None):
    document = {
        "data": [{"type": "filing", "id": str(i), "attributes": {}} for i in ids],
        "links": {"next": next_url} if next_url else {},
    }
    if count is not None:
        document["meta"] = {"count": count}
    return document


def test_pagination_follows_links_next_on_the_api_host(make_api):
    second = f"{BASE_URL}/api/filings?page%5Bnumber%5D=2"
    api, session = make_api(
        [FakeResponse(body=page([1, 2], second, count=3)), FakeResponse(body=page([3], count=3))]
    )
    pages = list(api.iter_filing_pages(country="IT", page_size=2))
    assert [len(p.document["data"]) for p in pages] == [2, 1]
    first_call = session.calls[0]["url"]
    assert "filter%5Bcountry%5D=IT" in first_call and "include=entity" in first_call
    assert "sort=id" in first_call
    assert session.calls[1]["url"] == second
    assert session.calls[0]["headers"]["Accept"] == "application/vnd.api+json"


def test_links_to_other_hosts_are_refused(make_api):
    api, _ = make_api([FakeResponse(body=page([1], "https://evil.example/api/filings?page=2"))])
    with pytest.raises(ApiError, match="other than filings.xbrl.org"):
        list(api.iter_filing_pages(country="IT"))


def test_relative_links_become_absolute(make_api):
    api, _ = make_api([])
    assert api.absolute_url("/LEI/2024-12-31/ESEF/IT/0/x.json") == f"{BASE_URL}/LEI/2024-12-31/ESEF/IT/0/x.json"
    assert api.absolute_url(None) is None
    with pytest.raises(ApiError):
        api.absolute_url("x.json")


def test_http_errors_raise(make_api):
    api, _ = make_api([FakeResponse(404, body=b"not found")])
    with pytest.raises(ApiError, match="HTTP 404"):
        api.get_document("/api/filings")


def test_non_jsonapi_body_raises(make_api):
    api, _ = make_api([FakeResponse(body=b"<html></html>")])
    with pytest.raises(ApiError, match="not JSON"):
        api.get_document("/api/filings")


def test_page_size_is_bounded(make_api):
    api, _ = make_api([])
    with pytest.raises(ValueError):
        list(api.iter_filing_pages(country="IT", page_size=500))
