"""Utility geografiche: distanze, risoluzione comune -> macro-mercato,
normalizzazione dei nomi (frazioni che le OTA spacciano per comuni).
"""

from __future__ import annotations

import csv
import functools
import math
import re
import unicodedata
from pathlib import Path
from typing import Optional

from . import config

EARTH_RADIUS_M = 6_371_008.8


# ── distanze ─────────────────────────────────────────────────────────────────

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distanza in metri fra due punti (formula dell'emisenoverso)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def geo_similarity(
    lat1: Optional[float],
    lon1: Optional[float],
    lat2: Optional[float],
    lon2: Optional[float],
    tolerance_m: float,
) -> Optional[float]:
    """Similarita' in [0, 1] fra due posizioni, tollerante all'offuscamento.

    Airbnb non pubblica la posizione esatta di un annuncio non prenotato: la
    sposta di un raggio dell'ordine dei 100-200 m. Due annunci dello stesso
    immobile su piattaforme diverse quindi NON hanno mai le stesse coordinate.
    Un raggio secco (`dist < X`) produce sia falsi negativi sopra soglia sia
    falsi positivi dentro; un kernel gaussiano restituisce invece un'evidenza
    graduata, che la deduplica pesa insieme alle altre.

    Ritorna None se una delle due posizioni manca: assenza di dato non e'
    evidenza di dissimilarita' e non deve entrare nel punteggio.
    """
    if None in (lat1, lon1, lat2, lon2):
        return None
    d = haversine_m(lat1, lon1, lat2, lon2)  # type: ignore[arg-type]
    sigma = max(tolerance_m, 1.0)
    return math.exp(-0.5 * (d / sigma) ** 2)


# ── normalizzazione nomi ─────────────────────────────────────────────────────

def _strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def normalize_place(name: str | None) -> str:
    """Chiave di confronto per nomi di luogo: minuscolo, senza accenti,
    senza punteggiatura, spazi normalizzati."""
    if not name:
        return ""
    text = _strip_accents(name).lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


@functools.lru_cache(maxsize=1)
def _comune_index() -> dict[str, tuple[str, str, str]]:
    """chiave normalizzata -> (comune canonico, macro_market, provincia)."""
    cfg = config.liguria()
    index: dict[str, tuple[str, str, str]] = {}

    for market_name, market in (cfg.get("macro_markets") or {}).items():
        provincia = market.get("provincia", "")
        for comune in market.get("comuni", []):
            index[normalize_place(comune)] = (comune, market_name, provincia)

    # Gli alias vanno risolti dopo, cosi' puntano al comune canonico gia' indicizzato.
    for alias, canonical in (cfg.get("comune_aliases") or {}).items():
        target = index.get(normalize_place(canonical))
        if target:
            index[normalize_place(alias)] = target

    return index


def resolve_comune(name: str | None) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Risolve un nome grezzo in (comune, macro_market, provincia).

    Ritorna (None, None, None) se il nome non appartiene al perimetro ligure
    configurato. Volutamente non fa fuzzy matching: un comune sconosciuto e' un
    segnale da far emergere nel report qualita', non da indovinare.
    """
    hit = _comune_index().get(normalize_place(name))
    return hit if hit else (None, None, None)


def market_profile(macro_market: str | None) -> str:
    """'costiero' o 'urbano': determina quali prior stagionali applicare."""
    profiles = config.liguria().get("market_profile") or {}
    if macro_market and macro_market in profiles:
        return profiles[macro_market]
    return profiles.get("default", "costiero")


def all_comuni() -> list[str]:
    return sorted({canonical for canonical, _, _ in _comune_index().values()})


def all_macro_markets() -> list[str]:
    return sorted((config.liguria().get("macro_markets") or {}).keys())


# ── capienza ─────────────────────────────────────────────────────────────────

def capacity_bucket(max_guests: Optional[int]) -> str:
    if max_guests is None:
        return "sconosciuta"
    for bucket in config.liguria().get("capacity_buckets", []):
        if bucket["min"] <= max_guests <= bucket["max"]:
            return bucket["name"]
    return "sconosciuta"


def season_of(month: int) -> str:
    for season, months in (config.liguria().get("seasons") or {}).items():
        if month in months:
            return season
    return "bassa"


# ── codici ISTAT (opzionali, da file ufficiale) ──────────────────────────────

_ISTAT_CACHE: dict[str, str] = {}


def load_istat_codes(csv_path: str | Path, *, name_col: str = "Denominazione in italiano",
                     code_col: str = "Codice Comune formato alfanumerico") -> int:
    """Carica i codici ISTAT dal file ufficiale delle unita' amministrative.

    Non sono hardcoded nel repo di proposito: un codice ISTAT inventato
    corrompe silenziosamente ogni join con le statistiche ufficiali, ed e'
    esattamente il tipo di errore che non si vede finche' non e' troppo tardi.
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(path)

    loaded = 0
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as fh:
        # Il file ISTAT e' storicamente in CSV punto-e-virgola.
        sample = fh.read(4096)
        fh.seek(0)
        delimiter = ";" if sample.count(";") > sample.count(",") else ","
        for row in csv.DictReader(fh, delimiter=delimiter):
            name = row.get(name_col)
            code = row.get(code_col)
            if not name or not code:
                continue
            key = normalize_place(name)
            if key in _comune_index():
                _ISTAT_CACHE[key] = code.strip()
                loaded += 1
    return loaded


def istat_code(comune: str | None) -> Optional[str]:
    return _ISTAT_CACHE.get(normalize_place(comune))
