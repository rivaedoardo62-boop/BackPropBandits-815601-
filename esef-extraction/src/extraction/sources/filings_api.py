"""Elenco delle relazioni ESEF da filings.xbrl.org (API JSON:API).

Nomi di filtri e attributi verificati con richieste di prova: vedi docs/api_notes.md.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from urllib.parse import urljoin, urlparse

import pandas as pd

from extraction.sources.http import PoliteSession

BASE_URL = "https://filings.xbrl.org"
FILINGS_ENDPOINT = f"{BASE_URL}/api/filings"

# fxo_id osservato: "<LEI>-<period_end>-ESEF-<country>-<seq>"
FXO_ID_RE = re.compile(
    r"^(?P<lei>[A-Z0-9]{20})-(?P<period_end>\d{4}-\d{2}-\d{2})-(?P<system>[A-Z]+)-(?P<country>[A-Z]{2})-(?P<seq>\d+)$"
)
LEI_RE = re.compile(r"^[A-Z0-9]{18}[0-9]{2}$")

FILINGS_COLUMNS = [
    "filing_id",
    "fxo_id",
    "filing_seq",
    "entity_name",
    "lei",
    "lei_checksum_ok",
    "country",
    "period_end",
    "lang_hint_from_filename",
    "json_filename_date",
    "date_added",
    "processed",
    "api_sha256",
    "json_url",
    "package_url",
    "report_url",
    "viewer_url",
    "error_count",
    "warning_count",
    "inconsistency_count",
    "retrieved_at",
]


def lei_checksum_ok(lei: str | None) -> bool:
    """Verifica le cifre di controllo ISO 17442 (ISO 7064 MOD 97-10)."""
    if not lei or not LEI_RE.match(lei):
        return False
    digits = "".join(str(int(ch, 36)) for ch in lei)
    return int(digits) % 97 == 1


def lang_hint_from_filename(url: str | None) -> str | None:
    """Indizio di lingua dal nome del file, solo se segue lo schema <base>-<data>[-<n>]-<xx>.

    L'API non espone la lingua. Lo schema di nome è una raccomandazione ESMA, non un
    obbligo, e "IT" potrebbe anche indicare il Paese: il valore è un indizio, non un dato.
    """
    if not url:
        return None
    stem = Path(urlparse(url).path).stem
    m = re.fullmatch(r".+-\d{4}-\d{2}-\d{2}(?:-\d+)?-([A-Za-z]{2})", stem)
    return m.group(1).lower() if m else None


def date_in_filename(url: str | None) -> str | None:
    """Data AAAA-MM-GG contenuta nel nome del file (serve a controllare period_end)."""
    if not url:
        return None
    m = re.search(r"\d{4}-\d{2}-\d{2}", Path(urlparse(url).path).name)
    return m.group(0) if m else None


def _absolute(url: str | None) -> str | None:
    return urljoin(BASE_URL + "/", url) if url else None


def flatten_filing(item: dict, entity: dict | None, retrieved_at: str) -> dict:
    attrs = item.get("attributes", {})
    ent_attrs = (entity or {}).get("attributes", {})
    lei = ent_attrs.get("identifier")
    fxo_id = attrs.get("fxo_id")
    m = FXO_ID_RE.match(fxo_id or "")
    return {
        "filing_id": item.get("id"),
        "fxo_id": fxo_id,
        "filing_seq": int(m.group("seq")) if m else None,
        "entity_name": ent_attrs.get("name"),
        "lei": lei,
        "lei_checksum_ok": lei_checksum_ok(lei),
        "country": attrs.get("country"),
        "period_end": attrs.get("period_end"),
        # Il nome del file JSON riporta il suffisso di lingua più spesso del pacchetto.
        "lang_hint_from_filename": (
            lang_hint_from_filename(attrs.get("json_url"))
            or lang_hint_from_filename(attrs.get("package_url"))
        ),
        # period_end dell'API non è sempre affidabile (es. 2032-12-31 per una relazione 2022):
        # si confronta con la data nel nome del file JSON, senza correggere nulla.
        "json_filename_date": date_in_filename(attrs.get("json_url")),
        "date_added": attrs.get("date_added"),
        "processed": attrs.get("processed"),
        "api_sha256": attrs.get("sha256"),
        "json_url": _absolute(attrs.get("json_url")),
        "package_url": _absolute(attrs.get("package_url")),
        "report_url": _absolute(attrs.get("report_url")),
        "viewer_url": _absolute(attrs.get("viewer_url")),
        "error_count": attrs.get("error_count"),
        "warning_count": attrs.get("warning_count"),
        "inconsistency_count": attrs.get("inconsistency_count"),
        "retrieved_at": retrieved_at,
    }


def iter_filing_pages(
    session: PoliteSession, country: str, page_size: int = 200
) -> Iterator[dict]:
    """Segue links.next fino all'ultima pagina. Ordinamento per id per una paginazione stabile."""
    url: str | None = FILINGS_ENDPOINT
    params: dict | None = {
        "filter[country]": country,
        "include": "entity",
        "sort": "id",
        "page[size]": page_size,
    }
    while url:
        payload = session.get(url, params=params).json()
        if "errors" in payload:
            raise RuntimeError(f"errore API: {payload['errors']}")
        yield payload
        url = payload.get("links", {}).get("next")
        params = None  # il link "next" contiene già la query completa


def rows_from_pages(pages: list[dict], retrieved_at: str) -> list[dict]:
    rows: dict[str, dict] = {}
    for payload in pages:
        included = {(e["type"], e["id"]): e for e in payload.get("included", [])}
        for item in payload.get("data", []):
            ref = (item.get("relationships", {}).get("entity", {}) or {}).get("data") or {}
            entity = included.get((ref.get("type"), ref.get("id")))
            rows[item["id"]] = flatten_filing(item, entity, retrieved_at)
    return list(rows.values())


def save_pages(pages: list[dict], page_dir: Path, retrieved_at: str, request_url: str) -> None:
    """Conserva le risposte grezze dell'API per tracciabilità e rielaborazione offline."""
    page_dir.mkdir(parents=True, exist_ok=True)
    for i, payload in enumerate(pages, start=1):
        (page_dir / f"page_{i:03d}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    meta = {"retrieved_at": retrieved_at, "request_url": request_url, "pages": len(pages)}
    (page_dir / "_meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")


def load_pages(page_dir: Path) -> tuple[list[dict], str]:
    meta = json.loads((page_dir / "_meta.json").read_text(encoding="utf-8"))
    pages = [
        json.loads(p.read_text(encoding="utf-8")) for p in sorted(page_dir.glob("page_*.json"))
    ]
    if len(pages) != meta["pages"]:
        raise RuntimeError(f"{page_dir}: attese {meta['pages']} pagine, trovate {len(pages)}")
    return pages, meta["retrieved_at"]


def fetch_filings(
    session: PoliteSession,
    country: str,
    out_csv: Path,
    raw_dir: Path,
    page_size: int = 200,
) -> pd.DataFrame:
    now = datetime.now(timezone.utc)
    retrieved_at = now.isoformat(timespec="seconds")
    pages = list(iter_filing_pages(session, country, page_size))
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    save_pages(
        pages,
        raw_dir / f"filings_{country.lower()}_{stamp}",
        retrieved_at,
        request_url=pages[0]["links"]["self"] if pages else FILINGS_ENDPOINT,
    )
    return write_filings_csv(pages, retrieved_at, out_csv)


def write_filings_csv(pages: list[dict], retrieved_at: str, out_csv: Path) -> pd.DataFrame:
    rows = rows_from_pages(pages, retrieved_at)
    expected = pages[0].get("meta", {}).get("count") if pages else 0
    if expected is not None and expected != len(rows):
        raise RuntimeError(f"attese {expected} relazioni, ottenute {len(rows)} righe distinte")
    df = pd.DataFrame(rows, columns=FILINGS_COLUMNS)
    df = df.sort_values(["lei", "period_end", "date_added", "filing_id"], kind="stable")
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)
    return df
