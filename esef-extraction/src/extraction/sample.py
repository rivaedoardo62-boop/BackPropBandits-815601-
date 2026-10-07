"""Passo 3: emittenti candidati e proposta di campione.

Regole di scelta della versione (proposta, da confermare: vedi README "Decisioni aperte"):
  1. si escludono le relazioni senza xBRL-JSON;
  2. se esistono versioni in lingue diverse si preferisce `preferred_lang` (indizio dal nome file);
  3. tra le rimanenti si propone quella aggiunta per ultima a filings.xbrl.org.
Ogni caso con più versioni viene segnalato, non risolto in silenzio.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

VERSION_CASE_SINGLE = "single"
VERSION_CASE_LANG = "language_versions"
VERSION_CASE_SAME_HASH = "identical_duplicates"
VERSION_CASE_REFILING = "refiling_different_hash"

ALLOWED_GROUPS = {"industrial_services", "utility", "bank", "insurance"}


def add_fiscal_year(df: pd.DataFrame) -> pd.DataFrame:
    """Esercizio = anno della data di fine periodo.

    Per gli esercizi non solari (es. chiusura al 31 gennaio) la convenzione è ambigua:
    vengono marcati con non_calendar_fy=True e non entrano nella proposta.
    """
    out = df.copy()
    pe = pd.to_datetime(out["period_end"], format="%Y-%m-%d")
    out["fiscal_year"] = pe.dt.year
    out["non_calendar_fy"] = ~((pe.dt.month == 12) & (pe.dt.day == 31))
    # Segnalazione, non correzione: il periodo effettivo va letto dai fact (Passo 6).
    fn_date = out["json_filename_date"]
    out["period_end_filename_mismatch"] = fn_date.notna() & (fn_date != out["period_end"])
    return out


def classify_versions(group: pd.DataFrame) -> str:
    if len(group) == 1:
        return VERSION_CASE_SINGLE
    langs = group["lang_hint_from_filename"].dropna().unique()
    if len(langs) > 1:
        return VERSION_CASE_LANG
    if group["api_sha256"].nunique() == 1:
        return VERSION_CASE_SAME_HASH
    return VERSION_CASE_REFILING


def _pick(group: pd.DataFrame, preferred_lang: str) -> tuple[str | None, str]:
    usable = group[group["json_url"].notna()]
    if usable.empty:
        return None, "nessuna versione con xBRL-JSON"
    notes = []
    if usable["lang_hint_from_filename"].nunique() > 1:
        same_lang = usable[usable["lang_hint_from_filename"] == preferred_lang]
        if not same_lang.empty:
            usable = same_lang
            notes.append(f"preferita lingua '{preferred_lang}' (indizio da nome file)")
    if len(usable) > 1:
        notes.append("scelta la versione aggiunta per ultima (date_added)")
    chosen = usable.sort_values(["date_added", "filing_id"]).iloc[-1]
    return str(chosen["filing_id"]), "; ".join(notes)


def build_candidates(
    filings_csv: Path,
    out_csv: Path,
    fiscal_years: tuple[int, ...] = (2024, 2025),
    preferred_lang: str = "it",
) -> pd.DataFrame:
    """Una riga per relazione, solo per emittenti con xBRL-JSON per tutti gli esercizi richiesti."""
    df = add_fiscal_year(pd.read_csv(filings_csv, dtype={"filing_id": str}))
    df = df[df["fiscal_year"].isin(fiscal_years) & ~df["non_calendar_fy"]].copy()

    keys = ["lei", "fiscal_year"]
    df["n_versions"] = df.groupby(keys)["filing_id"].transform("size")
    case = df.groupby(keys)[df.columns.tolist()].apply(classify_versions).rename("version_case")
    picks = df.groupby(keys)[df.columns.tolist()].apply(lambda g: _pick(g, preferred_lang))
    picks = pd.DataFrame(picks.tolist(), index=picks.index, columns=["proposed_filing_id", "version_note"])
    df = df.join(case, on=keys).join(picks, on=keys)
    df["proposed_version"] = df["filing_id"] == df["proposed_filing_id"]

    has_json = df[df["proposed_filing_id"].notna()].groupby("lei")["fiscal_year"].nunique()
    complete = has_json[has_json == len(fiscal_years)].index
    out = df[df["lei"].isin(complete)].drop(columns=["proposed_filing_id"])
    out = out.sort_values(["entity_name", "fiscal_year", "date_added"], kind="stable")
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_csv, index=False)
    return out


PROPOSAL_COLUMNS = [
    "lei",
    "issuer",
    "proposed_group",
    "proposed_sector",
    "proposed_market_segment",
    "classification_status",
    "fiscal_year",
    "period_end",
    "period_end_filename_mismatch",
    "proposed_version",
    "n_versions",
    "version_case",
    "version_note",
    "filing_id",
    "fxo_id",
    "lang_hint_from_filename",
    "date_added",
    "error_count",
    "warning_count",
    "inconsistency_count",
    "api_sha256",
    "json_url",
    "package_url",
    "selection_rationale",
]


def load_proposal_config(path: Path) -> list[dict]:
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    issuers = cfg["issuers"]
    seen = set()
    for item in issuers:
        if item["proposed_group"] not in ALLOWED_GROUPS:
            raise ValueError(f"{item['lei']}: proposed_group non valido {item['proposed_group']!r}")
        if item["lei"] in seen:
            raise ValueError(f"LEI duplicato nella proposta: {item['lei']}")
        seen.add(item["lei"])
    return issuers


def build_proposal(proposal_yaml: Path, candidates_csv: Path, out_csv: Path) -> pd.DataFrame:
    """Unisce la proposta (settore e segmento indicati a mano, da verificare) con le relazioni.

    Include tutte le versioni di ogni esercizio, con la colonna proposed_version.
    """
    issuers = load_proposal_config(proposal_yaml)
    cand = pd.read_csv(candidates_csv, dtype={"filing_id": str})
    meta = pd.DataFrame(issuers)
    missing = sorted(set(meta["lei"]) - set(cand["lei"]))
    if missing:
        raise ValueError(f"LEI proposti senza relazioni utilizzabili per tutti gli esercizi: {missing}")
    merged = meta.merge(cand, on="lei", how="left", validate="one_to_many")
    merged["issuer"] = merged["entity_name"]
    merged["classification_status"] = "DA VERIFICARE"
    out = merged[PROPOSAL_COLUMNS].sort_values(
        ["proposed_group", "issuer", "fiscal_year", "date_added"], kind="stable"
    )
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_csv, index=False)
    return out
