from pathlib import Path

import pytest
from pydantic import ValidationError

from extraction.schema.sample import SampleConfig, load_sample_config
from extraction.sources.listing import build_listing
from extraction.sources.sample import build_proposal, choose_versions, eligible_issuers
from fakes import make_filing

LEI_A = "815600AAAAAAAAAAAA01"
LEI_B = "815600BBBBBBBBBBBB02"
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "sample_candidates.yaml"


def by_id(choices):
    return {c.filing_id: c for c in choices}


def test_single_version_is_proposed_without_review():
    df = build_listing([make_filing(LEI_A, filing_id="1")])
    (choice,) = choose_versions(df)
    assert (choice.proposed, choice.rule, choice.needs_review) == (True, "UNICA", False)


def test_italian_version_is_preferred_and_flagged_for_review():
    df = build_listing([
        make_filing(LEI_A, filing_id="1", json_name="{lei}-{pe}-en.json"),
        make_filing(LEI_A, filing_id="2", json_name="{lei}-{pe}-it.json", seq=1),
    ])
    c = by_id(choose_versions(df))
    assert c["2"].proposed and c["2"].rule == "R3_LINGUA_IT" and c["2"].needs_review
    assert not c["1"].proposed and c["1"].rule == "R3_LINGUA"


def test_identical_packages_keep_the_first_one():
    df = build_listing([
        make_filing(LEI_A, filing_id="5", sha256="a" * 64),
        make_filing(LEI_A, filing_id="9", sha256="a" * 64, date_added="2025-09-24 21:00:00.000000", seq=1),
    ])
    c = by_id(choose_versions(df))
    assert c["5"].proposed and c["5"].rule == "UNICA_RIMASTA" and not c["5"].needs_review
    assert c["9"].rule == "R4_PACCHETTO_IDENTICO"


def test_same_language_versions_pick_the_latest():
    df = build_listing([
        make_filing(LEI_A, filing_id="1", date_added="2025-04-15 12:00:00.000000"),
        make_filing(LEI_A, filing_id="2", date_added="2025-09-24 21:00:00.000000", seq=1),
    ])
    c = by_id(choose_versions(df))
    assert c["2"].proposed and c["2"].rule == "R5_PIU_RECENTE" and c["2"].needs_review
    assert c["1"].rule == "R5_VERSIONE_PRECEDENTE"


def test_language_and_recency_rules_combine():
    df = build_listing([
        make_filing(LEI_A, filing_id="1", json_name="{lei}-{pe}-0-it.json"),
        make_filing(LEI_A, filing_id="2", json_name="{lei}-{pe}-0-en.json", seq=1),
        make_filing(LEI_A, filing_id="3", json_name="{lei}-{pe}-0-it.json", seq=2,
                    date_added="2025-04-15 12:30:00.000000"),
    ])
    c = by_id(choose_versions(df))
    assert c["3"].proposed and c["3"].rule == "R3_LINGUA_IT+R5_PIU_RECENTE"
    assert [c[i].proposed for i in ("1", "2")] == [False, False]


def test_versions_without_json_or_with_wrong_period_are_excluded():
    df = build_listing([
        make_filing(LEI_A, filing_id="1", json_name=None),
        make_filing(LEI_A, filing_id="2", json_name="{lei}-2023-12-31-it.json", seq=1),
        make_filing(LEI_A, filing_id="3", seq=2),
    ])
    c = by_id(choose_versions(df))
    assert (c["1"].rule, c["2"].rule) == ("R1_SENZA_JSON", "R2_PERIODO_INCOERENTE")
    assert c["3"].proposed and c["3"].rule == "UNICA_RIMASTA"


def test_eligibility_needs_both_years_with_calendar_year_end():
    df = build_listing([
        make_filing(LEI_A, "2024-12-31", "1"), make_filing(LEI_A, "2025-12-31", "2"),
        make_filing(LEI_B, "2024-12-31", "3"), make_filing(LEI_B, "2025-06-30", "4"),
    ])
    eligible = eligible_issuers(df, [2024, 2025])
    assert eligible["lei"].tolist() == [LEI_A]
    assert eligible[["n_versions_2024", "n_versions_2025"]].values.tolist() == [[1, 1]]


def minimal_config(**overrides):
    data = {
        "status": "proposta",
        "fiscal_years": [2024, 2025],
        "targets": {"banca": [1, 1]},
        "candidates": [{
            "lei": LEI_A, "issuer": "Acme", "group": "banca", "sector_proposed": "Banca",
            "index_proposed": "FTSE MIB", "star_proposed": False, "rationale": "test",
        }],
    }
    data.update(overrides)
    return SampleConfig.model_validate(data)


def test_proposal_contains_every_version_and_one_choice_per_year():
    df = build_listing([
        make_filing(LEI_A, "2024-12-31", "1"),
        make_filing(LEI_A, "2025-12-31", "2", json_name="{lei}-{pe}-en.json"),
        make_filing(LEI_A, "2025-12-31", "3", json_name="{lei}-{pe}-it.json", seq=1),
    ])
    proposal, summary = build_proposal(df, minimal_config())
    assert len(proposal) == 3
    assert proposal.groupby("fiscal_year")["proposed_use"].apply(lambda s: (s == "Y").sum()).tolist() == [1, 1]
    assert set(proposal["classification_status"]) == {"DA VERIFICARE"}
    assert summary["warnings"] == [] and summary["choices_needing_review"] == 1


def test_proposal_rejects_ineligible_candidates():
    df = build_listing([make_filing(LEI_A, "2024-12-31", "1")])
    with pytest.raises(ValueError, match=LEI_A):
        build_proposal(df, minimal_config())


def test_config_rejects_duplicates_and_unsigned_approval():
    cand = minimal_config().candidates[0].model_dump()
    with pytest.raises(ValidationError):
        minimal_config(candidates=[cand, cand])
    with pytest.raises(ValidationError):
        minimal_config(status="approvata")


def test_repository_sample_config_matches_requested_composition():
    config = load_sample_config(CONFIG_PATH)
    assert config.status == "proposta" and config.approved_by is None
    assert len(config.candidates) == 20
    groups = [c.group for c in config.candidates]
    for group, (lo, hi) in config.targets.items():
        assert lo <= groups.count(group) <= hi, group
