from pathlib import Path

import pandas as pd
import pytest
import yaml

from extraction.sample import (
    VERSION_CASE_LANG,
    VERSION_CASE_REFILING,
    VERSION_CASE_SAME_HASH,
    VERSION_CASE_SINGLE,
    build_candidates,
    build_proposal,
    classify_versions,
    load_proposal_config,
)
from extraction.sources.filings_api import write_filings_csv
from factories import entity, filing

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LEI_1 = "BUCRF72VH5RBN7X3VL35"
LEI_2 = "549300X5UKJVE386ZB61"
LEI_3 = "8156001A772766DCAA71"


def _filings_csv(tmp_path, filings, entities):
    page = {"data": filings, "included": entities, "links": {}, "meta": {"count": len(filings)}}
    path = tmp_path / "filings_it.csv"
    write_filings_csv([page], "T", path)
    return path


@pytest.fixture
def filings_csv(tmp_path):
    ents = [entity("1", LEI_1, "ALFA"), entity("2", LEI_2, "BETA"), entity("3", LEI_3, "GAMMA")]
    fl = [
        # ALFA: 2024 in due lingue, 2025 con due versioni stessa lingua e hash diversi
        filing(1, LEI_1, "2024-12-31", 0, json_name=f"{LEI_1}-2024-12-31-en", sha="1" * 64, entity_id="1"),
        filing(2, LEI_1, "2024-12-31", 1, json_name=f"{LEI_1}-2024-12-31-it", sha="2" * 64, entity_id="1"),
        filing(3, LEI_1, "2025-12-31", 0, sha="3" * 64, date_added="2026-04-01 10:00:00", entity_id="1"),
        filing(4, LEI_1, "2025-12-31", 1, sha="4" * 64, date_added="2026-09-24 10:00:00", entity_id="1"),
        # BETA: 2025 senza xBRL-JSON -> esclusa
        filing(5, LEI_2, "2024-12-31", entity_id="2"),
        filing(6, LEI_2, "2025-12-31", json_name="", entity_id="2"),
        # GAMMA: esercizio non solare -> esclusa
        filing(7, LEI_3, "2025-01-31", entity_id="3"),
        filing(8, LEI_3, "2026-01-31", entity_id="3"),
    ]
    return _filings_csv(tmp_path, fl, ents)


def test_classify_versions():
    base = {"api_sha256": "a", "lang_hint_from_filename": "it"}
    assert classify_versions(pd.DataFrame([base])) == VERSION_CASE_SINGLE
    assert classify_versions(pd.DataFrame([base, base])) == VERSION_CASE_SAME_HASH
    assert classify_versions(pd.DataFrame([base, {**base, "api_sha256": "b"}])) == VERSION_CASE_REFILING
    assert classify_versions(pd.DataFrame([base, {**base, "lang_hint_from_filename": "en"}])) == VERSION_CASE_LANG


def test_build_candidates_keeps_only_complete_calendar_year_issuers(filings_csv, tmp_path):
    out = build_candidates(filings_csv, tmp_path / "cand.csv")
    assert set(out["lei"]) == {LEI_1}
    assert (tmp_path / "cand.csv").exists()


def test_build_candidates_flags_versions_and_proposes_one_per_year(filings_csv, tmp_path):
    out = build_candidates(filings_csv, tmp_path / "cand.csv").set_index("filing_id")
    assert out.loc["1", "version_case"] == VERSION_CASE_LANG
    assert out.loc["3", "version_case"] == VERSION_CASE_REFILING
    # lingua preferita "it"
    assert bool(out.loc["2", "proposed_version"]) and not bool(out.loc["1", "proposed_version"])
    # stessa lingua: l'ultima aggiunta
    assert bool(out.loc["4", "proposed_version"]) and not bool(out.loc["3", "proposed_version"])
    assert out.groupby("fiscal_year")["proposed_version"].sum().tolist() == [1, 1]


def test_build_candidates_flags_period_end_filename_mismatch(tmp_path):
    fl = [
        filing(1, LEI_1, "2024-12-31", json_name=f"{LEI_1}-2023-12-31-it", entity_id="1"),
        filing(2, LEI_1, "2025-12-31", entity_id="1"),
    ]
    path = _filings_csv(tmp_path, fl, [entity("1", LEI_1, "ALFA")])
    out = build_candidates(path, tmp_path / "cand.csv").set_index("filing_id")
    assert bool(out.loc["1", "period_end_filename_mismatch"])
    assert not bool(out.loc["2", "period_end_filename_mismatch"])


def _write_yaml(path, issuers):
    path.write_text(yaml.safe_dump({"issuers": issuers}), encoding="utf-8")
    return path


def test_build_proposal_rejects_issuers_without_complete_filings(filings_csv, tmp_path):
    build_candidates(filings_csv, tmp_path / "cand.csv")
    cfg = _write_yaml(
        tmp_path / "p.yaml",
        [{"lei": LEI_2, "proposed_group": "bank", "proposed_sector": "x",
          "proposed_market_segment": "y", "selection_rationale": "z"}],
    )
    with pytest.raises(ValueError, match=LEI_2):
        build_proposal(cfg, tmp_path / "cand.csv", tmp_path / "out.csv")


def test_build_proposal_marks_classification_as_unverified(filings_csv, tmp_path):
    build_candidates(filings_csv, tmp_path / "cand.csv")
    cfg = _write_yaml(
        tmp_path / "p.yaml",
        [{"lei": LEI_1, "proposed_group": "utility", "proposed_sector": "x",
          "proposed_market_segment": "y", "selection_rationale": "z"}],
    )
    out = build_proposal(cfg, tmp_path / "cand.csv", tmp_path / "out.csv")
    assert (out["classification_status"] == "DA VERIFICARE").all()
    assert len(out) == 4  # tutte le versioni, con proposed_version


def test_proposal_config_rejects_unknown_group_and_duplicates(tmp_path):
    item = {"lei": LEI_1, "proposed_group": "bank"}
    with pytest.raises(ValueError, match="non valido"):
        load_proposal_config(_write_yaml(tmp_path / "a.yaml", [{**item, "proposed_group": "fintech"}]))
    with pytest.raises(ValueError, match="duplicato"):
        load_proposal_config(_write_yaml(tmp_path / "b.yaml", [item, item]))


def test_repository_proposal_respects_requested_mix():
    issuers = load_proposal_config(PROJECT_ROOT / "config" / "sample_proposal.yaml")
    groups = pd.Series([i["proposed_group"] for i in issuers]).value_counts()
    assert len(issuers) == 20
    assert 12 <= groups.get("industrial_services", 0) <= 16
    assert 2 <= groups.get("utility", 0) <= 3
    assert groups.get("bank", 0) == 2
    assert groups.get("insurance", 0) == 1
