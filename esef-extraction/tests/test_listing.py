import pytest

from extraction.sources.listing import LISTING_COLUMNS, build_listing, filename_date, language_hint, read_listing
from fakes import make_filing

LEI = "815600AAAAAAAAAAAA01"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (f"{LEI}-2024-12-31-it.json", "it"),
        (f"{LEI}-2024-12-31-0-en.json", "en"),
        ("moncler-2024-12-31-0-IT.json", "it"),
        (f"{LEI}-2024-12-31.json", None),  # "31" is not a language token
        (f"{LEI}-2025-12-31-1-it.xhtml", None),
    ],
)
def test_language_hint_is_the_literal_filename_suffix(name, expected):
    assert language_hint(f"https://filings.xbrl.org/x/{name}") == expected


def test_language_hint_handles_missing_url():
    assert language_hint(None) is None


def test_filename_date_falls_back_to_package_name():
    assert filename_date(None, f"https://h/{LEI}-2023-12-31-it.zip") == "2023-12-31"


def test_build_listing_flags_mislabelled_periods_and_versions():
    records = [
        make_filing(LEI, "2024-12-31", "1"),
        make_filing(LEI, "2024-12-31", "2", json_name="{lei}-2023-12-31-it.json", seq=1),  # API period != file
        make_filing("815600BBBBBBBBBBBB02", "2025-06-30", "3", json_name=None),
    ]
    df = build_listing(records)
    assert list(df.columns) == LISTING_COLUMNS
    row = df.set_index("filing_id")
    assert bool(row.loc["1", "period_end_matches_filename"]) is True
    assert bool(row.loc["2", "period_end_matches_filename"]) is False
    assert row.loc["2", "fxo_seq"] == 1
    assert row.loc["1", "n_filings_same_lei_period"] == 2
    assert bool(row.loc["3", "has_json"]) is False
    assert bool(row.loc["3", "is_calendar_year_end"]) is False
    assert row["lei_matches_fxo_id"].all()


def test_period_check_is_unknown_when_file_names_carry_no_date():
    df = build_listing([make_filing(LEI, "2021-12-31", "1", json_name="Saipem.json", package_name="Saipem_2021.zip")])
    assert df["filename_date"].isna().all()
    assert df["period_end_matches_filename"].isna().all()


def test_read_listing_keeps_identifiers_as_strings(tmp_path):
    digits_lei = "81560000000000000012"
    df = build_listing([make_filing(digits_lei, "2024-12-31", "7", sha256="0" * 64)])
    path = tmp_path / "filings.csv"
    df.to_csv(path, index=False)
    back = read_listing(path)
    assert back.loc[0, "lei"] == digits_lei
    assert back.loc[0, "sha256"] == "0" * 64
    assert back.loc[0, "filing_id"] == "7"
    assert bool(back.loc[0, "has_json"]) is True
