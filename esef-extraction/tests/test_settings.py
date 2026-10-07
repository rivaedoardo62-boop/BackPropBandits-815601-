import pytest
from pydantic import ValidationError

from extraction.settings import MIN_REQUEST_DELAY_S, Settings, read_env_file


def test_defaults_respect_the_politeness_floor():
    settings = Settings.from_env({})
    assert settings.request_delay_s >= MIN_REQUEST_DELAY_S
    assert settings.api_base_url == "https://filings.xbrl.org"
    assert "esef-extraction-prototype" in settings.user_agent


def test_values_are_read_from_the_environment(tmp_path):
    settings = Settings.from_env(
        {
            "ESEF_REQUEST_DELAY_S": "2.5",
            "ESEF_DATA_DIR": str(tmp_path),
            "ESEF_USER_AGENT": "custom-agent/2.0 (contact: test)",
        }
    )
    assert settings.request_delay_s == 2.5
    assert settings.interim_dir == tmp_path / "interim"
    assert settings.user_agent == "custom-agent/2.0 (contact: test)"


@pytest.mark.parametrize(
    "env",
    [
        {"ESEF_REQUEST_DELAY_S": "0.5"},
        {"ESEF_API_BASE_URL": "http://filings.xbrl.org"},
        {"ESEF_USER_AGENT": "curl"},
    ],
)
def test_unsafe_values_are_rejected(env):
    with pytest.raises(ValidationError):
        Settings.from_env(env)


def test_env_file_reader(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\n\nESEF_REQUEST_DELAY_S=1.5\nESEF_USER_AGENT=agent/1.0 (a b; c)\nQUOTED=\"x y\"\n",
        encoding="utf-8",
    )
    assert read_env_file(env_file) == {
        "ESEF_REQUEST_DELAY_S": "1.5",
        "ESEF_USER_AGENT": "agent/1.0 (a b; c)",
        "QUOTED": "x y",
    }
    assert read_env_file(tmp_path / "missing.env") == {}
