"""Build the index of all filings of a country from the filings.xbrl.org API.

Every API page is stored unchanged under data/raw/api/ with its SHA-256, so
that each row of the index can be traced back to the response it came from.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from extraction.schema.filings import INDEX_COLUMNS, FilingRecord, lei_checksum_ok
from extraction.sources.filings_api import ApiError, FilingsApi, utc_now_iso

log = logging.getLogger(__name__)

# Attributes that must be present in every filing resource. A missing key (as
# opposed to a null value) means the API changed: we stop instead of writing
# empty columns.
REQUIRED_FILING_ATTRIBUTES = (
    "fxo_id",
    "country",
    "period_end",
    "date_added",
    "processed",
    "sha256",
    "json_url",
    "package_url",
    "viewer_url",
    "error_count",
    "warning_count",
    "inconsistency_count",
)
REQUIRED_ENTITY_ATTRIBUTES = ("identifier", "name")


def parse_filings_page(document: dict, api: FilingsApi, snapshot_at: str) -> list[FilingRecord]:
    included = {
        (item.get("type"), item.get("id")): item for item in document.get("included") or []
    }
    records = []
    for item in document.get("data") or []:
        if item.get("type") != "filing":
            raise ApiError(f"unexpected resource type {item.get('type')!r}")
        attrs = item.get("attributes") or {}
        missing = [key for key in REQUIRED_FILING_ATTRIBUTES if key not in attrs]
        if missing:
            raise ApiError(f"filing {item.get('id')}: missing attributes {missing}")
        ref = ((item.get("relationships") or {}).get("entity") or {}).get("data")
        entity = included.get((ref.get("type"), ref.get("id"))) if ref else None
        if entity is None:
            raise ApiError(f"filing {item.get('id')}: entity not found in 'included'")
        entity_attrs = entity.get("attributes") or {}
        missing = [key for key in REQUIRED_ENTITY_ATTRIBUTES if key not in entity_attrs]
        if missing:
            raise ApiError(f"entity {entity.get('id')}: missing attributes {missing}")
        lei = str(entity_attrs["identifier"]).strip()
        records.append(
            FilingRecord(
                filing_id=str(item["id"]),
                fxo_id=attrs["fxo_id"],
                lei=lei,
                lei_checksum_ok=lei_checksum_ok(lei),
                entity_name=str(entity_attrs["name"]).strip(),
                country=attrs["country"],
                period_end=attrs["period_end"],
                language=None,
                date_added=attrs["date_added"],
                processed=attrs["processed"],
                sha256=attrs["sha256"],
                json_url=api.absolute_url(attrs["json_url"]),
                package_url=api.absolute_url(attrs["package_url"]),
                viewer_url=api.absolute_url(attrs["viewer_url"]),
                error_count=attrs["error_count"],
                warning_count=attrs["warning_count"],
                inconsistency_count=attrs["inconsistency_count"],
                snapshot_at=snapshot_at,
            )
        )
    return records


def build_filings_index(
    api: FilingsApi, *, country: str, raw_dir: Path, page_size: int = 200
) -> tuple[pd.DataFrame, dict]:
    """Download every page for ``country``; return the index and its provenance metadata."""
    snapshot_at = utc_now_iso()
    stamp = snapshot_at.replace("-", "").replace(":", "").replace("+0000", "Z")
    pages_dir = raw_dir / "api" / f"filings_{country.lower()}_{stamp}"
    pages_dir.mkdir(parents=True, exist_ok=False)

    records: list[FilingRecord] = []
    pages_log = []
    expected_count = None
    for number, page in enumerate(
        api.iter_filing_pages(country=country, page_size=page_size), start=1
    ):
        if expected_count is None:
            expected_count = (page.document.get("meta") or {}).get("count")
        path = pages_dir / f"page_{number:04d}.json"
        path.write_bytes(page.body)
        page_records = parse_filings_page(page.document, api, snapshot_at)
        records.extend(page_records)
        pages_log.append(
            {
                "page": number,
                "url": page.url,
                "fetched_at": page.fetched_at,
                "sha256": page.sha256,
                "file": path.name,
                "records": len(page_records),
            }
        )
        log.info("page %d: %d filings", number, len(page_records))

    frame = pd.DataFrame([record.model_dump() for record in records], columns=INDEX_COLUMNS)
    duplicated = frame["filing_id"].duplicated()
    if duplicated.any():
        raise ApiError(f"duplicated filing ids across pages: {frame.loc[duplicated, 'filing_id'].tolist()}")
    if expected_count is not None and len(frame) != expected_count:
        raise ApiError(f"API announced {expected_count} filings, received {len(frame)}")
    frame = frame.sort_values(["lei", "period_end", "filing_id"], kind="stable").reset_index(drop=True)

    metadata = {
        "source": api.base_url,
        "endpoint": "/api/filings",
        "country": country,
        "snapshot_at": snapshot_at,
        "user_agent": api.http.user_agent,
        "announced_count": expected_count,
        "records": len(frame),
        "entities": int(frame["lei"].nunique()),
        "raw_pages_dir": str(pages_dir),
        "pages": pages_log,
    }
    return frame, metadata


def write_filings_index(frame: pd.DataFrame, metadata: dict, csv_path: Path) -> Path:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(csv_path, index=False, encoding="utf-8")
    meta_path = csv_path.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta_path


def read_filings_index(csv_path: Path) -> pd.DataFrame:
    """Read the index back with explicit dtypes (identifiers stay strings)."""
    return pd.read_csv(
        csv_path,
        dtype={
            "filing_id": "string",
            "fxo_id": "string",
            "lei": "string",
            "entity_name": "string",
            "country": "string",
            "language": "string",
            "sha256": "string",
            "json_url": "string",
            "package_url": "string",
            "viewer_url": "string",
            "date_added": "string",
            "processed": "string",
            "snapshot_at": "string",
            "error_count": "Int64",
            "warning_count": "Int64",
            "inconsistency_count": "Int64",
        },
        parse_dates=["period_end"],
        keep_default_na=False,
        na_values=[""],
    )
