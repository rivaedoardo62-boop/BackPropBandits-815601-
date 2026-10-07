import pytest

from extraction.sources.http import HostNotAllowedError, PoliteSession


class FakeResponse:
    def __init__(self, status_code=200, headers=None, payload=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload or {}

    def json(self):
        return self._payload

    def close(self):
        pass

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeRequestsSession:
    def __init__(self, responses):
        self.headers = {}
        self.calls = []
        self._responses = list(responses)

    def get(self, url, params=None, timeout=None, stream=False):
        self.calls.append((url, params))
        return self._responses.pop(0)


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, s):
        self.sleeps.append(s)
        self.now += s


def make_session(responses, delay=1.5):
    clock = FakeClock()
    fake = FakeRequestsSession(responses)
    s = PoliteSession("test-agent/1.0", delay, session=fake, clock=clock.clock, sleep=clock.sleep)
    return s, fake, clock


def test_rejects_hosts_other_than_filings_xbrl_org():
    s, fake, _ = make_session([])
    with pytest.raises(HostNotAllowedError):
        s.get("https://www.1info.it/some/document.pdf")
    assert fake.calls == []


def test_rejects_delay_below_one_second():
    with pytest.raises(ValueError):
        PoliteSession("ua", min_delay_s=0.5, session=FakeRequestsSession([]))


def test_sets_user_agent():
    s, fake, _ = make_session([])
    assert fake.headers["User-Agent"] == "test-agent/1.0"


def test_waits_between_consecutive_requests():
    s, fake, clock = make_session([FakeResponse(), FakeResponse()], delay=1.5)
    s.get("https://filings.xbrl.org/api/filings")
    clock.now += 0.2  # tempo di elaborazione tra le richieste
    s.get("https://filings.xbrl.org/api/filings")
    assert clock.sleeps == [pytest.approx(1.3)]
    assert s.request_count == 2


def test_retries_on_429_honouring_retry_after():
    s, fake, clock = make_session(
        [FakeResponse(429, {"Retry-After": "7"}), FakeResponse(200, payload={"ok": 1})]
    )
    resp = s.get("https://filings.xbrl.org/api/filings")
    assert resp.json() == {"ok": 1}
    assert 7.0 in clock.sleeps
    assert len(fake.calls) == 2


def test_gives_up_after_max_retries():
    s, _, _ = make_session([FakeResponse(503)] * 4)
    with pytest.raises(RuntimeError, match="503"):
        s.get("https://filings.xbrl.org/api/filings")
