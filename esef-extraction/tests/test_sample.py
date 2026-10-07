import pandas as pd
import pytest
import yaml
from pydantic import ValidationError

from extraction.sample import (
    build_sample_proposal,
    choose_version,
    filename_date_mismatch,
    lang_hint,
    load_sample_config,
)
from extraction.schema.filings import INDEX_COLUMNS

LEI_A = "815600115DA6E507AE33"  # Carel (valid LEI)
LEI_B = "815600F25FF44EF1FA76"  # Italgas (valid LEI)
URL = "https://filings.xbrl.org"


def filing(filing_id, lei, period_end, *, sha="a" * 64, json_name=None, pkg_name=None, errors=0):
    pkg_name = pkg_name or f"{lei}-{period_end}.zip"
    json_name = f"{lei}-{period_end}-it.json" if json_name is None else json_name
    return {
        "filing_id": str(filing_id),
        "fxo_id": f"{lei}-{period_end}-ESEF-IT-{filing_id % 10}",
        "lei": lei,
        "lei_checksum_ok": True,
        "entity_name": f"ENTITY {lei[-4:]}",
        "country": "IT",
        "period_end": period_end,
        "language": None,
        "date_added": "2026-04-01 10:00:00",
        "processed": "2026-04-01 10:05:00",
        "sha256": sha,
        "json_url": f"{URL}/{lei}/{period_end}/ESEF/IT/0/{json_name}" if json_name != "" else None,
        "package_url": f"{URL}/{lei}/{period_end}/ESEF/IT/0/{pkg_name}",
        "viewer_url": None,
        "error_count": errors,
        "warning_count": 0,
        "inconsistency_count": 0,
        "snapshot_at": "2026-10-07T07:19:22+00:00",
    }


def versions(*rows):
    frame = pd.DataFrame(rows, columns=INDEX_COLUMNS)
    frame["period_end"] = pd.to_datetime(frame["period_end"])
    frame["lang_hint_filename"] = [lang_hint(j, p) for j, p in zip(frame.json_url, frame.package_url)]
    frame["filename_date_mismatch"] = frame.apply(filename_date_mismatch, axis=1)
    return frame


@pytest.mark.parametrize(
    ("json_url", "package_url", "expected"),
    [
        (f"{URL}/x/LEI-2025-12-31-0-it.json", None, "it"),
        (f"{URL}/x/moncler-2024-12-31-0-IT.json", None, "it"),
        (f"{URL}/x/LEI-2025-12-31.json", f"{URL}/x/LEI-2025-12-31-en.zip", "en"),
        (f"{URL}/x/LEI-2025-12-31.json", f"{URL}/x/LEI-2025-12-31.xbri", None),
        (None, None, None),
    ],
)
def test_lang_hint(json_url, package_url, expected):
    assert lang_hint(json_url, package_url) == expected


def test_single_version_is_used():
    chosen, flag, _ = choose_version(versions(filing(1, LEI_A, "2025-12-31")))
    assert (chosen, flag) == ("1", "unica")


def test_identical_packages_use_the_first_loaded():
    frame = versions(filing(12, LEI_A, "2024-12-31"), filing(3, LEI_A, "2024-12-31"))
    chosen, flag, _ = choose_version(frame)
    assert chosen == "3" and "identici" in flag


def test_italian_version_is_proposed_when_languages_differ():
    frame = versions(
        filing(1, LEI_B, "2025-12-31", sha="a" * 64, json_name=f"{LEI_B}-2025-12-31-0-en.json"),
        filing(2, LEI_B, "2025-12-31", sha="b" * 64, json_name=f"{LEI_B}-2025-12-31-0-it.json"),
    )
    chosen, flag, reason = choose_version(frame)
    assert chosen == "2" and "lingue diverse" in flag
    assert "da confermare" in reason


@pytest.mark.parametrize(
    "json_names",
    [
        ("{lei}-2024-12-31-it.json", "{lei}-2024-12-31-it.json"),  # same language, different hash
        ("{lei}-2024-12-31-it.json", "{lei}-2024-12-31-en.json", "{lei}-2024-12-31-en.json"),
        ("{lei}-2024-12-31.json", "{lei}-2024-12-31.json"),  # no language token
    ],
)
def test_undecidable_versions_get_no_proposal(json_names):
    rows = [
        filing(i, LEI_A, "2024-12-31", sha=str(i) * 64, json_name=name.format(lei=LEI_A))
        for i, name in enumerate(json_names, start=1)
    ]
    chosen, flag, _ = choose_version(versions(*rows))
    assert chosen is None and "non distinguibili" in flag


def test_version_with_wrong_date_in_file_name_is_set_aside():
    # Real pattern seen in the index: a FY2023 package registered with period_end 2024-12-31.
    frame = versions(
        filing(1, LEI_A, "2024-12-31", sha="a" * 64, json_name=f"{LEI_A}-2023-12-31-it.json",
               pkg_name=f"{LEI_A}-2023-12-31-it.zip"),
        filing(2, LEI_A, "2024-12-31", sha="b" * 64, json_name=f"{LEI_A}-2024-12-31-0-it.json"),
    )
    assert frame["filename_date_mismatch"].tolist() == [True, False]
    chosen, flag, reason = choose_version(frame)
    assert chosen == "2" and "anomalia" in flag and "1" in reason


def write_inputs(tmp_path, rows, issuers):
    csv_path = tmp_path / "filings_it.csv"
    pd.DataFrame(rows, columns=INDEX_COLUMNS).to_csv(csv_path, index=False)
    config_path = tmp_path / "sample.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "fiscal_years": [2024, 2025],
                "period_end_month_day": "12-31",
                "sector_groups": ["industriali_servizi", "utility"],
                "segments": ["FTSE MIB", "STAR"],
                "issuers": issuers,
            }
        ),
        encoding="utf-8",
    )
    return csv_path, load_sample_config(config_path)


def issuer(lei, status="proposed", group="industriali_servizi", segment="STAR"):
    return {"lei": lei, "name": "X", "sector_group": group, "sector": "s", "segment": segment, "status": status}


def test_build_sample_proposal(tmp_path):
    rows = [
        filing(1, LEI_A, "2024-12-31"),
        filing(2, LEI_A, "2025-12-31"),
        filing(3, LEI_A, "2023-12-31"),  # outside the requested years
        filing(4, LEI_B, "2024-12-31", json_name=""),  # no xBRL-JSON: excluded
        filing(5, LEI_B, "2024-12-31", sha="b" * 64),
        filing(6, LEI_B, "2025-12-31", sha="c" * 64, json_name=f"{LEI_B}-2025-12-31-en.json"),
        filing(7, LEI_B, "2025-12-31", sha="d" * 64, json_name=f"{LEI_B}-2025-12-31-it.json"),
    ]
    csv_path, config = write_inputs(
        tmp_path, rows, [issuer(LEI_A), issuer(LEI_B, status="reserve", group="utility", segment="FTSE MIB")]
    )
    proposal, problems = build_sample_proposal(csv_path, config)
    assert problems == []
    assert proposal["status"].tolist() == ["proposed", "proposed", "reserve", "reserve", "reserve"]
    assert proposal["filing_id"].tolist() == ["1", "2", "5", "6", "7"]
    b_2024 = proposal[(proposal.lei == LEI_B) & (proposal.fiscal_year == 2024)].iloc[0]
    assert b_2024["n_versions"] == 1 and b_2024["n_versions_without_json"] == 1
    b_2025 = proposal[(proposal.lei == LEI_B) & (proposal.fiscal_year == 2025)]
    assert b_2025.set_index("filing_id")["proposed_version"].to_dict() == {"6": "N", "7": "Y"}


def test_missing_year_and_unknown_lei_are_reported(tmp_path):
    rows = [filing(1, LEI_A, "2024-12-31"), filing(2, LEI_A, "2025-06-30")]
    unknown = "529900T8BM49AURSDO55"
    csv_path, config = write_inputs(tmp_path, rows, [issuer(LEI_A), issuer(unknown)])
    proposal, problems = build_sample_proposal(csv_path, config)
    assert any("2025-12-31" in p for p in problems)
    assert any(unknown in p and "assente" in p for p in problems)
    missing = proposal[proposal.fiscal_year == 2025].iloc[0]
    assert missing["version_flag"] == "mancante"


def test_config_rejects_duplicates_and_unknown_values(tmp_path):
    with pytest.raises(ValidationError):
        write_inputs(tmp_path, [], [issuer(LEI_A), issuer(LEI_A)])
    with pytest.raises(ValidationError):
        write_inputs(tmp_path, [], [issuer(LEI_A, segment="Nasdaq")])
    with pytest.raises(ValidationError):
        write_inputs(tmp_path, [], [issuer("NOT-A-LEI")])


def test_project_sample_config_is_valid():
    from extraction.settings import PROJECT_ROOT

    config = load_sample_config(PROJECT_ROOT / "config" / "sample.yaml")
    proposed = [i for i in config.issuers if i.status == "proposed"]
    groups = pd.Series([i.sector_group for i in proposed]).value_counts().to_dict()
    assert len(proposed) == 20
    assert groups == {"industriali_servizi": 14, "utility": 3, "banca": 2, "assicurazione": 1}
