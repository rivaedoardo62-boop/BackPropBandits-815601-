"""Runtime settings, read from environment variables (see .env.example).

No credential is needed: filings.xbrl.org is a public API. Nothing here is
read from files committed to the repository.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from extraction import __version__

# Hard floor required by the project rules: at least one second between two
# requests to filings.xbrl.org, retries included.
MIN_REQUEST_DELAY_S = 1.0

DEFAULT_API_BASE_URL = "https://filings.xbrl.org"
DEFAULT_USER_AGENT = (
    f"esef-extraction-prototype/{__version__} "
    "(research prototype on ESEF annual reports; max 1 request/s; "
    "contact configurable via ESEF_USER_AGENT)"
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    api_base_url: str = DEFAULT_API_BASE_URL
    user_agent: str = DEFAULT_USER_AGENT
    request_delay_s: float = Field(default=MIN_REQUEST_DELAY_S, ge=MIN_REQUEST_DELAY_S)
    timeout_s: float = Field(default=60.0, gt=0)
    max_retries: int = Field(default=3, ge=0, le=10)
    data_dir: Path = PROJECT_ROOT / "data"
    config_dir: Path = PROJECT_ROOT / "config"

    @field_validator("api_base_url")
    @classmethod
    def _https_without_trailing_slash(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("api_base_url must use https")
        return value.rstrip("/")

    @field_validator("user_agent")
    @classmethod
    def _descriptive_user_agent(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 20:
            raise ValueError("user_agent must be a descriptive string")
        return value

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        """Settings from the environment; a local .env file fills unset variables."""
        if env is None:
            env = {**read_env_file(PROJECT_ROOT / ".env"), **os.environ}
        mapping = {
            "api_base_url": "ESEF_API_BASE_URL",
            "user_agent": "ESEF_USER_AGENT",
            "request_delay_s": "ESEF_REQUEST_DELAY_S",
            "timeout_s": "ESEF_TIMEOUT_S",
            "max_retries": "ESEF_MAX_RETRIES",
            "data_dir": "ESEF_DATA_DIR",
            "config_dir": "ESEF_CONFIG_DIR",
        }
        values = {field: env[var] for field, var in mapping.items() if env.get(var)}
        return cls(**values)

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def interim_dir(self) -> Path:
        return self.data_dir / "interim"

    @property
    def output_dir(self) -> Path:
        return self.data_dir / "output"


def read_env_file(path: Path) -> dict[str, str]:
    """Minimal KEY=VALUE reader for a local .env file (comments and blanks ignored).

    Values are taken verbatim apart from one pair of surrounding quotes, so the
    same file works with ``docker run --env-file``.
    """
    if not path.is_file():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values
