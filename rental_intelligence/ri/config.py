"""Configurazione centralizzata: variabili d'ambiente + file YAML.

Regola: nessun numero economico, fiscale o geografico e' scritto nel codice.
Tutto passa da qui, cosi' l'unico posto in cui rivedere un'assunzione e' la
cartella `config/`.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULE_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = MODULE_ROOT / "config"

load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(MODULE_ROOT / ".env")


# ── helpers env ──────────────────────────────────────────────────────────────

def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _str(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


# ── YAML ─────────────────────────────────────────────────────────────────────

@functools.lru_cache(maxsize=None)
def _load_yaml(filename: str) -> dict[str, Any]:
    path = CONFIG_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"file di configurazione mancante: {path}")
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def liguria() -> dict[str, Any]:
    """Perimetro geografico, segmentazione e prior stagionali."""
    return _load_yaml("liguria.yaml")


def fiscale() -> dict[str, Any]:
    """Parametri economici e fiscali del modello di investimento."""
    return _load_yaml("fiscale.yaml")


def sources() -> dict[str, Any]:
    """Registro delle sorgenti dati e relativo stato di conformita'."""
    return _load_yaml("sources.yaml")


# ── LLM ──────────────────────────────────────────────────────────────────────

def llm_enabled() -> bool:
    return _bool("RI_LLM_ENABLED", False)


def anthropic_api_key() -> str | None:
    key = os.getenv("ANTHROPIC_API_KEY")
    return key.strip() if key and key.strip() else None


def llm_model() -> str:
    return _str("RI_LLM_MODEL", "claude-opus-5")


def llm_effort() -> str:
    effort = _str("RI_LLM_EFFORT", "high").lower()
    return effort if effort in {"low", "medium", "high", "xhigh", "max"} else "high"


# ── sorgenti attive ──────────────────────────────────────────────────────────

def active_sources() -> list[str]:
    """Connettori richiesti a runtime, nell'ordine dichiarato."""
    raw = _str("RI_SOURCES", "demo")
    return [s.strip() for s in raw.split(",") if s.strip()]


# ── percorsi ─────────────────────────────────────────────────────────────────

def db_path() -> Path:
    return PROJECT_ROOT / _str("RI_DB_PATH", "rental_intelligence/data/ri.sqlite")


def output_dir() -> Path:
    path = PROJECT_ROOT / _str("RI_OUTPUT_DIR", "rental_intelligence/data/out")
    path.mkdir(parents=True, exist_ok=True)
    return path


def import_dir() -> Path:
    path = MODULE_ROOT / "data" / "import"
    path.mkdir(parents=True, exist_ok=True)
    return path
