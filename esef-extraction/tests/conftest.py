"""Offline test doubles: no test contacts the network."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlencode

import pytest

from extraction.sources.filings_api import FilingsApi
from extraction.sources.http import PoliteSession

FIXTURES = Path(__file__).parent / "fixtures"
BASE_URL = "https://filings.xbrl.org"


class FakeResponse:
    def __init__(self, status_code=200, body=None, headers=None, url=""):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        self.status_code = status_code
        self.content = body or b""
        self.text = self.content.decode()
        self.headers = headers or {}
        self.url = url

    def close(self):
        pass


class FakeSession:
    """Stands in for requests.Session: replays canned responses, records calls."""

    def __init__(self, responses):
        self.headers = {}
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, params=None, **kwargs):
        full_url = f"{url}?{urlencode(params)}" if params else url
        self.calls.append({"method": method, "url": full_url, **kwargs})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if not response.url:
            response.url = full_url
        return response


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def make_api(clock):
    def factory(responses, **kwargs):
        session = FakeSession(responses)
        http = PoliteSession(
            "test-agent/1.0 (unit tests, no network)",
            session=session,
            clock=clock,
            sleep=clock.sleep,
            **kwargs,
        )
        return FilingsApi(http, BASE_URL), session

    return factory


@pytest.fixture
def api_page():
    """A real two-filing page of /api/filings?filter[country]=IT&include=entity."""
    return json.loads((FIXTURES / "filings_page_it.json").read_text(encoding="utf-8"))
