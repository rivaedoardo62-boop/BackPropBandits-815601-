"""Passo 2: elenco completo delle relazioni di un Paese da filings.xbrl.org.

Output: data/interim/filings_<cc>.csv (una riga per relazione) + .meta.json con la
provenienza dell'elenco; le pagine JSON grezze dell'API sono salvate in
data/raw/api/filings_<cc>/<timestamp>/ per poter ricostruire l'elenco.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from extraction.sources.filings_api import FilingsApiClient

# Column order: first the fields requested for the listing, then the auxiliary ones.
LISTING_COLUMNS = [
    "entity_name",
    "lei",
    "period_end",
    "language_hint",
    "date_added",
    "sha256",
    "json_url",
    "package_url",
    "error_count",
    "warning_count",
    "inconsistency_count",
    "filing_id",
    "fxo_id",
    "fxo_seq",
    "country",
    "processed",
    "report_url",
    "viewer_url",
    "json_filename",
    "package_filename",
    "package_format",
    "has_json",
    "filename_date",
    "period_end_matches_filename",
    "lei_matches_fxo_id",
    "is_calendar_year_end",
    "n_filings_same_lei_period",
]

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
# Literal two-letter token at the end of the report file name (e.g. "...-it.json").
# It is chosen by the issuer: a hint, not a verified language (see docs/api_notes.md).
_LANG_SUFFIX_RE = re.compile(r"-([A-Za-z]{2})\.json$")


def _basename(url: Any) -> str | None:
    return url.rsplit("/", 1)[-1] if isinstance(url, str) and url else None


def language_hint(json_url: Any) -> str | None:
    name = _basename(json_url)
    match = _LANG_SUFFIX_RE.search(name) if name else None
    return match.group(1).lower() if match else None


def filename_date(json_url: Any, package_url: Any) -> str | None:
    for url in (json_url, package_url):
        name = _basename(url)
        match = _DATE_RE.search(name) if name else None
        if match:
            return match.group(1)
    return None


def build_listing(records: Iterable[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(list(records))
    if df.empty:
        return pd.DataFrame(columns=LISTING_COLUMNS)
    df["json_filename"] = df["json_url"].map(_basename)
    df["package_filename"] = df["package_url"].map(_basename)
    df["package_format"] = df["package_filename"].map(
        lambda n: n.rsplit(".", 1)[-1].lower() if isinstance(n, str) and "." in n else None
    )
    df["language_hint"] = df["json_url"].map(language_hint)
    df["has_json"] = df["json_url"].map(lambda u: isinstance(u, str) and bool(u))
    df["fxo_seq"] = pd.to_numeric(df["fxo_id"].str.rsplit("-", n=1).str[-1], errors="coerce").astype("Int64")
    # Compare on the plain list: once stored in a DataFrame, None becomes NaN.
    dates = [filename_date(j, p) for j, p in zip(df["json_url"], df["package_url"])]
    df["filename_date"] = dates
    df["period_end_matches_filename"] = pd.Series(
        [None if d is None else d == pe for d, pe in zip(dates, df["period_end"])],
        dtype="boolean",
        index=df.index,
    )
    df["lei_matches_fxo_id"] = [
        isinstance(lei, str) and isinstance(fxo, str) and fxo.startswith(lei + "-")
        for lei, fxo in zip(df["lei"], df["fxo_id"])
    ]
    df["is_calendar_year_end"] = df["period_end"].astype("string").str.endswith("-12-31").fillna(False)
    df["n_filings_same_lei_period"] = df.groupby(["lei", "period_end"], dropna=False)["filing_id"].transform("size")
    df["filing_id_num"] = pd.to_numeric(df["filing_id"])
    df = df.sort_values(["entity_name", "period_end", "filing_id_num"], kind="stable")
    return df[LISTING_COLUMNS].reset_index(drop=True)


_STRING_COLUMNS = (
    "entity_name", "lei", "period_end", "language_hint", "date_added", "sha256", "json_url",
    "package_url", "filing_id", "fxo_id", "country", "processed", "report_url", "viewer_url",
    "json_filename", "package_filename", "package_format", "filename_date",
)


def read_listing(path: Path) -> pd.DataFrame:
    """Read a listing CSV keeping identifiers (LEI, filing id, hashes) as strings."""
    df = pd.read_csv(path, dtype={c: "string" for c in _STRING_COLUMNS}, keep_default_na=False, na_values=[""])
    for col in ("has_json", "lei_matches_fxo_id", "is_calendar_year_end", "period_end_matches_filename"):
        df[col] = df[col].astype("boolean")
    return df


def fetch_country_listing(
    client: FilingsApiClient,
    country: str,
    interim_dir: Path,
    raw_dir: Path,
) -> tuple[pd.DataFrame, Path]:
    """Download the full listing for ``country`` and write CSV, metadata and raw API pages."""
    started = datetime.now(timezone.utc)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    records = list(client.iter_filings(simple_filters={"country": country}))
    df = build_listing(records)

    cc = country.lower()
    snapshot_dir = raw_dir / "api" / f"filings_{cc}" / stamp
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    for i, page in enumerate(client.pages_fetched, start=1):
        (snapshot_dir / f"page-{i:04d}.json").write_text(json.dumps(page, ensure_ascii=False), encoding="utf-8")

    interim_dir.mkdir(parents=True, exist_ok=True)
    csv_path = interim_dir / f"filings_{cc}.csv"
    df.to_csv(csv_path, index=False)
    meta = {
        "source": "filings.xbrl.org JSON:API",
        "endpoint": client.base_url + "/api/filings",
        "query": {"filter[country]": country, "page[size]": client.page_size, "include": "entity", "sort": "id"},
        "retrieved_at_utc": started.isoformat(timespec="seconds"),
        "user_agent": client.http.user_agent,
        "pages": len(client.pages_fetched),
        "api_meta_count": client.pages_fetched[-1].get("meta", {}).get("count") if client.pages_fetched else 0,
        "rows": int(len(df)),
        "raw_pages_dir": snapshot_dir.relative_to(raw_dir.parent).as_posix(),
        "notes": "language_hint e' il suffisso del nome file scelto dall'emittente, non una lingua verificata.",
    }
    csv_path.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return df, csv_path
