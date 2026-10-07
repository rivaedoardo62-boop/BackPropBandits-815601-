import pandas as pd
import pytest

from extraction.sources.filings_api import (
    FILINGS_COLUMNS,
    date_in_filename,
    flatten_filing,
    iter_filing_pages,
    lang_hint_from_filename,
    lei_checksum_ok,
    load_pages,
    rows_from_pages,
    save_pages,
    write_filings_csv,
)
from factories import LEI_A, entity, filing


@pytest.mark.parametrize("lei", ["BUCRF72VH5RBN7X3VL35", "8156001A772766DCAA71", "549300X5UKJVE386ZB61"])
def test_lei_checksum_valid(lei):
    assert lei_checksum_ok(lei)


@pytest.mark.parametrize("lei", ["BUCRF72VH5RBN7X3VL36", "BUCRF72VH5RBN7X3VL3", None, "", "bucrf72vh5rbn7x3vl35"])
def test_lei_checksum_invalid(lei):
    assert not lei_checksum_ok(lei)


@pytest.mark.parametrize(
    "url,expected",
    [
        ("/X/2024-12-31/ESEF/IT/0/815600FBF92FD3531704-2024-12-31-it.json", "it"),
        ("/X/2024-12-31/ESEF/IT/0/5493000P70CQRQG8SN85-2024-12-31-0-en.json", "en"),
        ("/X/2024-12-31/ESEF/IT/0/moncler-2024-12-31-0-IT.json", "it"),
        ("/X/2021-12-31/ESEF/IT/0/2W8N8UU78PMDQKZENC08-2021-12-31.json", None),
        ("/X/2021-12-31/ESEF/IT/0/somethingAR.json", None),
        (None, None),
    ],
)
def test_lang_hint_from_filename(url, expected):
    assert lang_hint_from_filename(url) == expected


def test_date_in_filename():
    assert date_in_filename("/a/2032-12-31/ESEF/IT/0/X-2022-12-31-it.json") == "2022-12-31"
    assert date_in_filename("/a/b/noname.json") is None
    assert date_in_filename(None) is None


def test_flatten_filing_makes_absolute_urls_and_reads_lei_from_entity():
    row = flatten_filing(filing(7, LEI_A, "2024-12-31", seq=1), entity("1", LEI_A, "ENI S.P.A."), "T")
    assert row["lei"] == LEI_A
    assert row["entity_name"] == "ENI S.P.A."
    assert row["filing_seq"] == 1
    assert row["json_url"].startswith("https://filings.xbrl.org/")
    assert row["package_url"].endswith(".zip")
    assert row["lang_hint_from_filename"] == "it"
    assert row["json_filename_date"] == "2024-12-31"
    assert set(row) == set(FILINGS_COLUMNS)


def test_flatten_filing_keeps_missing_json_as_missing():
    row = flatten_filing(filing(8, LEI_A, "2024-12-31", json_name=""), entity("1", LEI_A, "X"), "T")
    assert row["json_url"] is None


class FakePoliteSession:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def get(self, url, params=None, stream=False):
        self.calls.append((url, params))
        payload = self.pages.pop(0)

        class R:
            def json(self_inner):
                return payload

        return R()


def test_iter_filing_pages_follows_next_links(two_pages):
    sess = FakePoliteSession(two_pages)
    pages = list(iter_filing_pages(sess, "IT", page_size=200))
    assert len(pages) == 2
    first_url, first_params = sess.calls[0]
    assert first_params["filter[country]"] == "IT"
    assert first_params["include"] == "entity"
    assert first_params["sort"] == "id"
    # La pagina successiva usa il link "next" così com'è, senza parametri aggiuntivi.
    assert sess.calls[1] == (two_pages[0]["links"]["next"], None)


def test_iter_filing_pages_raises_on_api_errors():
    sess = FakePoliteSession([{"errors": [{"detail": "bad filter"}]}])
    with pytest.raises(RuntimeError, match="bad filter"):
        list(iter_filing_pages(sess, "IT"))


def test_rows_from_pages_joins_entities(two_pages):
    rows = rows_from_pages(two_pages, "T")
    assert {r["entity_name"] for r in rows} == {"ENI S.P.A.", "OVS SPA"}


def test_write_filings_csv_checks_meta_count(two_pages, tmp_path):
    two_pages[0]["meta"]["count"] = 3
    with pytest.raises(RuntimeError, match="attese 3"):
        write_filings_csv(two_pages, "T", tmp_path / "f.csv")


def test_save_and_load_pages_roundtrip(two_pages, tmp_path):
    save_pages(two_pages, tmp_path / "p", "2026-10-07T00:00:00+00:00", "https://filings.xbrl.org/api/filings")
    pages, retrieved_at = load_pages(tmp_path / "p")
    assert pages == two_pages
    df = write_filings_csv(pages, retrieved_at, tmp_path / "f.csv")
    assert list(df.columns) == FILINGS_COLUMNS
    assert len(pd.read_csv(tmp_path / "f.csv")) == 2
