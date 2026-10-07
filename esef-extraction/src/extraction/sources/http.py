"""HTTP session enforcing the project's politeness rules.

- a descriptive User-Agent on every request;
- at least ``min_delay_s`` seconds (never less than 1 s) between the end of a
  request and the start of the next one, retries included;
- bounded retries with exponential backoff on 429/5xx and connection errors,
  honouring ``Retry-After`` when the server sends it.

For streamed downloads (``stream=True``) the caller must call ``mark_done()``
after the body has been consumed, so that the delay is measured from the end
of the transfer.
"""

from __future__ import annotations

import email.utils
import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone

import requests

from extraction.settings import MIN_REQUEST_DELAY_S

log = logging.getLogger(__name__)

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_BACKOFF_S = 300.0


class PoliteSession:
    def __init__(
        self,
        user_agent: str,
        *,
        min_delay_s: float = MIN_REQUEST_DELAY_S,
        timeout_s: float = 60.0,
        max_retries: int = 3,
        session: requests.Session | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not user_agent or not user_agent.strip():
            raise ValueError("a descriptive User-Agent is required")
        if min_delay_s < MIN_REQUEST_DELAY_S:
            raise ValueError(f"min_delay_s must be >= {MIN_REQUEST_DELAY_S} s")
        self.min_delay_s = min_delay_s
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self._session = session if session is not None else requests.Session()
        self._session.headers["User-Agent"] = user_agent.strip()
        self._clock = clock
        self._sleep = sleep
        self._last_done: float | None = None
        self.request_count = 0

    @property
    def user_agent(self) -> str:
        return self._session.headers["User-Agent"]

    def mark_done(self) -> None:
        """Restart the delay window (call after consuming a streamed body)."""
        self._last_done = self._clock()

    def _wait_turn(self) -> None:
        if self._last_done is None:
            return
        remaining = self.min_delay_s - (self._clock() - self._last_done)
        if remaining > 0:
            self._sleep(remaining)

    def request(self, method: str, url: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", self.timeout_s)
        attempt = 0
        while True:
            self._wait_turn()
            self.request_count += 1
            try:
                response = self._session.request(method, url, **kwargs)
            except (requests.ConnectionError, requests.Timeout) as exc:
                self.mark_done()
                if attempt >= self.max_retries:
                    raise
                wait = _backoff_s(attempt)
                log.warning("%s %s failed (%s); retry in %.0f s", method, url, exc, wait)
                self._sleep(wait)
                attempt += 1
                continue
            self.mark_done()
            if response.status_code in RETRY_STATUSES and attempt < self.max_retries:
                wait = _retry_after_s(response) or _backoff_s(attempt)
                log.warning(
                    "%s %s returned %s; retry in %.0f s",
                    method, url, response.status_code, wait,
                )
                response.close()
                self._sleep(wait)
                attempt += 1
                continue
            return response

    def get(self, url: str, **kwargs) -> requests.Response:
        return self.request("GET", url, **kwargs)

    def head(self, url: str, **kwargs) -> requests.Response:
        return self.request("HEAD", url, **kwargs)


def _backoff_s(attempt: int) -> float:
    return min(2.0 * 2**attempt, MAX_BACKOFF_S)


def _retry_after_s(response: requests.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return min(float(value), MAX_BACKOFF_S)
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    seconds = (when - datetime.now(timezone.utc)).total_seconds()
    return min(max(seconds, 0.0), MAX_BACKOFF_S) or None
