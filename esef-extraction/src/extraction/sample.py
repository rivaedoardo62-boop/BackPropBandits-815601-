"""Sample proposal (Passo 3): for each issuer and fiscal year, the filing to use.

Input: the filings index (data/interim/filings_it.csv) and config/sample.yaml.
Output: one row per issuer x fiscal year x filing version, so that every
version is visible; ``proposed_version`` marks the one proposed for use.

Version rules (from API metadata only; to be confirmed on the content after
the download):

1. filings without xBRL-JSON are excluded;
2. versions whose file name carries a date different from ``period_end`` are
   set aside as metadata anomalies, if a consistent version exists;
3. one version left -> use it;
4. all versions with the same SHA-256 -> identical packages, use the first
   loaded (lowest filing id);
5. versions whose file names carry distinct language tokens, exactly one
   Italian -> propose the Italian one (the token is only a hint);
6. otherwise no automatic choice: the versions must be compared on content
   (language, consolidated vs separate scope, correction).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from extraction.schema.filings import LEI_RE
from extraction.sources.filings_index import read_filings_index

Status = Literal["proposed", "reserve", "approved", "rejected"]
STATUS_ORDER = {"approved": 0, "proposed": 1, "reserve": 2, "rejected": 3}

_LANG_RE = re.compile(r"[-_](it|en)$", re.IGNORECASE)
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")

PROPOSAL_COLUMNS = [
    "status",
    "issuer_order",
    "lei",
    "entity_name",
    "sector_group",
    "sector_to_verify",
    "segment_to_verify",
    "fiscal_year",
    "period_end",
    "filing_id",
    "fxo_id",
    "n_versions",
    "n_versions_without_json",
    "version_flag",
    "lang_hint_filename",
    "filename_date_mismatch",
    "proposed_version",
    "choice_reason",
    "sha256",
    "json_url",
    "package_url",
    "error_count",
    "warning_count",
    "inconsistency_count",
    "date_added",
    "issuer_note",
]


class SampleIssuer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lei: str
    name: str
    sector_group: str
    sector: str
    segment: str
    status: Status
    note: str | None = None

    @field_validator("lei")
    @classmethod
    def _valid_lei(cls, value: str) -> str:
        if not LEI_RE.match(value):
            raise ValueError(f"not a LEI: {value!r}")
        return value


class SampleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fiscal_years: list[int] = Field(min_length=1)
    period_end_month_day: str = Field(pattern=r"^\d{2}-\d{2}$")
    sector_groups: list[str]
    segments: list[str]
    issuers: list[SampleIssuer]

    @model_validator(mode="after")
    def _consistent(self) -> SampleConfig:
        leis = [issuer.lei for issuer in self.issuers]
        duplicated = sorted({lei for lei in leis if leis.count(lei) > 1})
        if duplicated:
            raise ValueError(f"LEI listed more than once: {duplicated}")
        for issuer in self.issuers:
            if issuer.sector_group not in self.sector_groups:
                raise ValueError(f"{issuer.lei}: unknown sector_group {issuer.sector_group!r}")
            if issuer.segment not in self.segments:
                raise ValueError(f"{issuer.lei}: unknown segment {issuer.segment!r}")
        return self


def load_sample_config(path: Path) -> SampleConfig:
    with Path(path).open(encoding="utf-8") as handle:
        return SampleConfig.model_validate(yaml.safe_load(handle))


def _file_stem(url: object) -> str | None:
    if not isinstance(url, str) or not url:
        return None
    return url.rsplit("/", 1)[-1].rsplit(".", 1)[0]


def lang_hint(json_url: object, package_url: object) -> str | None:
    """Language token at the end of the xBRL-JSON (or package) file name, if any.

    ESEF file names often end in -it/-en, but this is a naming habit, not a
    verified attribute: the value is only a hint.
    """
    for url in (json_url, package_url):
        stem = _file_stem(url)
        match = _LANG_RE.search(stem) if stem else None
        if match:
            return match.group(1).lower()
    return None


def filename_date_mismatch(row: pd.Series) -> bool:
    """True if a date in the JSON or package file name differs from period_end."""
    period_end = row["period_end"].strftime("%Y-%m-%d")
    for url in (row["json_url"], row["package_url"]):
        stem = _file_stem(url)
        dates = _DATE_RE.findall(stem) if stem else []
        if dates and period_end not in dates:
            return True
    return False


def choose_version(versions: pd.DataFrame) -> tuple[str | None, str, str]:
    """Return (filing_id to use or None, version flag, reason). ``versions`` have JSON."""
    candidates = versions
    note = ""
    consistent = versions[~versions["filename_date_mismatch"]]
    if 0 < len(consistent) < len(versions):
        candidates = consistent
        set_aside = ", ".join(versions.loc[versions["filename_date_mismatch"], "filing_id"])
        note = f" Scartate per data nel nome file diversa da period_end: {set_aside}."

    if len(candidates) == 1:
        flag = "unica" if len(versions) == 1 else "versioni multiple: anomalia metadati"
        return candidates["filing_id"].iloc[0], flag, "Unica relazione utilizzabile." + note

    if candidates["sha256"].nunique() == 1:
        first = min(candidates["filing_id"], key=int)
        return (
            first,
            "versioni multiple: pacchetti identici",
            "Stesso SHA-256: copie identiche, si usa la prima caricata (filing_id minore)." + note,
        )

    hints = candidates["lang_hint_filename"]
    italian = candidates[hints == "it"]
    if hints.notna().all() and hints.nunique() == len(candidates) and len(italian) == 1:
        return (
            italian["filing_id"].iloc[0],
            "versioni multiple: lingue diverse (da nome file)",
            "Proposta la versione italiana; lingua indicata solo dal nome file, "
            "da confermare sul contenuto dopo il download." + note,
        )

    return (
        None,
        "versioni multiple: non distinguibili dai metadati",
        "Nessuna proposta automatica: scaricare tutte le versioni e confrontarne il "
        "contenuto (lingua, perimetro consolidato/separato, eventuale rettifica)." + note,
    )


def build_sample_proposal(
    filings_csv: Path, config: SampleConfig
) -> tuple[pd.DataFrame, list[str]]:
    index = read_filings_index(filings_csv)
    index["lang_hint_filename"] = [
        lang_hint(j, p) for j, p in zip(index["json_url"], index["package_url"], strict=True)
    ]
    index["filename_date_mismatch"] = index.apply(filename_date_mismatch, axis=1)

    rows: list[dict] = []
    problems: list[str] = []
    for order, issuer in enumerate(config.issuers, start=1):
        filings = index[index["lei"] == issuer.lei]
        if filings.empty:
            problems.append(f"{issuer.lei} ({issuer.name}): LEI assente dall'indice")
            continue
        base = {
            "status": issuer.status,
            "issuer_order": order,
            "lei": issuer.lei,
            "entity_name": filings["entity_name"].iloc[0],
            "sector_group": issuer.sector_group,
            "sector_to_verify": issuer.sector,
            "segment_to_verify": issuer.segment,
            "issuer_note": issuer.note or "",
        }
        for year in config.fiscal_years:
            period_end = pd.Timestamp(f"{year}-{config.period_end_month_day}")
            same_period = filings[filings["period_end"] == period_end]
            usable = same_period[same_period["json_url"].notna()]
            without_json = len(same_period) - len(usable)
            if usable.empty:
                elsewhere = filings[
                    filings["json_url"].fillna("").str.contains(period_end.strftime("%Y-%m-%d"))
                    | filings["package_url"].fillna("").str.contains(period_end.strftime("%Y-%m-%d"))
                ]
                hint = (
                    f"; file con quella data ma period_end diverso: {', '.join(elsewhere['fxo_id'])}"
                    if not elsewhere.empty
                    else ""
                )
                problems.append(
                    f"{issuer.lei} ({base['entity_name']}): nessuna relazione con xBRL-JSON "
                    f"per period_end {period_end.date()}"
                    f" ({without_json} senza xBRL-JSON){hint}"
                )
                rows.append(
                    {
                        **base,
                        "fiscal_year": year,
                        "period_end": period_end.date(),
                        "n_versions": 0,
                        "n_versions_without_json": without_json,
                        "version_flag": "mancante",
                        "proposed_version": "",
                        "choice_reason": "Nessuna relazione con xBRL-JSON per l'esercizio." + hint,
                    }
                )
                continue

            usable = usable.sort_values("filing_id", key=lambda s: s.astype(int))
            chosen, flag, reason = choose_version(usable)
            if chosen is None:
                problems.append(
                    f"{issuer.lei} ({base['entity_name']}) {year}: {flag} "
                    f"({', '.join(usable['fxo_id'])})"
                )
            for _, filing in usable.iterrows():
                if chosen is None:
                    proposed = ""
                else:
                    proposed = "Y" if filing["filing_id"] == chosen else "N"
                rows.append(
                    {
                        **base,
                        "fiscal_year": year,
                        "period_end": filing["period_end"].date(),
                        "filing_id": filing["filing_id"],
                        "fxo_id": filing["fxo_id"],
                        "n_versions": len(usable),
                        "n_versions_without_json": without_json,
                        "version_flag": flag,
                        "lang_hint_filename": filing["lang_hint_filename"] or "",
                        "filename_date_mismatch": bool(filing["filename_date_mismatch"]),
                        "proposed_version": proposed,
                        "choice_reason": reason,
                        "sha256": filing["sha256"],
                        "json_url": filing["json_url"],
                        "package_url": filing["package_url"],
                        "error_count": filing["error_count"],
                        "warning_count": filing["warning_count"],
                        "inconsistency_count": filing["inconsistency_count"],
                        "date_added": filing["date_added"],
                    }
                )
            if usable["error_count"].fillna(0).max() > 0:
                problems.append(
                    f"{issuer.lei} ({base['entity_name']}) {year}: errori di validazione "
                    "segnalati dall'API"
                )

    proposal = pd.DataFrame(rows, columns=PROPOSAL_COLUMNS)
    proposal["_status_rank"] = proposal["status"].map(STATUS_ORDER)
    proposal = (
        proposal.sort_values(["_status_rank", "issuer_order", "fiscal_year"], kind="stable")
        .drop(columns="_status_rank")
        .reset_index(drop=True)
    )
    return proposal, problems
