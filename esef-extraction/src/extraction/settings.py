"""Runtime settings, read from environment variables (see .env.example).

No credentials are needed: the filings.xbrl.org API is public.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from extraction import __version__

# Project rules: data only from filings.xbrl.org (deliberately not configurable),
# at least 1 second between two requests.
API_BASE = "https://filings.xbrl.org"
MIN_REQUEST_INTERVAL_FLOOR = 1.0
DEFAULT_REQUEST_INTERVAL = 1.5
DEFAULT_TIMEOUT = 120.0


def _default_root() -> Path:
    """Source checkout (or /app in the container) if recognisable, else the working directory."""
    candidate = Path(__file__).resolve().parents[2]
    return candidate if (candidate / "config").is_dir() else Path.cwd()


def build_user_agent(contact: str | None = None) -> str:
    """Descriptive User-Agent; a contact is added only if explicitly configured."""
    details = ["research prototype", "ESEF financial indicator extraction"]
    if contact:
        details.append(f"contact: {contact}")
    return f"esef-extraction/{__version__} ({'; '.join(details)})"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    config_dir: Path
    api_base: str
    request_interval: float
    timeout: float
    user_agent: str

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def interim_dir(self) -> Path:
        return self.data_dir / "interim"

    @property
    def output_dir(self) -> Path:
        return self.data_dir / "output"


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    interval = float(env.get("ESEF_REQUEST_INTERVAL") or DEFAULT_REQUEST_INTERVAL)
    if interval < MIN_REQUEST_INTERVAL_FLOOR:
        raise ValueError(
            f"ESEF_REQUEST_INTERVAL={interval} is below the {MIN_REQUEST_INTERVAL_FLOOR}s floor"
        )
    root = _default_root()
    return Settings(
        data_dir=Path(env.get("ESEF_DATA_DIR") or root / "data"),
        config_dir=Path(env.get("ESEF_CONFIG_DIR") or root / "config"),
        api_base=API_BASE,
        request_interval=interval,
        timeout=float(env.get("ESEF_HTTP_TIMEOUT") or DEFAULT_TIMEOUT),
        user_agent=build_user_agent(env.get("ESEF_CONTACT") or None),
    )
