"""Supervisore — gate di qualita' fra raccolta e analisi.

Stessa funzione del `SupervisorAgent` nel multiagent_pipeline gia' presente nel
repo: verificare il lavoro degli agenti a monte prima che i loro errori si
propaghino a valle.

Qui il rischio specifico e' che la pipeline produca comunque un report
elegante, con percentili e rendimenti a due decimali, costruito su venti
annunci mal geolocalizzati. Il report non sembrerebbe sbagliato: sembrerebbe
esattamente come un report giusto. Il gate esiste per rendere quel fallimento
visibile invece che silenzioso.

Distingue due livelli:
  - `blocking_issues`  -> l'analisi non parte, il report spiega perche';
  - `warnings`         -> l'analisi parte ma il report ne porta traccia.
"""

from __future__ import annotations

import logging
from collections import Counter

from ..analytics.pricing import MIN_SAMPLE_USABLE, segment_of
from ..models import ListingIntent, PipelineState, QualityReport

logger = logging.getLogger(__name__)

MIN_LISTINGS_FOR_ANALYSIS = 25
MAX_ACCEPTABLE_MISSING_GEO = 0.40
MAX_ACCEPTABLE_MISSING_PRICE = 0.35
SUSPICIOUS_DEDUP_RATIO = 0.55


def run(state: PipelineState) -> PipelineState:
    report = QualityReport(
        n_raw=len(state.raw_listings),
        n_listings=len(state.listings),
        n_properties=len(state.properties),
    )

    short_lets = [l for l in state.listings if l.intent is ListingIntent.SHORT_LET]
    report.coverage_by_source = dict(Counter(l.source for l in state.listings))
    report.n_dropped = sum((state.resolution_meta.get("dropped") or {}).values())
    report.dedup_ratio = float(
        (state.resolution_meta.get("dedup") or {}).get("dedup_ratio") or 0.0
    )

    # ── condizioni bloccanti ────────────────────────────────────────────────
    if not short_lets:
        report.blocking_issues.append(
            "nessun annuncio di affitto breve nel perimetro: non c'e' mercato da analizzare"
        )
    elif len(short_lets) < MIN_LISTINGS_FOR_ANALYSIS:
        report.blocking_issues.append(
            f"solo {len(short_lets)} annunci di affitto breve (minimo {MIN_LISTINGS_FOR_ANALYSIS}). "
            "Sotto questa soglia i percentili di prezzo descrivono il campione, non il mercato: "
            "meglio nessun numero che un numero che sembra affidabile e non lo e'."
        )

    if short_lets:
        missing_geo = sum(1 for l in short_lets if l.lat is None or l.lon is None) / len(short_lets)
        if missing_geo > MAX_ACCEPTABLE_MISSING_GEO:
            report.blocking_issues.append(
                f"{missing_geo:.0%} degli annunci senza coordinate (limite "
                f"{MAX_ACCEPTABLE_MISSING_GEO:.0%}): la deduplica perde il suo segnale "
                "principale e i conteggi per mercato non sono affidabili"
            )

        missing_price = sum(1 for l in short_lets if not l.base_price_eur) / len(short_lets)
        if missing_price > MAX_ACCEPTABLE_MISSING_PRICE and not state.price_observations:
            report.blocking_issues.append(
                f"{missing_price:.0%} degli annunci senza prezzo e nessun calendario "
                "disponibile: non c'e' base per stimare l'ADR"
            )

    # ── avvertimenti ────────────────────────────────────────────────────────
    if report.dedup_ratio > SUSPICIOUS_DEDUP_RATIO:
        report.warnings.append(
            f"la deduplica ha fuso il {report.dedup_ratio:.0%} degli annunci. È molto: "
            "verifica la soglia in analytics/dedup.py prima di fidarti dei conteggi. "
            "Un raggruppamento troppo aggressivo riduce artificialmente l'offerta e "
            "gonfia i prezzi mediani."
        )

    licence_coverage = float(
        (state.resolution_meta.get("dedup") or {}).get("licence_coverage") or 0.0
    )
    if short_lets and licence_coverage < 0.30:
        report.warnings.append(
            f"solo il {licence_coverage:.0%} degli annunci espone un CIN. È la chiave che "
            "rende la deduplica esatta invece che probabilistica: alzare questa copertura "
            "vale piu' di qualunque messa a punto dell'algoritmo di matching."
        )

    if not state.price_observations:
        report.warnings.append(
            "nessuna osservazione di calendario: l'occupazione sara' stimata da prior o da "
            "recensioni, non misurata. Tutti i rendimenti che ne derivano sono scenari."
        )

    failures = state.ingestion_meta.get("failures") or {}
    for source, reason in failures.items():
        report.warnings.append(f"sorgente '{source}' non disponibile: {reason}")

    if any(s.startswith("demo") for s in report.coverage_by_source):
        report.warnings.append(
            "il perimetro include dati dal generatore sintetico `demo`: i risultati "
            "illustrano il funzionamento della pipeline, non il mercato reale."
        )

    # ── segmenti con campione insufficiente ─────────────────────────────────
    counts = Counter(segment_of(p).key() for p in state.properties)
    report.segments_below_min_sample = sorted(
        key for key, n in counts.items() if n < MIN_SAMPLE_USABLE
    )
    if report.segments_below_min_sample:
        report.warnings.append(
            f"{len(report.segments_below_min_sample)} segmenti su {len(counts)} hanno meno di "
            f"{MIN_SAMPLE_USABLE} immobili e verranno esclusi dalle raccomandazioni di prezzo."
        )

    state.quality = report
    state.trace.append({
        "agent": "supervisor",
        "passed": report.passed,
        "n_blocking": len(report.blocking_issues),
        "n_warnings": len(report.warnings),
    })

    if not report.passed:
        logger.warning("gate qualita' non superato: %s", report.blocking_issues)
    return state
