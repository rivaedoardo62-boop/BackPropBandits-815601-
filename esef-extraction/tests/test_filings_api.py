import json

import pytest

from extraction.sources.filings_api import ApiConsistencyError, FilingsApiClient
from extraction.sources.http import PoliteSession
from fakes import BASE, FakeResponse, FakeSession

API = f"{BASE}/api/filings"


def api_item(fid, lei, entity_id, period_end="2024-12-31"):
    return {
        "type": "filing",
        "id": fid,
        "attributes": {
            "fxo_id": f"{lei}-{period_end}-ESEF-IT-0",
            "country": "IT",
            "period_end": period_end,
            "date_added": "2025-04-15 12:00:00.000000",
            "processed": "2025-04-15 13:00:00.000000",
            "sha256": "ab" * 32,
            "json_url": f"/{lei}/{period_end}/ESEF/IT/0/{lei}-{period_end}-it.json",
            "package_url": f"/{lei}/{period_end}/ESEF/IT/0/{lei}-{period_end}.zip",
            "report_url": None,
            "viewer_url": None,
            "error_count": 0,
            "warning_count": 2,
            "inconsistency_count": 0,
        },
        "relationships": {"entity": {"data": {"type": "entity", "id": entity_id}}},
    }


def entity(entity_id, lei, name):
    return {"type": "entity", "id": entity_id, "attributes": {"name": name, "identifier": lei}}


def make_client(pages, clock):
    fake = FakeSession(pages)
    http = PoliteSession("t/1", "filings.xbrl.org", 1.0, session=fake, clock=clock, sleep=clock.sleep)
    return FilingsApiClient(http, BASE, page_size=2), fake


def test_pagination_follows_next_link_and_joins_entities(clock):
    lei_a, lei_b = "815600AAAAAAAAAAAA01", "815600BBBBBBBBBBBB02"
    page1 = {
        "data": [api_item("1", lei_a, "10"), api_item("2", lei_b, "20")],
        "included": [entity("10", lei_a, "ALFA S.P.A."), entity("20", lei_b, "BETA S.P.A.")],
        "links": {"next": f"{API}?page%5Bnumber%5D=2"},
        "meta": {"count": 3},
    }
    page2 = {
        "data": [api_item("3", lei_a, "10", "2025-12-31")],
        "included": [entity("10", lei_a, "ALFA S.P.A.")],
        "links": {},
        "meta": {"count": 3},
    }
    client, fake = make_client([FakeResponse(API, payload=page1), FakeResponse(API, payload=page2)], clock)
    records = list(client.iter_filings(simple_filters={"country": "IT"}))

    assert [r["filing_id"] for r in records] == ["1", "2", "3"]
    assert records[1]["entity_name"] == "BETA S.P.A." and records[1]["lei"] == lei_b
    assert records[0]["json_url"] == f"{BASE}/{lei_a}/2024-12-31/ESEF/IT/0/{lei_a}-2024-12-31-it.json"
    first, second = fake.calls
    assert first["params"] == {"page[size]": 2, "include": "entity", "sort": "id", "filter[country]": "IT"}
    assert second["url"].endswith("page%5Bnumber%5D=2") and second["params"] is None
    assert clock.sleeps == [1.0]


def test_complex_filters_use_the_json_list_syntax(clock):
    page = {"data": [], "links": {}, "meta": {"count": 0}}
    client, fake = make_client([FakeResponse(API, payload=page)], clock)
    flt = [{"name": "entity.identifier", "op": "eq", "val": "815600AAAAAAAAAAAA01"}]
    assert list(client.iter_filings(filters=flt)) == []
    assert json.loads(fake.calls[0]["params"]["filter"]) == flt


def test_count_mismatch_raises(clock):
    page = {"data": [api_item("1", "815600AAAAAAAAAAAA01", "10")], "links": {}, "meta": {"count": 5}}
    client, _ = make_client([FakeResponse(API, payload=page)], clock)
    with pytest.raises(ApiConsistencyError):
        list(client.iter_filings())


def test_next_link_to_another_host_is_refused(clock):
    page = {"data": [], "links": {"next": "https://example.org/api/filings?page=2"}, "meta": {}}
    client, _ = make_client([FakeResponse(API, payload=page)], clock)
    with pytest.raises(ValueError):
        list(client.iter_filings())


def test_missing_entity_leaves_lei_empty(clock):
    item = api_item("1", "815600AAAAAAAAAAAA01", "99")
    page = {"data": [item], "included": [], "links": {}, "meta": {"count": 1}}
    client, _ = make_client([FakeResponse(API, payload=page)], clock)
    (record,) = client.iter_filings()
    assert record["lei"] is None and record["fxo_id"].startswith("815600AAAAAAAAAAAA01")
