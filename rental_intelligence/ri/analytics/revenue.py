"""Stima di occupazione, ADR, RevPAR e ricavo annuo.

Il punto che rende questo modulo delicato e che va capito prima di fidarsi dei
numeri: **l'occupazione non e' osservabile dall'esterno.**

Quello che si vede su una piattaforma e' se una notte e' disponibile oppure no.
Una notte non disponibile puo' essere:
  (a) venduta a un ospite  -> ricavo
  (b) bloccata dal proprietario (uso personale, manutenzione, chiusura
      stagionale, minimum-stay che rende inprenotabile un buco di 2 notti)
      -> nessun ricavo

Confondere (b) con (a) sovrastima l'occupazione, e siccome il ricavo e'
occupazione × ADR, sovrastima il rendimento — cioe' sbaglia esattamente nella
direzione che ti fa comprare un immobile che non conviene.

Il modulo implementa tre metodi in ordine di affidabilita' decrescente e
dichiara sempre quale ha usato (`occupancy_method`), cosi' l'agente 5 puo'
qualificare il numero invece di narrarlo come certo.

  1. `panel`   — piu' rilevazioni dello stesso calendario nel tempo. È l'unico
                 metodo che distingue davvero (a) da (b): una notte che era
                 disponibile e poi non lo e' piu' e' stata verosimilmente
                 prenotata; una notte non disponibile da sempre e' bloccata.
  2. `snapshot`— una sola rilevazione. Assume che una quota delle notti chiuse
                 sia bloccata (`blocked_share`) e la scarta. Il parametro e' un
                 prior, non una misura: va calibrato appena hai un panel.
  3. `reviews` — nessun calendario. Deriva le notti vendute dalle recensioni:
                 notti = recensioni / tasso_recensione × durata_media. Metodo
                 storicamente usato dalle analisi pubbliche su Airbnb; e'
                 grossolano, sottostima gli host nuovi e sovrastima quelli con
                 molti soggiorni brevi. Usalo come limite inferiore.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Optional

from .. import config, geo
from ..models import PriceObservation

# Quota di notti chiuse che si assume NON venduta, in assenza di panel.
DEFAULT_BLOCKED_SHARE = 0.25

# Parametri del metodo "reviews".
REVIEW_RATE = 0.50            # frazione di soggiorni che lascia una recensione
DEFAULT_LOS = 4.0             # notti per soggiorno
MAX_PLAUSIBLE_OCCUPANCY = 0.95


@dataclass
class OccupancyEstimate:
    occupancy: float
    method: str
    n_nights_observed: int
    n_nights_sold_est: float
    confidence: str
    caveats: list[str]


# ── metodo 1: panel ──────────────────────────────────────────────────────────

def occupancy_from_panel(observations: list[PriceObservation]) -> Optional[OccupancyEstimate]:
    """Occupazione da rilevazioni ripetute dello stesso calendario.

    Regola: una notte contata come venduta e' una notte vista almeno una volta
    disponibile e almeno una volta successiva non disponibile. Una notte sempre
    chiusa e' considerata bloccata ed esclusa dal denominatore, non contata come
    venduta. Cosi' l'errore va verso la sottostima, che e' il verso giusto
    quando il numero serve a decidere un acquisto.
    """
    by_night: dict[date, list[PriceObservation]] = defaultdict(list)
    for obs in observations:
        by_night[obs.stay_date].append(obs)

    multi = {d: obs for d, obs in by_night.items() if len({o.observed_at for o in obs}) >= 2}
    if len(multi) < 20:
        return None

    sold = 0
    universe = 0
    for _, obs in multi.items():
        series = sorted(obs, key=lambda o: o.observed_at)
        was_open = any(o.available for o in series)
        closed_at_end = not series[-1].available
        if was_open:
            universe += 1
            if closed_at_end:
                sold += 1
        # notti mai aperte: bloccate, fuori dal denominatore

    if universe == 0:
        return None

    occ = min(sold / universe, MAX_PLAUSIBLE_OCCUPANCY)
    return OccupancyEstimate(
        occupancy=round(occ, 4),
        method="panel",
        n_nights_observed=universe,
        n_nights_sold_est=float(sold),
        confidence="alta" if universe >= 180 else "media",
        caveats=[
            "notti mai risultate disponibili escluse dal denominatore: "
            "trattate come bloccate dall'host, non come vendute"
        ],
    )


# ── metodo 2: snapshot ───────────────────────────────────────────────────────

def occupancy_from_snapshot(
    observations: list[PriceObservation],
    blocked_share: float = DEFAULT_BLOCKED_SHARE,
) -> Optional[OccupancyEstimate]:
    """Occupazione da una sola rilevazione, con correzione per notti bloccate."""
    if not observations:
        return None
    total = len(observations)
    closed = sum(1 for o in observations if not o.available)
    sold_est = closed * (1 - blocked_share)
    occ = min(sold_est / total, MAX_PLAUSIBLE_OCCUPANCY) if total else 0.0
    return OccupancyEstimate(
        occupancy=round(occ, 4),
        method="snapshot",
        n_nights_observed=total,
        n_nights_sold_est=round(sold_est, 1),
        confidence="bassa",
        caveats=[
            f"assunto che il {blocked_share:.0%} delle notti chiuse sia bloccato "
            "dall'host e non venduto: e' un prior non calibrato",
            "una sola rilevazione non distingue prenotato da bloccato",
        ],
    )


# ── metodo 3: recensioni ─────────────────────────────────────────────────────

def occupancy_from_reviews(
    reviews_count: Optional[int],
    first_review: Optional[date],
    last_review: Optional[date],
    *,
    avg_los: float = DEFAULT_LOS,
    review_rate: float = REVIEW_RATE,
    available_nights_per_year: int = 365,
) -> Optional[OccupancyEstimate]:
    """Occupazione derivata dal ritmo delle recensioni.

    notti_vendute_anno = (recensioni/mese) x 12 / tasso_recensione x durata_media

    Distorsioni note, tutte nella stessa direzione (sottostima):
      - non tutti recensiscono, e il tasso vero varia per piattaforma e host;
      - gli annunci nuovi hanno poche recensioni ma possono essere pieni;
      - le prenotazioni dirette o via altri canali non lasciano recensioni li'.
    Usala come pavimento, mai come stima puntuale.
    """
    if not reviews_count or not first_review or not last_review:
        return None
    months = max((last_review - first_review).days / 30.44, 1.0)
    reviews_per_month = reviews_count / months
    nights_year = reviews_per_month * 12 / max(review_rate, 0.05) * avg_los
    occ = min(nights_year / available_nights_per_year, MAX_PLAUSIBLE_OCCUPANCY)
    return OccupancyEstimate(
        occupancy=round(occ, 4),
        method="reviews",
        n_nights_observed=0,
        n_nights_sold_est=round(nights_year, 1),
        confidence="bassa",
        caveats=[
            f"stima indiretta con tasso di recensione assunto al {review_rate:.0%} "
            f"e soggiorno medio di {avg_los:.1f} notti",
            "sottostima sistematicamente gli annunci nuovi e le prenotazioni dirette",
        ],
    )


# ── metodo 4: prior ──────────────────────────────────────────────────────────

def occupancy_from_prior(macro_market: str | None) -> OccupancyEstimate:
    """Fallback: media annua dei prior stagionali del profilo di mercato."""
    profile = geo.market_profile(macro_market)
    prior = config.liguria()["occupancy_prior"][profile]
    occ = sum(prior.values()) / len(prior)
    return OccupancyEstimate(
        occupancy=round(occ, 4),
        method="prior",
        n_nights_observed=0,
        n_nights_sold_est=round(occ * 365, 1),
        confidence="bassa",
        caveats=[
            f"nessun dato osservato: usato il prior '{profile}' di config/liguria.yaml",
            "questo numero descrive un'ipotesi, non il mercato",
        ],
    )


# ── ADR ──────────────────────────────────────────────────────────────────────

def adr_from_observations(observations: list[PriceObservation]) -> dict[str, Optional[float]]:
    """Percentili dell'ADR sulle notti con prezzo esposto.

    Solo le notti disponibili hanno un prezzo visibile: quello che si misura e'
    quindi il prezzo *richiesto*, non quello *incassato*. In alta stagione, dove
    resta libero soprattutto cio' che e' caro o poco attraente, la differenza fra
    i due e' rilevante. Il modello lo dichiara invece di nasconderlo.
    """
    prices = [o.price_eur for o in observations if o.available and o.price_eur and o.price_eur > 0]
    if not prices:
        return {"p25": None, "p50": None, "p75": None, "p90": None, "n": 0}
    prices.sort()
    return {
        "p25": round(_percentile(prices, 0.25), 2),
        "p50": round(statistics.median(prices), 2),
        "p75": round(_percentile(prices, 0.75), 2),
        "p90": round(_percentile(prices, 0.90), 2),
        "n": len(prices),
    }


def _percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return float("nan")
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


# ── ricavo annuo ─────────────────────────────────────────────────────────────

def annual_revenue(
    adr_annual_avg: float,
    occupancy_annual: float,
    macro_market: str | None,
    *,
    nights_available_per_year: int = 365,
    apply_seasonality: bool = True,
) -> dict[str, float]:
    """Ricavo lordo annuo, mese per mese.

    Moltiplicare ADR medio per occupazione media e per 365 e' sbagliato quando
    le due variabili sono correlate, ed e' esattamente il caso della Liguria:
    ad agosto sono alti insieme. La media dei prodotti mensili e' superiore al
    prodotto delle medie, quindi il calcolo ingenuo *sottostima* il ricavo di
    un balneare e lo sovrastima in mercati piatti. Qui si aggrega per mese.
    """
    cfg = config.liguria()
    profile = geo.market_profile(macro_market)
    adr_idx = cfg["seasonality_prior"][profile]
    occ_idx = cfg["occupancy_prior"][profile]
    occ_prior_avg = sum(occ_idx.values()) / len(occ_idx)

    days = {1: 31, 2: 28.25, 3: 31, 4: 30, 5: 31, 6: 30,
            7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}
    scale = nights_available_per_year / 365.25

    monthly: dict[int, float] = {}
    total = 0.0
    nights_sold = 0.0

    for month in range(1, 13):
        if apply_seasonality:
            adr_m = adr_annual_avg * adr_idx[month]
            # Riscala il profilo di occupazione sul livello annuo osservato.
            occ_m = min(occ_idx[month] * (occupancy_annual / occ_prior_avg), 1.0)
        else:
            adr_m, occ_m = adr_annual_avg, occupancy_annual

        n = days[month] * scale * occ_m
        revenue = n * adr_m
        monthly[month] = round(revenue, 2)
        total += revenue
        nights_sold += n

    return {
        "annual_gross_revenue": round(total, 2),
        "nights_sold": round(nights_sold, 1),
        "effective_adr": round(total / nights_sold, 2) if nights_sold else 0.0,
        "revpar": round(total / (nights_available_per_year or 1), 2),
        "monthly": {m: monthly[m] for m in range(1, 13)},
    }
