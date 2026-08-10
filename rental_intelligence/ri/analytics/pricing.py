"""Statistiche di segmento e raccomandazione di prezzo.

Due principi che governano questo modulo:

1. **L'unita' di analisi non e' l'annuncio, e' il segmento.** Un percentile
   calcolato su otto annunci non e' un percentile, e' rumore con tre decimali.
   Ogni statistica porta con se' `sample_size` e `confidence`, e sotto la
   numerosita' minima il segmento viene marcato come inaffidabile invece di
   essere silenziosamente incluso nel report.

2. **"Il prezzo piu' conveniente" non e' il prezzo piu' basso.** La richiesta
   iniziale chiedeva di selezionare i prezzi piu' bassi: e' la metrica
   sbagliata. Un immobile a 60 €/notte pieno per 60 notti rende 3.600 €;
   uno a 95 €/notte pieno per 140 notti ne rende 13.300. Cio' che si ottimizza
   e' il RevPAR (ricavo per notte disponibile), non l'ADR.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Optional

from .. import config, geo
from ..models import (
    Listing,
    MarketSegment,
    MarketStats,
    PriceObservation,
    PricingAdvice,
    Property,
    PropertyType,
)
from .revenue import (
    adr_from_observations,
    annual_revenue,
    occupancy_from_panel,
    occupancy_from_prior,
    occupancy_from_reviews,
    occupancy_from_snapshot,
)

MIN_SAMPLE_RELIABLE = 30      # sotto questa soglia: confidenza bassa
MIN_SAMPLE_USABLE = 8         # sotto questa soglia: il segmento non entra nel report


def segment_of(listing_or_property, comune_market: Optional[str] = None) -> MarketSegment:
    market = getattr(listing_or_property, "macro_market", None) or comune_market or "sconosciuto"
    ptype = getattr(listing_or_property, "property_type", PropertyType.UNKNOWN)
    guests = getattr(listing_or_property, "max_guests", None)
    return MarketSegment(
        macro_market=market,
        property_type=ptype if isinstance(ptype, PropertyType) else PropertyType.UNKNOWN,
        capacity_bucket=geo.capacity_bucket(guests),
    )


def build_market_stats(
    properties: list[Property],
    listings: list[Listing],
    observations: list[PriceObservation],
) -> list[MarketStats]:
    """Una riga di statistiche per segmento di mercato."""
    by_listing_id = {l.listing_id: l for l in listings}
    obs_by_listing: dict[str, list[PriceObservation]] = defaultdict(list)
    for obs in observations:
        obs_by_listing[obs.listing_id].append(obs)

    grouped: dict[str, list[Property]] = defaultdict(list)
    segments: dict[str, MarketSegment] = {}
    for prop in properties:
        seg = segment_of(prop)
        grouped[seg.key()].append(prop)
        segments[seg.key()] = seg

    stats: list[MarketStats] = []
    for key, props in grouped.items():
        seg = segments[key]
        seg_obs: list[PriceObservation] = []
        occ_estimates = []

        for prop in props:
            prop_obs: list[PriceObservation] = []
            for lid in prop.listing_ids:
                prop_obs.extend(obs_by_listing.get(lid, []))
            seg_obs.extend(prop_obs)

            est = occupancy_from_panel(prop_obs) or occupancy_from_snapshot(prop_obs)
            if est is None:
                primary = by_listing_id.get(prop.listing_ids[0]) if prop.listing_ids else None
                if primary is not None:
                    est = occupancy_from_reviews(
                        primary.reviews_count, primary.first_review, primary.last_review
                    )
            if est is not None:
                occ_estimates.append(est)

        adr = adr_from_observations(seg_obs)

        # Nessun ADR osservato: ripiega sui prezzi base dichiarati negli annunci.
        if adr["n"] == 0:
            base_prices = sorted(
                l.base_price_eur for lid in
                (lid for p in props for lid in p.listing_ids)
                if (l := by_listing_id.get(lid)) and l.base_price_eur
            )
            if base_prices:
                adr = {
                    "p25": round(_pct(base_prices, 0.25), 2),
                    "p50": round(statistics.median(base_prices), 2),
                    "p75": round(_pct(base_prices, 0.75), 2),
                    "p90": round(_pct(base_prices, 0.90), 2),
                    "n": len(base_prices),
                }

        if occ_estimates:
            occupancy = statistics.median(e.occupancy for e in occ_estimates)
            method = _worst_method(e.method for e in occ_estimates)
            caveats = sorted({c for e in occ_estimates for c in e.caveats})
        else:
            fallback = occupancy_from_prior(seg.macro_market)
            occupancy, method, caveats = fallback.occupancy, fallback.method, fallback.caveats

        profile = geo.market_profile(seg.macro_market)
        seasonality = config.liguria()["seasonality_prior"][profile]

        revenue = None
        revpar = None
        if adr["p50"]:
            rev = annual_revenue(adr["p50"], occupancy, seg.macro_market)
            revenue = rev["annual_gross_revenue"]
            revpar = rev["revpar"]

        n = len(props)
        confidence = "alta" if n >= MIN_SAMPLE_RELIABLE and method == "panel" else (
            "media" if n >= MIN_SAMPLE_RELIABLE or method == "panel" else "bassa")

        extra: list[str] = list(caveats)
        if n < MIN_SAMPLE_RELIABLE:
            extra.append(
                f"campione di {n} immobili: sotto {MIN_SAMPLE_RELIABLE} i percentili "
                "sono indicativi e non vanno usati per decisioni puntuali"
            )
        if adr["n"] and not observations:
            extra.append("ADR derivato dai prezzi base degli annunci, non dal calendario")

        stats.append(MarketStats(
            segment=seg,
            sample_size=n,
            n_price_observations=adr["n"],
            adr_p25=adr["p25"], adr_p50=adr["p50"],
            adr_p75=adr["p75"], adr_p90=adr["p90"],
            occupancy_est=round(occupancy, 4),
            occupancy_method=method,
            revpar_est=revpar,
            annual_revenue_est=revenue,
            seasonality_index={int(k): float(v) for k, v in seasonality.items()},
            confidence=confidence,
            caveats=extra,
        ))

    return sorted(stats, key=lambda s: (-s.sample_size, s.segment.key()))


def _worst_method(methods) -> str:
    """Il metodo meno affidabile fra quelli usati: la confidenza di un
    aggregato non puo' superare quella del suo componente peggiore."""
    order = ["prior", "reviews", "snapshot", "panel"]
    ms = list(methods)
    return min(ms, key=lambda m: order.index(m) if m in order else 0) if ms else "prior"


def _pct(sorted_values: list[float], q: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


# ── raccomandazione di prezzo ────────────────────────────────────────────────

def price_advice(
    prop: Property,
    listings_by_id: dict[str, Listing],
    stats_by_segment: dict[str, MarketStats],
    *,
    target_percentile: float = 0.55,
) -> Optional[PricingAdvice]:
    """Prezzo consigliato mese per mese per un immobile.

    Il target di default e' leggermente sopra la mediana: la lettura e' che un
    immobile in linea con il mercato debba stare appena sopra il centro, non
    inseguire il fondo. Chi vuole massimizzare l'occupazione abbassa il target,
    chi ha un immobile distintivo lo alza. Non e' una verita' di mercato ma una
    scelta di posizionamento, ed e' un parametro proprio per questo.
    """
    seg = segment_of(prop)
    stats = stats_by_segment.get(seg.key())
    if stats is None or stats.adr_p50 is None:
        return None
    if stats.sample_size < MIN_SAMPLE_USABLE:
        return None

    current = next(
        (listings_by_id[lid].base_price_eur for lid in prop.listing_ids
         if lid in listings_by_id and listings_by_id[lid].base_price_eur),
        None,
    )

    anchors = [(0.25, stats.adr_p25), (0.50, stats.adr_p50),
               (0.75, stats.adr_p75), (0.90, stats.adr_p90)]
    anchors = [(q, v) for q, v in anchors if v is not None]
    target_adr = _interpolate(anchors, target_percentile)

    rationale = [
        f"segmento {seg.key()} — {stats.sample_size} immobili, "
        f"confidenza {stats.confidence}",
        f"mediana di segmento {stats.adr_p50:.0f} €/notte "
        f"(p25 {stats.adr_p25:.0f} — p75 {stats.adr_p75:.0f})",
        f"occupazione stimata {stats.occupancy_est:.0%} con metodo '{stats.occupancy_method}'",
    ]

    position = None
    percentile = None
    delta = None
    if current:
        percentile = _percentile_of(anchors, current)
        if current < (stats.adr_p25 or 0):
            position = "sotto"
            rationale.append(
                "il prezzo attuale e' sotto il primo quartile: se l'occupazione non "
                "e' gia' vicina alla saturazione, si sta lasciando margine sul tavolo"
            )
        elif current > (stats.adr_p75 or 1e9):
            position = "sopra"
            rationale.append(
                "prezzo sopra il terzo quartile: sostenibile solo con un vantaggio "
                "reale (vista, posizione, qualita'), altrimenti erode l'occupazione"
            )
        else:
            position = "in_linea"

        cur_rev = annual_revenue(current, stats.occupancy_est or 0.0, seg.macro_market)
        new_rev = annual_revenue(target_adr, stats.occupancy_est or 0.0, seg.macro_market)
        delta = round(new_rev["annual_gross_revenue"] - cur_rev["annual_gross_revenue"], 2)
        rationale.append(
            "il delta di ricavo assume occupazione invariata: e' un limite superiore, "
            "perche' alzare il prezzo in genere riduce le notti vendute"
        )

    profile = geo.market_profile(seg.macro_market)
    seasonality = config.liguria()["seasonality_prior"][profile]
    by_month = {int(m): round(target_adr * float(idx), 2) for m, idx in seasonality.items()}

    return PricingAdvice(
        property_id=prop.property_id,
        segment_key=seg.key(),
        current_adr=current,
        suggested_adr_by_month=by_month,
        suggested_adr_annual_avg=round(target_adr, 2),
        position_vs_market=position,
        percentile_in_segment=percentile,
        expected_revenue_delta_eur=delta,
        rationale=rationale,
    )


def _interpolate(anchors: list[tuple[float, float]], q: float) -> float:
    anchors = sorted(anchors)
    if q <= anchors[0][0]:
        return anchors[0][1]
    if q >= anchors[-1][0]:
        return anchors[-1][1]
    for (q1, v1), (q2, v2) in zip(anchors, anchors[1:]):
        if q1 <= q <= q2:
            w = (q - q1) / (q2 - q1) if q2 > q1 else 0
            return v1 + w * (v2 - v1)
    return anchors[-1][1]


def _percentile_of(anchors: list[tuple[float, float]], value: float) -> float:
    anchors = sorted(anchors, key=lambda a: a[1])
    if value <= anchors[0][1]:
        return round(anchors[0][0], 3)
    if value >= anchors[-1][1]:
        return round(anchors[-1][0], 3)
    for (q1, v1), (q2, v2) in zip(anchors, anchors[1:]):
        if v1 <= value <= v2:
            w = (value - v1) / (v2 - v1) if v2 > v1 else 0
            return round(q1 + w * (q2 - q1), 3)
    return round(anchors[-1][0], 3)


# ── calibrazione ─────────────────────────────────────────────────────────────

def calibrate_seasonality(observations: list[PriceObservation]) -> dict[int, float]:
    """Indice stagionale osservato, da usare al posto dei prior in liguria.yaml.

    Richiede osservazioni distribuite su tutti i mesi: con un solo trimestre di
    dati restituisce un indice che sembra plausibile ed e' privo di significato,
    quindi qui si rifiuta esplicitamente di produrlo.
    """
    by_month: dict[int, list[float]] = defaultdict(list)
    for obs in observations:
        if obs.available and obs.price_eur:
            by_month[obs.stay_date.month].append(obs.price_eur)

    if len(by_month) < 12:
        missing = sorted(set(range(1, 13)) - set(by_month))
        raise ValueError(
            f"calibrazione impossibile: mancano osservazioni per i mesi {missing}. "
            "Serve almeno un anno di rilevazioni; con dati parziali l'indice "
            "sarebbe una proiezione travestita da misura."
        )

    medians = {m: statistics.median(v) for m, v in by_month.items()}
    overall = statistics.mean(medians.values())
    return {m: round(v / overall, 4) for m, v in sorted(medians.items())}
