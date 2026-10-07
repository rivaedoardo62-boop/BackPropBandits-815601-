"""Client for the filings.xbrl.org JSON:API (https://filings.xbrl.org/docs/api).

Endpoint, filter and attribute names used here were verified with the probe
requests documented in docs/api_notes.md (``python -m extraction verify-api``).
Only the API host is ever contacted: URLs pointing elsewhere are refused.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlsplit

from extraction.sources.http import PoliteSession

JSONAPI_MEDIA_TYPE = "application/vnd.api+json"
FILINGS_PATH = "/api/filings"
ENTITIES_PATH = "/api/entities"


class ApiError(RuntimeError):
    """The API answered with something we cannot interpret safely."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class ApiPage:
    url: str
    status: int
    fetched_at: str
    body: bytes = field(repr=False)
    sha256: str
    document: dict = field(repr=False)


class FilingsApi:
    def __init__(self, http: PoliteSession, base_url: str) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")
        parts = urlsplit(self.base_url)
        if parts.scheme != "https" or not parts.netloc:
            raise ValueError(f"invalid API base URL: {base_url}")
        self._host = parts.netloc

    def absolute_url(self, path_or_url: str | None) -> str | None:
        """Turn an API link (relative or absolute) into an absolute URL on the API host."""
        if not path_or_url:
            return None
        if path_or_url.startswith(("http://", "https://")):
            self.check_same_host(path_or_url)
            return path_or_url
        if not path_or_url.startswith("/"):
            raise ApiError(f"unexpected relative link: {path_or_url!r}")
        return self.base_url + path_or_url

    def check_same_host(self, url: str) -> None:
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.netloc != self._host:
            raise ApiError(f"refusing to contact a host other than {self._host}: {url}")

    def get_document(self, path_or_url: str, params: dict[str, str] | None = None) -> ApiPage:
        url = self.absolute_url(path_or_url)
        response = self.http.get(url, params=params, headers={"Accept": JSONAPI_MEDIA_TYPE})
        fetched_at = utc_now_iso()
        if response.status_code != 200:
            raise ApiError(
                f"GET {response.url} -> HTTP {response.status_code}: {response.text[:300]!r}"
            )
        body = response.content
        try:
            document = json.loads(body)
        except ValueError as exc:
            raise ApiError(f"GET {response.url}: the response is not JSON") from exc
        if not isinstance(document, dict) or "data" not in document:
            raise ApiError(f"GET {response.url}: not a JSON:API document")
        return ApiPage(
            url=response.url,
            status=response.status_code,
            fetched_at=fetched_at,
            body=body,
            sha256=hashlib.sha256(body).hexdigest(),
            document=document,
        )

    def iter_filing_pages(
        self, *, country: str, page_size: int = 200, sort: str = "id"
    ) -> Iterator[ApiPage]:
        """Yield every page of ``/api/filings?filter[country]=<country>&include=entity``.

        Pagination follows ``links.next``. A stable sort key keeps the pages
        consistent if new filings are added while we paginate.
        """
        if not 1 <= page_size <= 200:
            raise ValueError("page_size must be between 1 and 200")
        params = {
            "filter[country]": country,
            "include": "entity",
            "page[size]": str(page_size),
            "sort": sort,
        }
        page = self.get_document(FILINGS_PATH, params=params)
        expected = (page.document.get("meta") or {}).get("count")
        max_pages = expected // page_size + 2 if isinstance(expected, int) else 10_000
        fetched = 0
        while True:
            yield page
            fetched += 1
            next_url = (page.document.get("links") or {}).get("next")
            if not next_url or not page.document.get("data"):
                return
            if fetched >= max_pages:
                raise ApiError(f"pagination did not stop after {fetched} pages")
            page = self.get_document(next_url)
