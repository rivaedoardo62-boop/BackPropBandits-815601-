"""Agente 1 — Raccolta.

Responsabilita' unica: interrogare le sorgenti abilitate e depositare nello
stato i payload grezzi. Non normalizza, non filtra, non deduce. Ogni sorgente
che fallisce viene registrata e la pipeline prosegue con le altre: un
connettore rotto degrada la copertura, non ferma l'analisi.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from .. import config, connectors
from ..models import PipelineState

logger = logging.getLogger(__name__)

# Finestra di calendario richiesta alle sorgenti che ne espongono uno.
CALENDAR_HORIZON_DAYS = 365


def run(state: PipelineState) -> PipelineState:
    requested = config.active_sources()
    collected_raw = []
    collected_prices = []
    per_source: dict[str, int] = {}
    failures: dict[str, str] = {}

    start = date.today()
    end = start + timedelta(days=CALENDAR_HORIZON_DAYS)

    for name in requested:
        try:
            connector = connectors.build(name)
        except (connectors.ComplianceError, connectors.MissingCredentials, KeyError) as exc:
            # Percorso atteso, non eccezionale: una sorgente non disponibile e'
            # informazione utile per il report qualita', non un crash.
            failures[name] = str(exc)
            logger.warning("sorgente '%s' non utilizzabile: %s", name, exc)
            continue

        if not connector.enabled:
            failures[name] = "disabilitata in config/sources.yaml"
            continue

        try:
            raw = list(connector.fetch_listings(state.perimeter))
            collected_raw.extend(raw)
            per_source[name] = len(raw)

            prices = list(connector.fetch_prices(state.perimeter, raw, start, end))
            collected_prices.extend(prices)
            logger.info("sorgente '%s': %d annunci, %d osservazioni di prezzo",
                        name, len(raw), len(prices))
        except NotImplementedError as exc:
            failures[name] = f"adattatore da completare: {exc}"
            logger.warning("sorgente '%s' incompleta", name)
        except Exception as exc:  # noqa: BLE001 — una sorgente non deve far cadere il run
            failures[name] = f"{type(exc).__name__}: {exc}"
            logger.exception("errore nella sorgente '%s'", name)

    state.raw_listings = collected_raw
    state.price_observations = collected_prices
    state.ingestion_meta = {
        "requested_sources": requested,
        "per_source": per_source,
        "failures": failures,
        "n_raw": len(collected_raw),
        "n_price_observations": len(collected_prices),
        "calendar_window": [start.isoformat(), end.isoformat()],
        "ran_at": datetime.now().isoformat(timespec="seconds"),
    }
    state.trace.append({"agent": "a1_ingestion", "n_raw": len(collected_raw),
                        "sources_ok": list(per_source), "sources_failed": list(failures)})

    if not collected_raw:
        state.errors.append(
            "nessun annuncio raccolto: verifica RI_SOURCES e lo stato delle sorgenti "
            f"in config/sources.yaml. Dettaglio errori: {failures}"
        )
    return state
