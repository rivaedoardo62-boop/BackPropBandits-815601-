"""Agente 5 — Report.

Prende i risultati gia' calcolati dagli agenti 3 e 4 e li rende leggibili.
Due modalita':

  * **LLM** — Claude riceve una scheda-fatti compatta e produce una narrazione
    strutturata. Non calcola nulla: il prompt glielo vieta esplicitamente e lo
    schema di output non ha campi in cui potrebbe infilare un numero derivato.
  * **template** — nessuna chiamata API, testo deterministico dagli stessi
    dati. È il comportamento predefinito, e non e' un ripiego di serie B: e' la
    prova che il valore del sistema sta nell'analisi, non nella prosa.

Il payload inviato al modello e' volutamente ridotto: solo i segmenti
affidabili, solo le prime raccomandazioni, nessun campo grezzo. Serve a
contenere il costo, ma soprattutto a togliere al modello il materiale con cui
potrebbe divagare.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

from .. import config
from ..llm import LLMRefused, LLMUnavailable, try_build
from ..llm.prompts import (
    INVESTMENT_INSTRUCTION,
    INVESTMENT_REPORT_SCHEMA,
    MARKET_INSTRUCTION,
    MARKET_REPORT_SCHEMA,
    SYSTEM_STABLE,
    system_volatile,
)
from ..models import PipelineState

logger = logging.getLogger(__name__)

MAX_SEGMENTS_IN_PROMPT = 12
MAX_ADVICE_IN_PROMPT = 10
MAX_DEALS_IN_PROMPT = 8


def run(state: PipelineState, *, save: bool = True) -> PipelineState:
    generated_at = datetime.now().isoformat(timespec="seconds")
    perimeter = _describe_perimeter(state)
    sources = sorted((state.ingestion_meta.get("per_source") or {}).keys())

    report: dict[str, Any] = {
        "meta": {
            "generato_il": generated_at,
            "perimetro": perimeter,
            "sorgenti": sources,
            "modalita_narrazione": "template",
            "versione": "0.1.0",
        },
        "qualita_dati": state.quality.model_dump() if state.quality else None,
        "mercato": _market_payload(state),
        "investimenti": _investment_payload(state),
        "avvertenza": (
            "Analisi generata automaticamente. I parametri fiscali provengono da "
            "config/fiscale.yaml e non sono verificati contro la normativa vigente. "
            "Non costituisce consulenza finanziaria, fiscale o immobiliare."
        ),
    }

    # ── gate qualita' ────────────────────────────────────────────────────────
    if state.quality and not state.quality.passed:
        report["narrazione"] = {
            "sintesi": (
                "Analisi non prodotta: i dati raccolti non superano il controllo di "
                "qualita' minimo. Le ragioni sono elencate in `qualita_dati."
                "blocking_issues`. Un report costruito su questi dati sarebbe "
                "indistinguibile da uno affidabile, ed e' il motivo per cui non "
                "viene generato."
            ),
            "blocchi": state.quality.blocking_issues,
        }
        report["meta"]["modalita_narrazione"] = "bloccato"
        return _finalize(state, report, save)

    # ── narrazione ───────────────────────────────────────────────────────────
    client = try_build()
    if client is None:
        report["narrazione"] = _template_narrative(state)
    else:
        volatile = system_volatile(
            perimeter=perimeter,
            generated_at=generated_at,
            data_sources=sources,
            quality_summary=_quality_summary(state),
        )
        try:
            market_text = client.generate_structured(
                system_stable=SYSTEM_STABLE,
                system_volatile=volatile,
                user_payload=_market_prompt_payload(state),
                json_schema=MARKET_REPORT_SCHEMA,
                instruction=MARKET_INSTRUCTION,
            )
            narrative: dict[str, Any] = {"mercato": market_text}

            if state.underwriting:
                narrative["investimenti"] = client.generate_structured(
                    system_stable=SYSTEM_STABLE,
                    system_volatile=volatile,
                    user_payload=_investment_prompt_payload(state),
                    json_schema=INVESTMENT_REPORT_SCHEMA,
                    instruction=INVESTMENT_INSTRUCTION,
                )

            report["narrazione"] = narrative
            report["meta"]["modalita_narrazione"] = "llm"
            report["meta"]["llm"] = {
                "modello": client.model,
                "effort": client.effort,
                "usage": client.usage,
                "costo_stimato_usd": client.cost_estimate_usd(),
            }
        except (LLMUnavailable, LLMRefused, RuntimeError) as exc:
            # La narrazione e' un miglioramento, non una dipendenza: se salta,
            # il report esce comunque con lo stesso contenuto informativo.
            logger.warning("narrazione LLM fallita, ripiego su template: %s", exc)
            report["narrazione"] = _template_narrative(state)
            report["meta"]["llm_error"] = str(exc)

    return _finalize(state, report, save)


# ── payload compatti ─────────────────────────────────────────────────────────

def _market_payload(state: PipelineState) -> dict[str, Any]:
    return {
        "n_segmenti": len(state.market_stats),
        "segmenti": [
            {
                "chiave": s.segment.key(),
                "macro_mercato": s.segment.macro_market,
                "tipologia": s.segment.property_type.value,
                "capienza": s.segment.capacity_bucket,
                "n_immobili": s.sample_size,
                "adr_p25": s.adr_p25, "adr_p50": s.adr_p50,
                "adr_p75": s.adr_p75, "adr_p90": s.adr_p90,
                "occupazione_stimata": s.occupancy_est,
                "metodo_occupazione": s.occupancy_method,
                "revpar": s.revpar_est,
                "ricavo_annuo_stimato": s.annual_revenue_est,
                "confidenza": s.confidence,
                "avvertenze": s.caveats,
            }
            for s in state.market_stats
        ],
        "raccomandazioni_prezzo": [a.model_dump() for a in state.pricing_advice],
        "immobili_in_vendita": [d.model_dump() for d in state.deal_candidates[:30]],
    }


def _investment_payload(state: PipelineState) -> dict[str, Any]:
    return {
        "n_valutazioni": len(state.underwriting),
        "meta": state.underwriting_meta,
        "valutazioni": [r.model_dump() for r in state.underwriting],
    }


def _market_prompt_payload(state: PipelineState) -> dict[str, Any]:
    """Versione ridotta per il modello: solo cio' che serve a scrivere."""
    reliable = [s for s in state.market_stats if s.sample_size >= 8]
    reliable.sort(key=lambda s: -s.sample_size)
    return {
        "segmenti": [
            {
                "chiave": s.segment.key(),
                "n_immobili": s.sample_size,
                "adr_p25": s.adr_p25, "adr_mediano": s.adr_p50, "adr_p75": s.adr_p75,
                "occupazione": s.occupancy_est,
                "metodo_occupazione": s.occupancy_method,
                "revpar": s.revpar_est,
                "ricavo_annuo_stimato": s.annual_revenue_est,
                "confidenza": s.confidence,
                "avvertenze": s.caveats[:3],
            }
            for s in reliable[:MAX_SEGMENTS_IN_PROMPT]
        ],
        "n_segmenti_esclusi_campione_scarso": len(state.market_stats) - len(reliable),
        "raccomandazioni_prezzo": [
            {
                "property_id": a.property_id,
                "segmento": a.segment_key,
                "adr_attuale": a.current_adr,
                "adr_consigliato_medio": a.suggested_adr_annual_avg,
                "posizione": a.position_vs_market,
                "delta_ricavo_stimato_eur": a.expected_revenue_delta_eur,
                "motivazioni": a.rationale,
            }
            for a in sorted(
                state.pricing_advice,
                key=lambda x: abs(x.expected_revenue_delta_eur or 0),
                reverse=True,
            )[:MAX_ADVICE_IN_PROMPT]
        ],
    }


def _investment_prompt_payload(state: PipelineState) -> dict[str, Any]:
    return {
        "avvertenza_parametri": state.underwriting_meta.get("config_warning"),
        "valutazioni": [
            {
                "immobile": r.property_ref,
                "verdetto": r.verdict.value,
                "motivazioni_verdetto": r.verdict_reasons,
                "prezzo_acquisto": r.acquisition.purchase_price,
                "costo_totale_acquisizione": r.acquisition.total,
                "ricavo_lordo_annuo": r.operating.gross_revenue,
                "costi_operativi": r.operating.total_opex,
                "noi": r.operating.noi,
                "imposta_reddito": r.operating.income_tax,
                "regime_fiscale": r.operating.tax_regime_used,
                "costo_regime_alternativo": r.operating.tax_regime_alternative_cost,
                "flusso_cassa_netto": r.operating.net_cashflow,
                "rendimento_lordo": r.gross_yield,
                "rendimento_netto": r.net_yield,
                "cap_rate": r.cap_rate,
                "dscr": r.dscr,
                "break_even_occupancy": r.break_even_occupancy,
                "van": r.npv,
                "tir": r.irr,
                "payback_anni": r.payback_years,
                "sensibilita": r.sensitivity,
            }
            for r in state.underwriting[:MAX_DEALS_IN_PROMPT]
        ],
    }


# ── narrazione da template ───────────────────────────────────────────────────

def _template_narrative(state: PipelineState) -> dict[str, Any]:
    """Testo deterministico: stessi contenuti, senza chiamate API."""
    lines: list[str] = []

    reliable = [s for s in state.market_stats if s.confidence in {"alta", "media"}]
    lines.append(
        f"Analizzati {len(state.properties)} immobili distinti "
        f"({len(state.listings)} annunci) su {len(state.market_stats)} segmenti di mercato, "
        f"di cui {len(reliable)} con confidenza almeno media."
    )
    if not reliable:
        lines.append(
            "Nessun segmento raggiunge una confidenza media: i numeri che seguono "
            "descrivono il campione raccolto, non il mercato. Servono piu' annunci per "
            "segmento oppure dati di calendario ripetuti nel tempo."
        )

    if reliable:
        top = max(reliable, key=lambda s: s.revpar_est or 0)
        if top.revpar_est:
            lines.append(
                f"Il segmento con il RevPAR piu' alto e' {top.segment.key()}: "
                f"{top.revpar_est:.0f} €/notte disponibile, ADR mediano "
                f"{top.adr_p50:.0f} € e occupazione stimata {top.occupancy_est:.0%} "
                f"(metodo '{top.occupancy_method}')."
            )

    methods = {s.occupancy_method for s in state.market_stats}
    if methods and methods <= {"prior", "reviews"}:
        lines.append(
            "Nessun segmento dispone di dati di calendario: tutte le occupazioni sono "
            "stimate indirettamente. I rendimenti che ne derivano vanno letti come "
            "scenari, non come misure."
        )

    upside = [a for a in state.pricing_advice if (a.expected_revenue_delta_eur or 0) > 0]
    if upside:
        total = sum(a.expected_revenue_delta_eur or 0 for a in upside)
        lines.append(
            f"{len(upside)} immobili risultano prezzati sotto il posizionamento di "
            f"riferimento del loro segmento, per un potenziale teorico di "
            f"{total:,.0f} € annui complessivi. Il calcolo assume occupazione "
            "invariata, quindi e' un limite superiore."
        )

    verdicts = state.underwriting_meta.get("by_verdict") or {}
    if state.underwriting:
        lines.append(
            f"Valutate {len(state.underwriting)} opportunita' di acquisto: "
            + ", ".join(f"{n} '{v}'" for v, n in verdicts.items() if n) + "."
        )
        best = max(state.underwriting, key=lambda r: r.net_yield)
        lines.append(
            f"Il rendimento netto piu' alto e' {best.net_yield:.2%} su "
            f"{best.property_ref}, con break-even al "
            f"{(best.break_even_occupancy or 0):.0%} di occupazione."
        )

    return {
        "modalita": "template",
        "sintesi": " ".join(lines),
        "nota": (
            "Narrazione generata da template deterministico. Per la lettura discorsiva "
            "imposta RI_LLM_ENABLED=true e ANTHROPIC_API_KEY. I numeri sono identici "
            "nelle due modalita': l'LLM non ricalcola nulla."
        ),
    }


# ── utilita' ─────────────────────────────────────────────────────────────────

def _describe_perimeter(state: PipelineState) -> str:
    p = state.perimeter
    parts = []
    if p.macro_markets:
        parts.append("mercati: " + ", ".join(p.macro_markets))
    if p.comuni:
        parts.append("comuni: " + ", ".join(p.comuni))
    if p.min_guests or p.max_guests:
        parts.append(f"capienza {p.min_guests or 1}-{p.max_guests or '∞'}")
    return "; ".join(parts) if parts else "tutta la Liguria configurata"


def _quality_summary(state: PipelineState) -> str:
    q = state.quality
    if q is None:
        return "non valutata"
    return (
        f"{q.n_listings} annunci -> {q.n_properties} immobili "
        f"(deduplica {q.dedup_ratio:.0%}); "
        f"{len(q.blocking_issues)} problemi bloccanti, {len(q.warnings)} avvertimenti"
    )


def _finalize(state: PipelineState, report: dict[str, Any], save: bool) -> PipelineState:
    state.report = report
    if save:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = config.output_dir() / f"report_{stamp}.json"
        path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        state.report_path = str(path)
        logger.info("report salvato in %s", path)

    state.trace.append({
        "agent": "a5_report",
        "modalita": report["meta"]["modalita_narrazione"],
        "path": state.report_path,
    })
    return state
