"""Persistenza SQLite.

Esiste per una ragione sola, e non e' "avere un database": **l'occupazione si
misura solo nel tempo.** Una singola rilevazione dice se una notte e' libera
oggi; non dice se e' stata venduta. Per distinguere venduto da bloccato servono
piu' fotografie dello stesso calendario a distanza di giorni, e per averle
bisogna conservarle.

Da qui discendono le scelte di schema:

* `price_observation` ha chiave primaria `(listing_id, stay_date, observed_at)`:
  la stessa notte va conservata piu' volte, una per rilevazione. Usare
  `(listing_id, stay_date)` e sovrascrivere — la scelta istintiva — cancellerebbe
  esattamente il dato che serve.
* `raw_listing` conserva il payload originale in JSON. Quando fra sei mesi una
  statistica sembrera' sbagliata, l'unico modo per capire se il problema e' nel
  modello o nel parsing e' rileggere cosa era arrivato davvero.
* Nessun ORM. Lo schema e' di quattro tabelle e resta leggibile; una dipendenza
  in piu' non pagherebbe.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Iterator, Optional

from . import config
from .models import Listing, PriceObservation, Property, RawListing

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_listing (
    source              TEXT NOT NULL,
    source_listing_id   TEXT NOT NULL,
    intent              TEXT NOT NULL,
    fetched_at          TEXT NOT NULL,
    url                 TEXT,
    payload             TEXT NOT NULL,
    PRIMARY KEY (source, source_listing_id, fetched_at)
);

CREATE TABLE IF NOT EXISTS listing (
    listing_id      TEXT NOT NULL,
    fetched_at      TEXT NOT NULL,
    source          TEXT NOT NULL,
    intent          TEXT NOT NULL,
    comune          TEXT,
    macro_market    TEXT,
    property_type   TEXT,
    max_guests      INTEGER,
    bedrooms        INTEGER,
    lat             REAL,
    lon             REAL,
    base_price_eur  REAL,
    asking_price_eur REAL,
    licence_code    TEXT,
    data            TEXT NOT NULL,
    PRIMARY KEY (listing_id, fetched_at)
);

-- observed_at fa parte della chiave: e' l'intera ragione d'essere di questa tabella.
CREATE TABLE IF NOT EXISTS price_observation (
    listing_id  TEXT NOT NULL,
    stay_date   TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    available   INTEGER NOT NULL,
    price_eur   REAL,
    min_nights  INTEGER,
    PRIMARY KEY (listing_id, stay_date, observed_at)
);

CREATE TABLE IF NOT EXISTS property_cluster (
    property_id   TEXT NOT NULL,
    resolved_at   TEXT NOT NULL,
    listing_ids   TEXT NOT NULL,
    comune        TEXT,
    macro_market  TEXT,
    licence_code  TEXT,
    confidence    REAL,
    data          TEXT NOT NULL,
    PRIMARY KEY (property_id, resolved_at)
);

CREATE INDEX IF NOT EXISTS idx_obs_listing_date ON price_observation (listing_id, stay_date);
CREATE INDEX IF NOT EXISTS idx_obs_stay_date    ON price_observation (stay_date);
CREATE INDEX IF NOT EXISTS idx_listing_market   ON listing (macro_market, intent);
CREATE INDEX IF NOT EXISTS idx_listing_licence  ON listing (licence_code);
"""


@contextmanager
def connect(path: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    db = path or config.db_path()
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


# ── scrittura ────────────────────────────────────────────────────────────────

def save_raw(conn: sqlite3.Connection, items: Iterable[RawListing]) -> int:
    rows = [
        (r.source, r.source_listing_id, r.intent.value, r.fetched_at.isoformat(),
         r.url, json.dumps(r.payload, ensure_ascii=False, default=str))
        for r in items
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO raw_listing "
        "(source, source_listing_id, intent, fetched_at, url, payload) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    return len(rows)


def save_listings(conn: sqlite3.Connection, items: Iterable[Listing]) -> int:
    rows = [
        (l.listing_id, l.fetched_at.isoformat(), l.source, l.intent.value,
         l.comune, l.macro_market, l.property_type.value, l.max_guests, l.bedrooms,
         l.lat, l.lon, l.base_price_eur, l.asking_price_eur, l.licence_code,
         l.model_dump_json())
        for l in items
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO listing "
        "(listing_id, fetched_at, source, intent, comune, macro_market, property_type, "
        " max_guests, bedrooms, lat, lon, base_price_eur, asking_price_eur, licence_code, data) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    return len(rows)


def save_observations(conn: sqlite3.Connection, items: Iterable[PriceObservation]) -> int:
    rows = [
        (o.listing_id, o.stay_date.isoformat(), o.observed_at.isoformat(),
         1 if o.available else 0, o.price_eur, o.min_nights)
        for o in items
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO price_observation "
        "(listing_id, stay_date, observed_at, available, price_eur, min_nights) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    return len(rows)


def save_properties(conn: sqlite3.Connection, items: Iterable[Property]) -> int:
    stamp = datetime.now().isoformat(timespec="seconds")
    rows = [
        (p.property_id, stamp, json.dumps(p.listing_ids), p.comune, p.macro_market,
         p.licence_code, p.merge_confidence, p.model_dump_json())
        for p in items
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO property_cluster "
        "(property_id, resolved_at, listing_ids, comune, macro_market, licence_code, "
        " confidence, data) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    return len(rows)


# ── lettura ──────────────────────────────────────────────────────────────────

def load_observations(
    conn: sqlite3.Connection,
    listing_ids: Optional[list[str]] = None,
    since: Optional[date] = None,
) -> list[PriceObservation]:
    """Rilegge lo storico completo, incluse le rilevazioni ripetute.

    È questa la funzione che abilita `occupancy_from_panel`: senza lo storico,
    quel metodo non ha niente su cui lavorare e il sistema ricade sulle stime
    indirette.
    """
    query = "SELECT * FROM price_observation WHERE 1=1"
    params: list = []
    if listing_ids:
        query += f" AND listing_id IN ({','.join('?' * len(listing_ids))})"
        params.extend(listing_ids)
    if since:
        query += " AND stay_date >= ?"
        params.append(since.isoformat())
    query += " ORDER BY listing_id, stay_date, observed_at"

    return [
        PriceObservation(
            listing_id=row["listing_id"],
            stay_date=date.fromisoformat(row["stay_date"]),
            observed_at=datetime.fromisoformat(row["observed_at"]),
            available=bool(row["available"]),
            price_eur=row["price_eur"],
            min_nights=row["min_nights"],
        )
        for row in conn.execute(query, params)
    ]


def panel_depth(conn: sqlite3.Connection) -> dict[str, int]:
    """Quante rilevazioni distinte esistono per notte-immobile.

    Diagnostica chiave del sistema: finche' la mediana e' 1, l'occupazione non
    e' misurata ma assunta, e ogni rendimento a valle e' uno scenario. Serve
    almeno una manciata di rilevazioni distanziate nel tempo.
    """
    row = conn.execute("""
        SELECT COUNT(DISTINCT observed_at) AS snapshots,
               COUNT(*)                    AS observations,
               COUNT(DISTINCT listing_id)  AS listings,
               COUNT(DISTINCT stay_date)   AS nights
        FROM price_observation
    """).fetchone()
    result = dict(row) if row else {}
    if result.get("nights") and result.get("listings"):
        cells = result["listings"] * result["nights"]
        result["avg_depth"] = round(result["observations"] / cells, 2) if cells else 0
    return result


def persist_state(state, path: Optional[Path] = None) -> dict[str, int]:
    """Salva tutto lo stato di una esecuzione. Da chiamare a ogni run
    programmato: e' l'accumulo che rende la stima di occupazione affidabile."""
    with connect(path) as conn:
        counts = {
            "raw": save_raw(conn, state.raw_listings),
            "listings": save_listings(conn, state.listings),
            "observations": save_observations(conn, state.price_observations),
            "properties": save_properties(conn, state.properties),
        }
    logger.info("persistiti %s", counts)
    return counts
