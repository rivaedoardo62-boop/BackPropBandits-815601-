"""Impostazioni di esecuzione lette dall'ambiente (nessuna credenziale richiesta)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_USER_AGENT = (
    "esef-extraction-prototype/0.1 "
    "(research prototype; set FILINGS_API_USER_AGENT with a contact address)"
)

# Vincolo di progetto: almeno 1 secondo tra due richieste a filings.xbrl.org.
MIN_ALLOWED_DELAY_S = 1.0


@dataclass(frozen=True)
class Settings:
    project_root: Path
    user_agent: str
    min_delay_s: float
    timeout_s: float

    @property
    def data_dir(self) -> Path:
        return self.project_root / "data"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def interim_dir(self) -> Path:
        return self.data_dir / "interim"

    @property
    def output_dir(self) -> Path:
        return self.data_dir / "output"

    @property
    def config_dir(self) -> Path:
        return self.project_root / "config"


def load_settings(project_root: Path | None = None) -> Settings:
    root = Path(os.environ.get("ESEF_PROJECT_ROOT", project_root or Path.cwd())).resolve()
    delay = float(os.environ.get("FILINGS_API_MIN_DELAY_S", "1.5"))
    if delay < MIN_ALLOWED_DELAY_S:
        raise ValueError(
            f"FILINGS_API_MIN_DELAY_S={delay} è sotto il minimo consentito di {MIN_ALLOWED_DELAY_S}s"
        )
    return Settings(
        project_root=root,
        user_agent=os.environ.get("FILINGS_API_USER_AGENT", DEFAULT_USER_AGENT),
        min_delay_s=delay,
        timeout_s=float(os.environ.get("FILINGS_API_TIMEOUT_S", "60")),
    )
