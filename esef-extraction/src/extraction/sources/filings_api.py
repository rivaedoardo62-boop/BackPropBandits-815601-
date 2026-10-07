"""Client for the filings.xbrl.org JSON:API (https://filings.xbrl.org/docs/api).

Names below were verified against the live API; see docs/api_notes.md.
"""

from __future__ import annotations

import json
from typing import Any, Iterator
from urllib.parse import urljoin

from extraction.sources.http import PoliteSession

FILINGS_PATH = "/api/filings"

# Filing attributes returned by the API (verified on 2026-10-07).
FILING_ATTRIBUTES = (
    "fxo_id",
    "country",
    "period_end",
    "date_added",
    "processed",
    "sha256",
    "json_url",
    "package_url",
    "report_url",
    "viewer_url",
    "error_count",
    "warning_count",
    "inconsistency_count",
)
URL_ATTRIBUTES = ("json_url", "package_url", "report_url", "viewer_url")


class ApiConsistencyError(RuntimeError):
    """The API returned something that contradicts its own metadata."""


class FilingsApiClient:
    def __init__(self, http: PoliteSession, base_url: str, page_size: int = 200) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")
        self.page_size = page_size
        self.pages_fetched: list[dict[str, Any]] = []

    def absolute(self, path: str | None) -> str | None:
        return urljoin(self.base_url + "/", path.lstrip("/")) if path else None

    def iter_filings(
        self,
        simple_filters: dict[str, str] | None = None,
        filters: list[dict[str, Any]] | None = None,
        sort: str = "id",
    ) -> Iterator[dict[str, Any]]:
        """Yield one flat record per filing, following ``links.next`` until exhausted.

        ``simple_filters`` become ``filter[<attr>]=<value>`` (equality only);
        ``filters`` is the flask-combo-jsonapi list syntax, e.g.
        ``[{"name": "period_end", "op": "ge", "val": "2024-01-01"}]``.
        Sorting by ``id`` keeps the pagination stable while the index grows.
        """
        params: dict[str, Any] | None = {
            "page[size]": self.page_size,
            "include": "entity",
            "sort": sort,
        }
        for name, value in (simple_filters or {}).items():
            params[f"filter[{name}]"] = value
        if filters:
            params["filter"] = json.dumps(filters)

        url: str | None = self.base_url + FILINGS_PATH
        expected: int | None = None
        seen: set[str] = set()
        while url:
            payload = self.http.get_json(url, params=params)
            self.pages_fetched.append(payload)
            entities = {
                (inc.get("type"), inc.get("id")): inc.get("attributes", {})
                for inc in payload.get("included", [])
            }
            for item in payload.get("data", []):
                if item["id"] in seen:
                    raise ApiConsistencyError(f"filing {item['id']} returned twice while paginating")
                seen.add(item["id"])
                yield self.flatten(item, entities)
            expected = payload.get("meta", {}).get("count", expected)
            url = payload.get("links", {}).get("next")
            params = None  # the next link already carries the full query string
        if expected is not None and len(seen) != expected:
            raise ApiConsistencyError(f"meta.count={expected} but {len(seen)} filings were returned")

    def flatten(self, item: dict[str, Any], entities: dict[tuple, dict[str, Any]]) -> dict[str, Any]:
        attrs = item.get("attributes", {})
        ref = (item.get("relationships", {}).get("entity", {}) or {}).get("data") or {}
        entity = entities.get((ref.get("type"), ref.get("id")), {})
        record: dict[str, Any] = {
            "filing_id": item["id"],
            "entity_name": entity.get("name"),
            "lei": entity.get("identifier"),
        }
        for name in FILING_ATTRIBUTES:
            value = attrs.get(name)
            record[name] = self.absolute(value) if name in URL_ATTRIBUTES else value
        return record
