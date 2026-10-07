import copy

import pytest

from extraction.schema.filings import INDEX_COLUMNS, lei_checksum_ok
from extraction.sources.filings_api import ApiError
from extraction.sources.filings_index import (
    build_filings_index,
    parse_filings_page,
    read_filings_index,
    write_filings_index,
)
from tests.conftest import BASE_URL, FakeResponse

SNAPSHOT = "2026-10-07T07:19:22+00:00"


def test_parse_real_page(make_api, api_page):
    api, _ = make_api([])
    records = parse_filings_page(api_page, api, SNAPSHOT)
    assert len(records) == 2
    ovs = records[0]
    assert ovs.lei == "8156001A772766DCAA71"
    assert ovs.entity_name == "OVS SPA"
    assert ovs.period_end.isoformat() == "2023-01-31"
    assert ovs.language is None  # not provided by the API
    assert ovs.sha256 == "6b6b1fd281dda0b8baf1d7524488daa5bbd5b76d5778734f41252bcef829e0ce"
    assert ovs.json_url.startswith(f"{BASE_URL}/8156001A772766DCAA71/2023-01-31/")
    assert ovs.package_url.endswith(".zip")
    assert ovs.error_count == 0 and ovs.warning_count == 18
    assert ovs.lei_checksum_ok


def test_missing_attribute_stops_the_parser(make_api, api_page):
    api, _ = make_api([])
    broken = copy.deepcopy(api_page)
    del broken["data"][0]["attributes"]["json_url"]
    with pytest.raises(ApiError, match="json_url"):
        parse_filings_page(broken, api, SNAPSHOT)


def test_missing_entity_stops_the_parser(make_api, api_page):
    api, _ = make_api([])
    broken = copy.deepcopy(api_page)
    broken["included"] = []
    with pytest.raises(ApiError, match="entity not found"):
        parse_filings_page(broken, api, SNAPSHOT)


def test_null_json_url_is_kept_as_missing(make_api, api_page):
    api, _ = make_api([])
    page = copy.deepcopy(api_page)
    page["data"][0]["attributes"]["json_url"] = None
    assert parse_filings_page(page, api, SNAPSHOT)[0].json_url is None


@pytest.mark.parametrize(
    ("lei", "expected"),
    [
        ("8156001A772766DCAA71", True),
        ("815600115DA6E507AE33", True),
        ("815600115DA6E507AE34", False),  # wrong check digits
        ("not-a-lei", False),
    ],
)
def test_lei_checksum(lei, expected):
    assert lei_checksum_ok(lei) is expected


def test_build_write_and_read_back(make_api, api_page, tmp_path):
    api, _ = make_api([FakeResponse(body=api_page | {"links": {}, "meta": {"count": 2}})])
    frame, meta = build_filings_index(api, country="IT", raw_dir=tmp_path / "raw")
    assert list(frame.columns) == INDEX_COLUMNS
    assert meta["records"] == 2 and meta["announced_count"] == 2
    saved_pages = list((tmp_path / "raw" / "api").glob("filings_it_*/page_0001.json"))
    assert len(saved_pages) == 1  # raw response kept for provenance

    csv_path = tmp_path / "interim" / "filings_it.csv"
    meta_path = write_filings_index(frame, meta, csv_path)
    assert meta_path.exists()
    again = read_filings_index(csv_path)
    assert again["lei"].tolist() == frame["lei"].tolist()
    assert again["filing_id"].tolist() == ["6710", "6708"]  # sorted by LEI
    assert again["language"].isna().all()


def test_count_mismatch_is_an_error(make_api, api_page, tmp_path):
    api, _ = make_api([FakeResponse(body=api_page | {"links": {}, "meta": {"count": 5}})])
    with pytest.raises(ApiError, match="announced 5"):
        build_filings_index(api, country="IT", raw_dir=tmp_path)
