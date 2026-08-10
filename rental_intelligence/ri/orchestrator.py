"""Orchestratore della pipeline.

Topologia (5 agenti + 1 supervisore, 3 archi condizionali guidati dai dati):

    START
      │
      ▼
    A1 Ingestion ──── nessun dato ────────────────────────┐
      │                                                    │
      ▼                                                    │
    A2 Resolution                                          │
      │                                                    │
      ▼                                                    │
    Supervisor ─── qualita' insufficiente ────────┐        │
      │                                            │        │
      ▼                                            ▼        ▼
    A3 Market                                   A5 Report (modalita' bloccata)
      │
      ├─ nessun immobile in vendita ─┐
      ▼                              │
    A4 Underwriting                  │
      │                              │
      └──────────────┬───────────────┘
                     ▼
                 A5 Report
                     │
                    END

I tre archi condizionali sono decisioni sui dati, non gestione di errori:

  1. `after_ingestion`  — senza annunci non c'e' niente da normalizzare.
  2. `after_supervisor` — se il gate di qualita' non passa, si salta l'analisi e
     si va direttamente al report, che spiega perche'. Produrre percentili su
     dati inadeguati e' peggio che non produrli: il risultato e' visivamente
     indistinguibile da uno affidabile.
  3. `after_market`     — l'agente 4 gira solo se ci sono immobili in vendita
     agganciati a un segmento. Senza, non c'e' nulla da valutare.

Nota sull'implementazione: questo orchestratore e' Python semplice, senza
LangGraph, a differenza di `multiagent_pipeline/main.py`. La topologia e' la
stessa e la traduzione e' meccanica (ogni `run` diventa un nodo, ogni funzione
`after_*` un `add_conditional_edges`). La scelta e' per far girare il modulo
senza dipendenze aggiuntive; se serve la coerenza con l'altra pipeline, la
conversione e' un'ora di lavoro e nessun cambiamento di logica.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Optional

from .agents import (
    a1_ingestion,
    a2_resolution,
    a3_market,
    a4_underwriting,
    a5_report,
    supervisor,
)
from .models import ListingIntent, Perimeter, PipelineState

logger = logging.getLogger(__name__)


# ── archi condizionali ───────────────────────────────────────────────────────

def after_ingestion(state: PipelineState) -> str:
    return "a2_resolution" if state.raw_listings else "a5_report"


def after_supervisor(state: PipelineState) -> str:
    if state.quality is None or not state.quality.passed:
        return "a5_report"
    return "a3_market"


def after_market(state: PipelineState) -> str:
    has_deals = any(d.segment_key for d in state.deal_candidates)
    return "a4_underwriting" if has_deals else "a5_report"


# ── esecuzione ───────────────────────────────────────────────────────────────

_NODES: dict[str, Callable[[PipelineState], PipelineState]] = {
    "a1_ingestion": a1_ingestion.run,
    "a2_resolution": a2_resolution.run,
    "supervisor": supervisor.run,
    "a3_market": a3_market.run,
    "a4_underwriting": a4_underwriting.run,
    "a5_report": a5_report.run,
}

_ROUTES: dict[str, Callable[[PipelineState], str]] = {
    "a1_ingestion": after_ingestion,
    "a2_resolution": lambda _: "supervisor",
    "supervisor": after_supervisor,
    "a3_market": after_market,
    "a4_underwriting": lambda _: "a5_report",
    "a5_report": lambda _: "END",
}


def run_pipeline(
    perimeter: Optional[Perimeter] = None,
    *,
    save_report: bool = True,
    max_steps: int = 12,
) -> PipelineState:
    """Esegue la pipeline dall'inizio alla fine e restituisce lo stato finale.

    `max_steps` e' una cintura di sicurezza: la topologia e' aciclica, quindi
    non puo' scattare a meno che qualcuno non aggiunga un ciclo. Se scatta, e'
    un bug di routing, ed e' meglio scoprirlo con un'eccezione che con un
    processo che gira per sempre.
    """
    state = PipelineState(perimeter=perimeter or Perimeter())
    node = "a1_ingestion"
    steps = 0
    started = time.perf_counter()

    while node != "END":
        steps += 1
        if steps > max_steps:
            raise RuntimeError(
                f"superato il limite di {max_steps} passi: probabile ciclo nel routing "
                f"(ultimo nodo: {node})"
            )

        logger.info("→ %s", node)
        t0 = time.perf_counter()
        try:
            state = _NODES[node](state)
        except Exception as exc:  # noqa: BLE001
            logger.exception("errore nel nodo %s", node)
            state.errors.append(f"{node}: {type(exc).__name__}: {exc}")
            if node == "a5_report":
                break
            node = "a5_report"
            continue
        elapsed = time.perf_counter() - t0
        if state.trace and state.trace[-1].get("agent"):
            state.trace[-1]["elapsed_s"] = round(elapsed, 3)

        node = _ROUTES[node](state)

    total = time.perf_counter() - started
    state.trace.append({"agent": "END", "total_elapsed_s": round(total, 3), "steps": steps})
    logger.info("pipeline completata in %.2fs (%d passi)", total, steps)
    return state


def summary(state: PipelineState) -> str:
    """Riepilogo testuale compatto, per la CLI e per i log."""
    q = state.quality
    n_sale = sum(1 for l in state.listings if l.intent is ListingIntent.SALE)
    lines = [
        "─" * 68,
        "RENTAL INTELLIGENCE LIGURIA — riepilogo esecuzione",
        "─" * 68,
        f"  sorgenti          : {', '.join(state.ingestion_meta.get('per_source', {})) or '—'}",
        f"  annunci grezzi    : {len(state.raw_listings)}",
        f"  annunci validi    : {len(state.listings)}  (di cui {n_sale} in vendita)",
        f"  immobili distinti : {len(state.properties)}",
    ]
    if q:
        lines.append(f"  deduplica         : {q.dedup_ratio:.1%}")
        lines.append(f"  gate qualita'     : {'superato' if q.passed else 'NON superato'}")
        for issue in q.blocking_issues:
            lines.append(f"      ✗ {issue}")
        for warn in q.warnings[:5]:
            lines.append(f"      ! {warn}")
    lines += [
        f"  segmenti mercato  : {len(state.market_stats)}",
        f"  consigli prezzo   : {len(state.pricing_advice)}",
        f"  valutazioni acq.  : {len(state.underwriting)}",
    ]
    if state.underwriting:
        for verdict, n in (state.underwriting_meta.get("by_verdict") or {}).items():
            if n:
                lines.append(f"      {verdict:20s} {n}")
    if state.errors:
        lines.append("  errori:")
        lines += [f"      ✗ {e}" for e in state.errors]
    if state.report_path:
        lines.append(f"  report            : {state.report_path}")
    lines.append("─" * 68)
    return "\n".join(lines)
