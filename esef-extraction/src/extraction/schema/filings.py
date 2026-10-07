"""Row contract of data/interim/filings_<country>.csv (one row per filing)."""

from __future__ import annotations

import re
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

LEI_RE = re.compile(r"^[A-Z0-9]{18}[0-9]{2}$")
SHA256_RE = r"^[0-9a-f]{64}$"


def lei_checksum_ok(lei: str) -> bool:
    """ISO 17442 check digits (ISO 7064 MOD 97-10) on a 20-character LEI."""
    if not LEI_RE.match(lei):
        return False
    return int("".join(str(int(char, 36)) for char in lei)) % 97 == 1


class FilingRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    filing_id: str
    fxo_id: str
    lei: str
    lei_checksum_ok: bool
    entity_name: str
    country: str
    period_end: date
    # filings.xbrl.org does not expose the report language (verified, see
    # docs/api_notes.md): the column is kept empty instead of being guessed.
    language: str | None = None
    date_added: str | None
    processed: str | None
    sha256: str | None = Field(default=None, pattern=SHA256_RE)
    json_url: str | None
    package_url: str | None
    viewer_url: str | None
    error_count: int | None
    warning_count: int | None
    inconsistency_count: int | None
    snapshot_at: str


INDEX_COLUMNS: list[str] = list(FilingRecord.model_fields)
