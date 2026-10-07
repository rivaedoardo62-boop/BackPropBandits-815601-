import pytest
import requests

from extraction.sources.http import PoliteSession
from tests.conftest import FakeResponse, FakeSession


def make_session(responses, clock, **kwargs):
    session = FakeSession(responses)
    http = PoliteSession(
        "test-agent/1.0 (unit tests)", session=session, clock=clock, sleep=clock.sleep, **kwargs
    )
    return http, session


def test_user_agent_is_sent(clock):
    http, session = make_session([FakeResponse()], clock)
    http.get("https://filings.xbrl.org/api/filings")
    assert session.headers["User-Agent"] == "test-agent/1.0 (unit tests)"


@pytest.mark.parametrize("agent", ["", "   "])
def test_empty_user_agent_is_rejected(agent):
    with pytest.raises(ValueError):
        PoliteSession(agent)


def test_delay_below_one_second_is_rejected():
    with pytest.raises(ValueError):
        PoliteSession("test-agent/1.0 (unit tests)", min_delay_s=0.5)


def test_waits_at_least_the_minimum_delay_between_requests(clock):
    http, _ = make_session([FakeResponse(), FakeResponse(), FakeResponse()], clock)
    http.get("https://example.org/a")
    assert clock.sleeps == []  # first request: no wait
    clock.now += 0.3  # caller spends 0.3 s before the next request
    http.get("https://example.org/b")
    assert clock.sleeps == [pytest.approx(0.7)]
    clock.now += 5  # long pause: no extra wait
    http.get("https://example.org/c")
    assert clock.sleeps == [pytest.approx(0.7)]


def test_retries_on_429_honouring_retry_after_and_keeping_the_delay(clock):
    responses = [FakeResponse(429, headers={"Retry-After": "7"}), FakeResponse(200)]
    http, session = make_session(responses, clock)
    response = http.get("https://example.org/a")
    assert response.status_code == 200
    assert len(session.calls) == 2
    assert clock.sleeps == [7]  # Retry-After (>= 1 s, so no extra throttle wait)


def test_retries_on_connection_error_then_raises(clock):
    errors = [requests.ConnectionError("boom")] * 3
    http, session = make_session(errors, clock, max_retries=2)
    with pytest.raises(requests.ConnectionError):
        http.get("https://example.org/a")
    assert len(session.calls) == 3
    assert clock.sleeps == [2.0, 4.0]  # exponential backoff


def test_non_retryable_status_is_returned(clock):
    http, session = make_session([FakeResponse(404)], clock)
    assert http.get("https://example.org/a").status_code == 404
    assert len(session.calls) == 1
