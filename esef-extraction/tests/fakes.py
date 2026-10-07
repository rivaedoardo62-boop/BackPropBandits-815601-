"""Test doubles and record builders: no test touches the network."""

from __future__ import annotations

from typing import Any

import requests

BASE = "https://filings.xbrl.org"


class FakeResponse:
    def __init__(self, url: str, status_code: int = 200, payload: Any = None,
                 body: bytes = b"", headers: dict | None = None) -> None:
        self.url = url
        self.status_code = status_code
        self._payload = payload
        self._body = body
        self.headers = headers or {}
        self.closed = False

    def json(self) -> Any:
        return self._payload

    def iter_content(self, chunk_size: int):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i:i + chunk_size]

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def close(self) -> None:
        self.closed = True


class FakeSession:
    """Replays queued responses and records every call."""

    def __init__(self, responses: list[FakeResponse | Exception]) -> None:
        self.headers: dict[str, str] = {}
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeClock:
    """Monotonic clock advanced only by the fake sleep."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make_filing(lei: str = "815600AAAAAAAAAAAA01", period_end: str = "2024-12-31", filing_id: str = "1",
                json_name: str | None = "{lei}-{pe}-it.json", package_name: str = "{lei}-{pe}.zip",
                sha256: str | None = None, date_added: str = "2025-04-15 12:00:00.000000",
                entity_name: str = "ACME S.P.A.", seq: int = 0, error_count: int = 0) -> dict[str, Any]:
    """A flat record shaped like FilingsApiClient.flatten() output."""
    folder = f"{BASE}/{lei}/{period_end}/ESEF/IT/{seq}"
    return {
        "filing_id": filing_id,
        "entity_name": entity_name,
        "lei": lei,
        "fxo_id": f"{lei}-{period_end}-ESEF-IT-{seq}",
        "country": "IT",
        "period_end": period_end,
        "date_added": date_added,
        "processed": date_added,
        "sha256": sha256 or f"{int(filing_id):064x}",
        "json_url": f"{folder}/{json_name.format(lei=lei, pe=period_end)}" if json_name else None,
        "package_url": f"{folder}/{package_name.format(lei=lei, pe=period_end)}",
        "report_url": None,
        "viewer_url": None,
        "error_count": error_count,
        "warning_count": 0,
        "inconsistency_count": 0,
    }
