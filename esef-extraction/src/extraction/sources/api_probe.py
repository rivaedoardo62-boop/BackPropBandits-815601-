"""Probe requests used to verify the filings.xbrl.org API (docs/api_notes.md).

Each probe records the exact request, the HTTP status and what was observed,
so that the verification can be repeated with ``python -m extraction verify-api``.
Downloads made here (one report package and its xBRL-JSON) are hashed in
memory and never written to disk.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from extraction.sources.filings_api import (
    ENTITIES_PATH,
    FILINGS_PATH,
    JSONAPI_MEDIA_TYPE,
    ApiError,
    FilingsApi,
    utc_now_iso,
)

CHUNK = 1 << 16


def _filter(*clauses: dict) -> str:
    return json.dumps(list(clauses), separators=(",", ":"))


def _entity_ids(document: dict) -> set[str]:
    included = {(i["type"], i["id"]): i for i in document.get("included") or []}
    ids = set()
    for item in document.get("data") or []:
        ref = ((item.get("relationships") or {}).get("entity") or {}).get("data") or {}
        entity = included.get((ref.get("type"), ref.get("id")))
        ids.add(entity["attributes"]["identifier"] if entity else "<not included>")
    return ids


class _Probe:
    def __init__(self, api: FilingsApi) -> None:
        self.api = api
        self.results: list[dict[str, Any]] = []

    def run(self, name: str, purpose: str, func: Callable[[], dict]) -> dict:
        try:
            result = func()
        except (ApiError, OSError, ValueError, KeyError) as exc:
            result = {"ok": False, "outcome": f"error: {exc}"}
        result = {"name": name, "purpose": purpose, **result}
        self.results.append(result)
        return result

    def get(self, path: str, params: dict[str, str] | None = None):
        page = self.api.get_document(path, params=params)
        return page, {"request": f"GET {page.url}", "status": page.status}


def run_probes(
    api: FilingsApi, *, country: str, lei: str, period_end: str, download: bool = True
) -> dict:
    probe = _Probe(api)
    target: dict[str, Any] = {}

    def basic() -> dict:
        page, req = probe.get(
            FILINGS_PATH, {"filter[country]": country, "page[size]": "2", "include": "entity"}
        )
        data = page.document["data"]
        filing_attrs = sorted(data[0]["attributes"]) if data else []
        entity_attrs = sorted((page.document.get("included") or [{}])[0].get("attributes", {}))
        countries = {item["attributes"].get("country") for item in data}
        return {
            **req,
            "ok": countries == {country} and bool(filing_attrs),
            "outcome": f"meta.count={page.document.get('meta', {}).get('count')}",
            "filing_attributes": filing_attrs,
            "entity_attributes": entity_attrs,
            "filing_relationships": sorted(data[0].get("relationships", {})) if data else [],
            "links": sorted(page.document.get("links", {})),
        }

    def sort_by_id() -> dict:
        page, req = probe.get(FILINGS_PATH, {"filter[country]": country, "page[size]": "5", "sort": "id"})
        ids = [int(item["id"]) for item in page.document["data"]]
        return {**req, "ok": ids == sorted(ids), "outcome": f"ids={ids}"}

    def lei_has() -> dict:
        flt = _filter({"name": "entity", "op": "has", "val": {"name": "identifier", "op": "eq", "val": lei}})
        page, req = probe.get(FILINGS_PATH, {"filter": flt, "include": "entity", "page[size]": "50"})
        leis = _entity_ids(page.document)
        rows = [
            {"filing_id": d["id"], **{k: d["attributes"][k] for k in ("fxo_id", "period_end", "sha256", "json_url", "package_url")}}
            for d in page.document["data"]
        ]
        match = [r for r in rows if r["period_end"] == period_end]
        if match:
            target.update(match[0])
        return {
            **req,
            "ok": leis == {lei},
            "outcome": f"meta.count={page.document.get('meta', {}).get('count')}, identifiers={sorted(leis)}",
            "filings": rows,
        }

    def lei_shortcut() -> dict:
        flt = _filter({"name": "entity.identifier", "op": "eq", "val": lei})
        page, req = probe.get(FILINGS_PATH, {"filter": flt, "include": "entity", "page[size]": "50"})
        leis = _entity_ids(page.document)
        return {
            **req,
            "ok": leis == {lei},
            "outcome": f"meta.count={page.document.get('meta', {}).get('count')}, identifiers={sorted(leis)}",
        }

    def entity_filings() -> dict:
        page, req = probe.get(f"{ENTITIES_PATH}/{lei}/filings", {"page[size]": "50"})
        return {**req, "ok": True, "outcome": f"meta.count={page.document.get('meta', {}).get('count')}"}

    def entity_resource() -> dict:
        page, req = probe.get(f"{ENTITIES_PATH}/{lei}")
        data = page.document["data"]
        return {
            **req,
            "ok": data.get("attributes", {}).get("identifier") == lei,
            "outcome": f"id={data.get('id')} attributes={data.get('attributes')}",
        }

    def period_end_eq() -> dict:
        page, req = probe.get(
            FILINGS_PATH,
            {"filter[country]": country, "filter[period_end]": period_end, "page[size]": "200"},
        )
        values = {d["attributes"]["period_end"] for d in page.document["data"]}
        return {
            **req,
            "ok": values <= {period_end},
            "outcome": f"meta.count={page.document.get('meta', {}).get('count')}, period_end values={sorted(values)}",
        }

    def period_end_range() -> dict:
        year = period_end[:4]
        flt = _filter(
            {"name": "country", "op": "eq", "val": country},
            {"name": "period_end", "op": "ge", "val": f"{year}-01-01"},
            {"name": "period_end", "op": "le", "val": f"{year}-12-31"},
        )
        page, req = probe.get(FILINGS_PATH, {"filter": flt, "page[size]": "200"})
        values = sorted({d["attributes"]["period_end"] for d in page.document["data"]})
        in_range = all(f"{year}-01-01" <= v <= f"{year}-12-31" for v in values)
        return {
            **req,
            "ok": in_range,
            "outcome": f"meta.count={page.document.get('meta', {}).get('count')}, min={values[:1]}, max={values[-1:]}",
        }

    def json_url_null() -> dict:
        # Verified limitation: the API rejects null values in filters (HTTP 400),
        # so filings without xBRL-JSON are found client-side in the index.
        # The probe passes while the limitation still holds.
        flt = _filter(
            {"name": "country", "op": "eq", "val": country},
            {"name": "json_url", "op": "is_", "val": None},
        )
        response = api.http.get(
            api.absolute_url(FILINGS_PATH),
            params={"filter": flt, "page[size]": "1"},
            headers={"Accept": JSONAPI_MEDIA_TYPE},
        )
        return {
            "request": f"GET {response.url}",
            "status": response.status_code,
            "ok": response.status_code == 400,
            "outcome": f"HTTP {response.status_code}: {response.text.strip()[:160]}",
        }

    def head(kind: str) -> Callable[[], dict]:
        def run() -> dict:
            if not target.get(kind):
                return {"ok": False, "outcome": f"no {kind} for the probe filing"}
            url = api.absolute_url(target[kind])
            response = api.http.head(url, allow_redirects=False)
            return {
                "request": f"HEAD {url}",
                "status": response.status_code,
                "ok": response.status_code == 200,
                "outcome": (
                    f"content-type={response.headers.get('Content-Type')}, "
                    f"content-encoding={response.headers.get('Content-Encoding')}, "
                    f"content-length={response.headers.get('Content-Length')}"
                ),
            }

        return run

    def download_hash(kind: str) -> Callable[[], dict]:
        def run() -> dict:
            if not target.get(kind):
                return {"ok": False, "outcome": f"no {kind} for the probe filing"}
            url = api.absolute_url(target[kind])
            digest = hashlib.sha256()
            size = 0
            body = bytearray() if kind == "json_url" else None
            with api.http.get(url, stream=True, allow_redirects=False) as response:
                status = response.status_code
                encoding = response.headers.get("Content-Encoding")
                if status == 200:
                    for chunk in response.iter_content(CHUNK):
                        digest.update(chunk)
                        size += len(chunk)
                        if body is not None:
                            body.extend(chunk)
            api.http.mark_done()
            computed = digest.hexdigest()
            result = {
                "request": f"GET {url}",
                "status": status,
                # requests decodes Content-Encoding (gzip): size and hash refer
                # to the decoded body, i.e. the file as it would be stored.
                "content_encoding": encoding,
                "bytes_decoded": size,
                "sha256_computed": computed,
                "sha256_api": target.get("sha256"),
                "matches_api_sha256": computed == target.get("sha256"),
            }
            if body is not None and status == 200:
                result["xbrl_json_structure"] = _describe_xbrl_json(json.loads(body))
            result["ok"] = status == 200
            result["outcome"] = (
                f"{size} bytes, sha256 {'==' if result['matches_api_sha256'] else '!='} API sha256"
            )
            return result

        return run

    probe.run("filings_country_include_entity", "filtro Paese, attributi filing ed entita'", basic)
    probe.run("filings_sort_id", "ordinamento stabile per la paginazione", sort_by_id)
    probe.run("filings_lei_filter_has", "filtro per LEI via relazione 'entity' (op has)", lei_has)
    probe.run("filings_lei_filter_shortcut", "filtro per LEI con la forma abbreviata entity.identifier", lei_shortcut)
    probe.run("entity_filings_link", "filing di un'entita' via /api/entities/<LEI>/filings", entity_filings)
    probe.run("entity_resource", "risorsa entita' indirizzata per LEI", entity_resource)
    probe.run("filings_period_end_eq", "filtro semplice su data di fine periodo", period_end_eq)
    probe.run("filings_period_end_range", "filtro su intervallo di fine periodo (ge/le)", period_end_range)
    probe.run(
        "filings_json_url_null",
        "filtro su json_url nullo: atteso HTTP 400 (limite noto, filtro lato client)",
        json_url_null,
    )
    probe.run("head_json_url", "il link json_url e' raggiungibile sull'host dell'API", head("json_url"))
    probe.run("head_package_url", "il link package_url e' raggiungibile sull'host dell'API", head("package_url"))
    if download:
        probe.run("package_sha256", "a cosa si riferisce l'attributo sha256 (pacchetto?)", download_hash("package_url"))
        probe.run("json_sha256_and_format", "hash e struttura dello xBRL-JSON", download_hash("json_url"))

    return {
        "run_at": utc_now_iso(),
        "api_base_url": api.base_url,
        "user_agent": api.http.user_agent,
        "min_delay_s": api.http.min_delay_s,
        "requests_sent": api.http.request_count,
        "probe_lei": lei,
        "probe_period_end": period_end,
        "probe_filing": target,
        "probes": probe.results,
    }


def _describe_xbrl_json(doc: dict) -> dict:
    """Structural summary of an xBRL-JSON document (no values)."""
    facts = doc.get("facts") or {}
    sample_id, sample = next(iter(facts.items()), (None, {}))
    dimension_keys: set[str] = set()
    fact_keys: set[str] = set()
    with_decimals = 0
    for fact in facts.values():
        fact_keys.update(fact)
        dimension_keys.update((fact.get("dimensions") or {}).keys())
        with_decimals += "decimals" in fact
    info = doc.get("documentInfo") or {}
    return {
        "top_level_keys": sorted(doc),
        "documentInfo_keys": sorted(info),
        "documentType": info.get("documentType"),
        "taxonomy": info.get("taxonomy"),
        "namespaces_prefixes": sorted((info.get("namespaces") or {}).keys()),
        "facts_container_type": type(facts).__name__,
        "fact_count": len(facts),
        "fact_keys_union": sorted(fact_keys),
        "dimension_keys_union": sorted(dimension_keys),
        "facts_with_decimals": with_decimals,
        "sample_fact_id": sample_id,
        "sample_fact_keys": sorted(sample),
    }
