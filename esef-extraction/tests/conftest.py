import pytest

from factories import LEI_A, LEI_B, entity, filing


@pytest.fixture
def two_pages():
    page1 = {
        "data": [filing(1, LEI_A, "2024-12-31", entity_id="10")],
        "included": [entity("10", LEI_A, "ENI S.P.A.")],
        "links": {"next": "https://filings.xbrl.org/api/filings?page%5Bnumber%5D=2"},
        "meta": {"count": 2},
    }
    page2 = {
        "data": [filing(2, LEI_B, "2025-01-31", entity_id="11")],
        "included": [entity("11", LEI_B, "OVS SPA")],
        "links": {},
        "meta": {"count": 2},
    }
    return [page1, page2]
