"""Agente 3 — Analisi di mercato e pricing.

Tre uscite:
  1. `market_stats`     — ADR, occupazione, RevPAR per segmento;
  2. `pricing_advice`   — prezzo consigliato mese per mese per ogni immobile;
  3. `deal_candidates`  — annunci di vendita agganciati al mercato locativo
                          della loro zona.

Il terzo punto e' il ponte fra i due mondi. Senza, il sistema sa dire quanto si
affitta e quanto costa comprare ma non sa metterli in relazione, che e'
esattamente la domanda dell'investitore. L'aggancio avviene per segmento
(macro-mercato, tipologia, fascia di capienza), non per singolo immobile: la
capienza di un immobile in vendita si stima dalla superficie, quindi il match
e' con un mercato di riferimento, non con un comparabile puntuale.
"""

from __future__ import annotations

import logging
from datetime import datetime

from .. import geo
from ..analytics import pricing
from ..analytics.revenue import annual_revenue
from ..models import DealCandidate, ListingIntent, MarketSegment, PipelineState, PropertyType

logger = logging.getLogger(__name__)

# Rapporto mq per ospite usato per stimare la capienza di un immobile in vendita.
SQM_PER_GUEST = 16.0


def run(state: PipelineState) -> PipelineState:
    listings_by_id = {l.listing_id: l for l in state.listings}

    stats = pricing.build_market_stats(
        state.properties, state.listings, state.price_observations
    )
    stats_by_key = {s.segment.key(): s for s in stats}

    advice = []
    for prop in state.properties:
        item = pricing.price_advice(prop, listings_by_id, stats_by_key)
        if item is not None:
            advice.append(item)

    deals = _build_deal_candidates(state, stats_by_key)

    state.market_stats = stats
    state.pricing_advice = advice
    state.deal_candidates = deals
    state.market_meta = {
        "n_segments": len(stats),
        "n_segments_reliable": sum(1 for s in stats if s.confidence in {"alta", "media"}),
        "n_pricing_advice": len(advice),
        "n_deal_candidates": len(deals),
        "occupancy_methods": sorted({s.occupancy_method for s in stats}),
        "ran_at": datetime.now().isoformat(timespec="seconds"),
    }
    state.trace.append({
        "agent": "a3_market",
        "n_segments": len(stats),
        "n_advice": len(advice),
        "n_deals": len(deals),
    })

    logger.info("mercato: %d segmenti, %d raccomandazioni di prezzo, %d immobili in vendita "
                "agganciati", len(stats), len(advice), len(deals))
    return state


def _build_deal_candidates(state: PipelineState, stats_by_key: dict) -> list[DealCandidate]:
    """Collega ogni annuncio di vendita al suo segmento locativo."""
    out: list[DealCandidate] = []

    for listing in state.listings:
        if listing.intent is not ListingIntent.SALE or not listing.asking_price_eur:
            continue
        if not listing.comune or not listing.macro_market:
            continue

        guests = listing.max_guests
        if guests is None and listing.surface_sqm:
            guests = max(2, int(listing.surface_sqm / SQM_PER_GUEST))

        segment = MarketSegment(
            macro_market=listing.macro_market,
            property_type=listing.property_type
            if listing.property_type is not PropertyType.UNKNOWN else PropertyType.ENTIRE_HOME,
            capacity_bucket=geo.capacity_bucket(guests),
        )
        stats = stats_by_key.get(segment.key())

        expected_revenue = None
        if stats and stats.adr_p50 and stats.occupancy_est:
            expected_revenue = annual_revenue(
                stats.adr_p50, stats.occupancy_est, listing.macro_market
            )["annual_gross_revenue"]

        price_sqm = (round(listing.asking_price_eur / listing.surface_sqm, 2)
                     if listing.surface_sqm else None)

        omi_min = _num(listing, "omi_min_eur_sqm")
        omi_max = _num(listing, "omi_max_eur_sqm")
        vs_omi = None
        if price_sqm and omi_min and omi_max:
            omi_mid = (omi_min + omi_max) / 2
            vs_omi = round((price_sqm - omi_mid) / omi_mid, 4)

        out.append(DealCandidate(
            listing_id=listing.listing_id,
            comune=listing.comune,
            macro_market=listing.macro_market,
            asking_price_eur=listing.asking_price_eur,
            surface_sqm=listing.surface_sqm,
            price_per_sqm=price_sqm,
            omi_min_eur_sqm=omi_min,
            omi_max_eur_sqm=omi_max,
            vs_omi_pct=vs_omi,
            segment_key=segment.key() if stats else None,
            expected_annual_revenue_eur=expected_revenue,
        ))

    # Ordina per rendimento lordo implicito: e' il primo filtro che un
    # investitore applica, e mette in cima cio' che merita approfondimento.
    def implied_yield(d: DealCandidate) -> float:
        if not d.expected_annual_revenue_eur or not d.asking_price_eur:
            return -1.0
        return d.expected_annual_revenue_eur / d.asking_price_eur

    return sorted(out, key=implied_yield, reverse=True)


def _num(listing, key: str):
    """I valori OMI viaggiano in `Listing.extra`: non tutte le sorgenti li hanno."""
    value = listing.extra.get(key)
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
