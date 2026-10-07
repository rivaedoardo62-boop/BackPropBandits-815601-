"""Passo 3: eleggibilita' degli emittenti, proposta di campione e scelta delle versioni.

Regole di scelta della versione, applicate in ordine a tutte le relazioni dello
stesso emittente ed esercizio (una sola versione proposta per esercizio):
  R1_SENZA_JSON          esclusa se manca l'xBRL-JSON;
  R2_PERIODO_INCOERENTE  esclusa se la data nel nome del file contraddice period_end;
  R3_LINGUA              se esistono versioni con suffisso "it" e altre no, si tengono
                         quelle "it" (versione italiana come primaria; le altre servono
                         per il confronto IT/EN dopo il download);
  R4_PACCHETTO_IDENTICO  versioni con lo stesso SHA-256 del pacchetto: si tiene la prima;
  R5_VERSIONE_PRECEDENTE se ne restano piu' d'una, si propone la piu' recente (date_added).
R3 e R5 si basano su metadati non verificati: le scelte che ne dipendono sono marcate
needs_review=Y e vanno confermate dopo il download confrontando i valori numerici.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from extraction.schema.sample import SampleConfig

PROPOSAL_COLUMNS = [
    "proposal_status",
    "group",
    "issuer",
    "entity_name_api",
    "lei",
    "sector_proposed",
    "index_proposed",
    "star_proposed",
    "classification_status",
    "rationale",
    "fiscal_year",
    "period_end",
    "n_versions",
    "proposed_use",
    "version_rule",
    "version_note",
    "needs_review",
    "filing_id",
    "fxo_id",
    "date_added",
    "language_hint",
    "package_format",
    "error_count",
    "warning_count",
    "inconsistency_count",
    "sha256",
    "json_url",
    "package_url",
]

NOTES = {
    "UNICA": "Unica versione disponibile per l'esercizio.",
    "UNICA_RIMASTA": "Proposta: unica versione rimasta dopo le esclusioni.",
    "R1_SENZA_JSON": "Esclusa: nessun xBRL-JSON disponibile.",
    "R2_PERIODO_INCOERENTE": "Esclusa: la data nel nome del file non coincide con period_end dell'API.",
    "R3_LINGUA": "Non proposta: esiste una versione con suffisso 'it'; da usare per il confronto IT/EN.",
    "R3_LINGUA_IT": "Proposta: versione con suffisso 'it' (suffisso scelto dall'emittente, lingua da verificare).",
    "R4_PACCHETTO_IDENTICO": "Non proposta: stesso SHA-256 di una versione precedente (pacchetto identico).",
    "R5_VERSIONE_PRECEDENTE": "Non proposta: esiste una versione aggiunta piu' di recente con lo stesso suffisso di lingua.",
    "R5_PIU_RECENTE": "Proposta: versione aggiunta piu' di recente tra quelle con lo stesso suffisso di lingua.",
}


@dataclass(frozen=True)
class VersionChoice:
    filing_id: str
    proposed: bool
    rule: str
    needs_review: bool


def calendar_year_filings(listing: pd.DataFrame, fiscal_years: list[int]) -> pd.DataFrame:
    """Filings closing on 31/12 of one of the requested years (fiscal_year = year of period_end)."""
    df = listing.copy()
    df["fiscal_year"] = pd.to_numeric(df["period_end"].astype("string").str[:4], errors="coerce").astype("Int64")
    keep = df["is_calendar_year_end"].astype("boolean").fillna(False).astype(bool) & df["fiscal_year"].isin(fiscal_years)
    return df[keep].copy()


def _usable(df: pd.DataFrame) -> pd.Series:
    return df["has_json"].astype(bool) & df["period_end_matches_filename"].astype("boolean").fillna(True).astype(bool)


def eligible_issuers(listing: pd.DataFrame, fiscal_years: list[int]) -> pd.DataFrame:
    """Issuers with at least one usable version (xBRL-JSON, consistent period) for every year."""
    rows = calendar_year_filings(listing, fiscal_years)
    rows = rows[_usable(rows)]
    counts = rows.groupby(["lei", "fiscal_year"]).size().unstack(fill_value=0)
    for year in fiscal_years:
        if year not in counts.columns:
            counts[year] = 0
    complete = counts[(counts[fiscal_years] > 0).all(axis=1)]
    names = rows.groupby("lei")["entity_name"].first()
    out = pd.DataFrame({"lei": complete.index, "entity_name": names.reindex(complete.index).values})
    for year in fiscal_years:
        out[f"n_versions_{year}"] = complete[year].values
    return out.sort_values("entity_name", kind="stable").reset_index(drop=True)


def choose_versions(group: pd.DataFrame) -> list[VersionChoice]:
    """Apply rules R1-R5 to all filings of one issuer and fiscal year."""
    g = group.assign(_id=pd.to_numeric(group["filing_id"])).sort_values("_id")
    decided: dict[str, str] = {}
    pool = g

    def drop(mask: pd.Series, rule: str) -> None:
        nonlocal pool
        for fid in pool.loc[mask, "filing_id"]:
            decided[fid] = rule
        pool = pool[~mask]

    drop(~pool["has_json"].astype(bool), "R1_SENZA_JSON")
    drop(~_usable(pool), "R2_PERIODO_INCOERENTE")
    applied: list[str] = []
    is_it = pool["language_hint"].eq("it").fillna(False).astype(bool)
    if is_it.any() and not is_it.all():
        drop(~is_it, "R3_LINGUA")
        applied.append("R3_LINGUA_IT")
    drop(pool["sha256"].duplicated(keep="first"), "R4_PACCHETTO_IDENTICO")
    if len(pool) > 1:
        latest = pool.sort_values(["date_added", "_id"]).iloc[-1]["filing_id"]
        drop(pool["filing_id"] != latest, "R5_VERSIONE_PRECEDENTE")
        applied.append("R5_PIU_RECENTE")
    if not applied:
        applied.append("UNICA" if len(g) == 1 else "UNICA_RIMASTA")
    chosen_rule = "+".join(applied)
    review = any(rule in applied for rule in ("R3_LINGUA_IT", "R5_PIU_RECENTE"))

    choices = [VersionChoice(fid, False, rule, False) for fid, rule in decided.items()]
    choices += [VersionChoice(fid, True, chosen_rule, review) for fid in pool["filing_id"]]
    return choices


def note_for(rule: str) -> str:
    return " ".join(NOTES[part] for part in rule.split("+"))


def build_proposal(listing: pd.DataFrame, config: SampleConfig) -> tuple[pd.DataFrame, dict]:
    years = config.fiscal_years
    eligible = set(eligible_issuers(listing, years)["lei"])
    not_eligible = [c.lei for c in config.candidates if c.lei not in eligible]
    if not_eligible:
        raise ValueError(f"candidates without usable filings for all of {years}: {not_eligible}")

    filings = calendar_year_filings(listing, years)
    rows = []
    for cand in config.candidates:
        for year in years:
            versions = filings[(filings["lei"] == cand.lei) & (filings["fiscal_year"] == year)]
            choices = {c.filing_id: c for c in choose_versions(versions)}
            for _, f in versions.iterrows():
                choice = choices[f["filing_id"]]
                rows.append({
                    "proposal_status": "PROPOSTA - DA APPROVARE" if not config.is_approved else "APPROVATA",
                    "group": cand.group,
                    "issuer": cand.issuer,
                    "entity_name_api": f["entity_name"],
                    "lei": cand.lei,
                    "sector_proposed": cand.sector_proposed,
                    "index_proposed": cand.index_proposed,
                    "star_proposed": "Y" if cand.star_proposed else "N",
                    "classification_status": "DA VERIFICARE",
                    "rationale": cand.rationale,
                    "fiscal_year": year,
                    "period_end": f["period_end"],
                    "n_versions": len(versions),
                    "proposed_use": "Y" if choice.proposed else "N",
                    "version_rule": choice.rule,
                    "version_note": note_for(choice.rule),
                    "needs_review": "Y" if choice.needs_review else "N",
                    **{col: f[col] for col in (
                        "filing_id", "fxo_id", "date_added", "language_hint", "package_format",
                        "error_count", "warning_count", "inconsistency_count", "sha256",
                        "json_url", "package_url",
                    )},
                })
    proposal = pd.DataFrame(rows, columns=PROPOSAL_COLUMNS)
    return proposal, summarize(proposal, config)


def summarize(proposal: pd.DataFrame, config: SampleConfig) -> dict:
    issuers = proposal.drop_duplicates("lei")
    by_group = issuers["group"].value_counts().to_dict()
    warnings = []
    for group, (lo, hi) in config.targets.items():
        n = by_group.get(group, 0)
        if not lo <= n <= hi:
            warnings.append(f"gruppo {group}: {n} emittenti, atteso tra {lo} e {hi}")
    chosen = proposal[proposal["proposed_use"] == "Y"]
    per_year = chosen.groupby(["lei", "fiscal_year"]).size()
    if (per_year != 1).any():
        warnings.append("almeno un emittente/esercizio non ha esattamente una versione proposta")
    return {
        "status": config.status,
        "n_issuers": int(len(issuers)),
        "by_group": by_group,
        "by_index_proposed": issuers["index_proposed"].value_counts().to_dict(),
        "star_proposed": int((issuers["star_proposed"] == "Y").sum()),
        "issuer_years_with_multiple_versions": int((proposal.groupby(["lei", "fiscal_year"]).size() > 1).sum()),
        "choices_needing_review": int((chosen["needs_review"] == "Y").sum()),
        "warnings": warnings,
    }


def write_proposal(listing: pd.DataFrame, config: SampleConfig, interim_dir: Path) -> tuple[Path, dict]:
    proposal, summary = build_proposal(listing, config)
    interim_dir.mkdir(parents=True, exist_ok=True)
    out = interim_dir / "sample_proposal.csv"
    proposal.to_csv(out, index=False)
    eligible_issuers(listing, config.fiscal_years).to_csv(interim_dir / "eligible_issuers.csv", index=False)
    (interim_dir / "sample_proposal.summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return out, summary
