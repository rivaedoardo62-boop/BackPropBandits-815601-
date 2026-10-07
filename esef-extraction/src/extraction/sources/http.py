"""Sessione HTTP "educata": un solo host ammesso, User-Agent descrittivo, ritardo minimo tra richieste."""

from __future__ import annotations

import time
from typing import Callable
from urllib.parse import urlparse

import requests

from extraction.settings import MIN_ALLOWED_DELAY_S

# Vincolo di progetto: si scarica solo da filings.xbrl.org.
ALLOWED_HOSTS = frozenset({"filings.xbrl.org"})
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class HostNotAllowedError(ValueError):
    pass


class PoliteSession:
    def __init__(
        self,
        user_agent: str,
        min_delay_s: float = 1.5,
        timeout_s: float = 60.0,
        max_retries: int = 3,
        session: requests.Session | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if min_delay_s < MIN_ALLOWED_DELAY_S:
            raise ValueError(f"min_delay_s deve essere >= {MIN_ALLOWED_DELAY_S}")
        if not user_agent.strip():
            raise ValueError("User-Agent vuoto")
        self.min_delay_s = min_delay_s
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self._session = session or requests.Session()
        self._session.headers["User-Agent"] = user_agent
        self._clock = clock
        self._sleep = sleep
        self._last_response_at: float | None = None
        self.request_count = 0

    def _wait_turn(self) -> None:
        if self._last_response_at is None:
            return
        elapsed = self._clock() - self._last_response_at
        if elapsed < self.min_delay_s:
            self._sleep(self.min_delay_s - elapsed)

    def get(self, url: str, params: dict | None = None, stream: bool = False) -> requests.Response:
        host = urlparse(url).hostname
        if host not in ALLOWED_HOSTS:
            raise HostNotAllowedError(f"host non ammesso: {host!r} ({url})")
        for attempt in range(self.max_retries + 1):
            self._wait_turn()
            try:
                resp = self._session.get(url, params=params, timeout=self.timeout_s, stream=stream)
            finally:
                # Il ritardo si misura dalla fine della richiesta precedente.
                self._last_response_at = self._clock()
                self.request_count += 1
            if resp.status_code in RETRYABLE_STATUS and attempt < self.max_retries:
                retry_after = resp.headers.get("Retry-After", "")
                backoff = float(retry_after) if retry_after.isdigit() else 2.0 ** (attempt + 1)
                resp.close()
                self._sleep(backoff)
                continue
            resp.raise_for_status()
            return resp
        raise AssertionError("unreachable")
