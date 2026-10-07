import hashlib

import pytest
import requests

from extraction.settings import build_user_agent, load_settings
from extraction.sources.http import HostNotAllowedError, PoliteSession
from fakes import FakeResponse, FakeSession

HOST = "filings.xbrl.org"
URL = f"https://{HOST}/api/filings"


def make_session(responses, clock, interval=1.5, retries=4):
    fake = FakeSession(responses)
    http = PoliteSession("test-agent/1.0 (tests)", HOST, interval, max_retries=retries,
                         session=fake, clock=clock, sleep=clock.sleep)
    return http, fake


def test_interval_below_one_second_is_rejected(clock):
    with pytest.raises(ValueError):
        make_session([], clock, interval=0.5)
    with pytest.raises(ValueError):
        load_settings({"ESEF_REQUEST_INTERVAL": "0.9"})


def test_user_agent_is_descriptive_and_contact_is_opt_in():
    assert "esef-extraction/" in build_user_agent()
    assert "contact" not in build_user_agent()
    assert build_user_agent("team@example.org").endswith("contact: team@example.org)")
    assert load_settings({}).user_agent == build_user_agent()


def test_api_host_cannot_be_overridden_from_the_environment():
    assert load_settings({"ESEF_API_BASE": "https://example.org"}).api_base == "https://filings.xbrl.org"


def test_user_agent_header_is_sent(clock):
    http, fake = make_session([FakeResponse(URL, payload={})], clock)
    http.get_json(URL)
    assert fake.headers["User-Agent"] == "test-agent/1.0 (tests)"


def test_consecutive_requests_are_spaced_by_min_interval(clock):
    http, _ = make_session([FakeResponse(URL, payload={}) for _ in range(3)], clock, interval=1.5)
    for _ in range(3):
        http.get_json(URL)
    assert clock.sleeps == [1.5, 1.5]


def test_no_wait_when_enough_time_has_passed(clock):
    http, _ = make_session([FakeResponse(URL, payload={}) for _ in range(2)], clock)
    http.get_json(URL)
    clock.now += 10
    http.get_json(URL)
    assert clock.sleeps == []


def test_retry_on_429_honours_retry_after(clock):
    responses = [FakeResponse(URL, 429, headers={"Retry-After": "30"}), FakeResponse(URL, payload={"ok": 1})]
    http, fake = make_session(responses, clock)
    assert http.get_json(URL) == {"ok": 1}
    assert len(fake.calls) == 2
    assert 30 in clock.sleeps


def test_retry_on_connection_error_then_gives_up(clock):
    responses = [requests.ConnectionError("boom")] * 3
    http, fake = make_session(responses, clock, retries=2)
    with pytest.raises(requests.ConnectionError):
        http.get_json(URL)
    assert len(fake.calls) == 3


def test_client_error_is_not_retried(clock):
    http, fake = make_session([FakeResponse(URL, 404)], clock)
    with pytest.raises(requests.HTTPError):
        http.get_json(URL)
    assert len(fake.calls) == 1


@pytest.mark.parametrize("url", ["https://example.org/api/filings", "http://filings.xbrl.org/api/filings"])
def test_urls_outside_allowed_host_are_refused(clock, url):
    http, fake = make_session([], clock)
    with pytest.raises(HostNotAllowedError):
        http.get_json(url)
    assert fake.calls == []


def test_redirect_to_foreign_host_is_refused(clock):
    http, _ = make_session([FakeResponse("https://example.org/elsewhere", payload={})], clock)
    with pytest.raises(HostNotAllowedError):
        http.get_json(URL)


def test_download_writes_file_and_returns_sha256(clock, tmp_path):
    body = b"x" * 3_000_000
    http, fake = make_session([FakeResponse(URL, body=body)], clock)
    dest = tmp_path / "sub" / "file.zip"
    digest, size = http.download(URL, dest, chunk_size=1 << 20)
    assert dest.read_bytes() == body
    assert (digest, size) == (hashlib.sha256(body).hexdigest(), len(body))
    assert not (tmp_path / "sub" / "file.zip.part").exists()
    assert fake.calls[0]["stream"] is True
