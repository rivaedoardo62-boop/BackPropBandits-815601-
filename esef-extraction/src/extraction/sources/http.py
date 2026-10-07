"""Polite HTTP access to filings.xbrl.org.

- descriptive User-Agent on every request;
- at least ``min_interval`` seconds (floor: 1 s) between the end of a request and the start of the next;
- bounded retries with exponential backoff on 429/5xx and network errors, honouring Retry-After;
- every URL, including the final one after redirects, must be on the allowed host.
"""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import requests

from extraction.settings import MIN_REQUEST_INTERVAL_FLOOR

log = logging.getLogger(__name__)

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_BACKOFF_SECONDS = 300.0


class HostNotAllowedError(ValueError):
    """Raised when a URL points outside the host the session is restricted to."""


class PoliteSession:
    def __init__(
        self,
        user_agent: str,
        allowed_host: str,
        min_interval: float,
        timeout: float = 120.0,
        max_retries: int = 4,
        session: requests.Session | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if min_interval < MIN_REQUEST_INTERVAL_FLOOR:
            raise ValueError(f"min_interval must be >= {MIN_REQUEST_INTERVAL_FLOOR}s")
        self._session = session if session is not None else requests.Session()
        self._session.headers["User-Agent"] = user_agent
        self.allowed_host = allowed_host
        self.min_interval = min_interval
        self.timeout = timeout
        self.max_retries = max_retries
        self._clock = clock
        self._sleep = sleep
        self._last_request_end: float | None = None
        self.request_count = 0

    @property
    def user_agent(self) -> str:
        return self._session.headers["User-Agent"]

    def check_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != self.allowed_host:
            raise HostNotAllowedError(f"refusing URL outside https://{self.allowed_host}: {url}")

    def _wait_turn(self) -> None:
        if self._last_request_end is None:
            return
        remaining = self.min_interval - (self._clock() - self._last_request_end)
        if remaining > 0:
            self._sleep(remaining)

    def _backoff(self, attempt: int, retry_after: str | None, reason: str) -> None:
        delay = max(self.min_interval, 2.0 ** (attempt + 1))
        if retry_after and retry_after.strip().isdigit():
            delay = max(delay, float(retry_after))
        delay = min(delay, MAX_BACKOFF_SECONDS)
        log.warning("%s, retry %d/%d in %.0fs", reason, attempt + 1, self.max_retries, delay)
        self._sleep(delay)

    def _request(self, url: str, *, params: Any = None, headers: dict | None = None,
                 stream: bool = False) -> requests.Response:
        self.check_url(url)
        for attempt in range(self.max_retries + 1):
            self._wait_turn()
            try:
                resp = self._session.get(url, params=params, headers=headers,
                                         timeout=self.timeout, stream=stream)
            except (requests.ConnectionError, requests.Timeout) as exc:
                self._last_request_end = self._clock()
                if attempt == self.max_retries:
                    raise
                self._backoff(attempt, None, type(exc).__name__)
                continue
            self.request_count += 1
            if not stream:
                self._last_request_end = self._clock()
            log.info("GET %s -> %s", resp.url, resp.status_code)
            if resp.status_code in RETRY_STATUSES and attempt < self.max_retries:
                resp.close()
                self._last_request_end = self._clock()
                self._backoff(attempt, resp.headers.get("Retry-After"), f"HTTP {resp.status_code}")
                continue
            try:
                self.check_url(resp.url)
                resp.raise_for_status()
            except Exception:
                resp.close()
                self._last_request_end = self._clock()
                raise
            return resp
        raise AssertionError("unreachable")

    def get_json(self, url: str, params: Any = None) -> dict:
        resp = self._request(url, params=params, headers={"Accept": "application/vnd.api+json"})
        return resp.json()

    def download(self, url: str, dest: Path, chunk_size: int = 1 << 20) -> tuple[str, int]:
        """Stream ``url`` to ``dest`` via a temporary file; return (sha256, size in bytes)."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        digest, size = hashlib.sha256(), 0
        resp = self._request(url, stream=True)
        try:
            with tmp.open("wb") as fh:
                for chunk in resp.iter_content(chunk_size):
                    fh.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        finally:
            resp.close()
            self._last_request_end = self._clock()
        tmp.replace(dest)
        return digest.hexdigest(), size
