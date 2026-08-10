"""Generatore sintetico calibrato sui prior liguri.

Serve a tre cose concrete:
  1. far girare la pipeline end-to-end senza dipendere da nessuna fonte esterna;
  2. dare ai test un dataset deterministico con verita' note (sappiamo quanti
     duplicati abbiamo iniettato, quindi possiamo misurare la deduplica);
  3. permettere di sviluppare gli agenti 3, 4 e 5 in parallelo alla trattativa
     per l'accesso ai dati reali, che e' la parte lenta del progetto.

I dati NON sono reali e non vanno mai presentati come tali: il report finale
riporta esplicitamente la sorgente `demo` in testa.
"""

from __future__ import annotations

import hashlib
import random
from datetime import date, datetime, timedelta
from typing import Iterable

from .. import config, geo
from ..models import ListingIntent, Perimeter, PriceObservation, RawListing
from .base import Connector, register

# Coordinate approssimate dei centri dei macro-mercati, usate solo per generare
# posizioni plausibili nel dataset sintetico.
_MARKET_CENTERS: dict[str, tuple[float, float]] = {
    "riviera_ponente_estrema": (43.790, 7.610),
    "sanremo_area": (43.816, 7.776),
    "golfo_dianese": (43.910, 8.080),
    "riviera_alassio": (44.005, 8.172),
    "finalese": (44.169, 8.344),
    "savona_ponente_ge": (44.309, 8.481),
    "genova_citta": (44.407, 8.934),
    "golfo_paradiso": (44.348, 9.155),
    "tigullio": (44.311, 9.213),
    "tigullio_orientale": (44.271, 9.394),
    "cinque_terre": (44.135, 9.685),
    "golfo_dei_poeti": (44.103, 9.828),
}

# ADR medio annuo indicativo per macro-mercato (appartamento 3-4 posti).
# Sono valori inventati ma di ordine di grandezza plausibile: servono a rendere
# il dataset sintetico utile per testare la logica, non a stimare il mercato.
_MARKET_BASE_ADR: dict[str, float] = {
    "riviera_ponente_estrema": 95,
    "sanremo_area": 110,
    "golfo_dianese": 100,
    "riviera_alassio": 125,
    "finalese": 115,
    "savona_ponente_ge": 95,
    "genova_citta": 90,
    "golfo_paradiso": 155,
    "tigullio": 165,
    "tigullio_orientale": 130,
    "cinque_terre": 185,
    "golfo_dei_poeti": 120,
}

_AMENITIES = [
    "wifi", "aria_condizionata", "lavatrice", "cucina", "tv", "terrazza",
    "vista_mare", "parcheggio", "ascensore", "lavastoviglie", "animali_ammessi",
    "riscaldamento", "balcone", "giardino",
]


@register
class DemoConnector(Connector):
    """Dataset sintetico, deterministico a parita' di seed."""

    name = "demo"
    intent_supported = ("short_let", "sale")

    def __init__(self, seed: int = 20250810, n_short_let: int = 420,
                 n_sale: int = 60, duplicate_rate: float = 0.22) -> None:
        super().__init__()
        self.rng = random.Random(seed)
        self.n_short_let = n_short_let
        self.n_sale = n_sale
        self.duplicate_rate = duplicate_rate
        self._generated: list[RawListing] = []
        # Verita' nota: quali id sintetici sono lo stesso immobile fisico.
        self.ground_truth_clusters: dict[str, str] = {}

    # ── annunci ──────────────────────────────────────────────────────────────

    def fetch_listings(self, perimeter: Perimeter) -> Iterable[RawListing]:
        markets = perimeter.macro_markets or geo.all_macro_markets()
        markets = [m for m in markets if m in _MARKET_CENTERS]
        if not markets:
            return []

        cfg = config.liguria()
        out: list[RawListing] = []
        now = datetime.now()

        for i in range(self.n_short_let):
            market = self.rng.choice(markets)
            comuni = cfg["macro_markets"][market]["comuni"]
            comune = self.rng.choice(comuni)
            unit = self._make_unit(i, market, comune)

            primary = self._as_raw("demo_airbnb", f"ab-{i}", ListingIntent.SHORT_LET, unit, now)
            out.append(primary)
            self.ground_truth_clusters[primary.source_listing_id] = unit["unit_key"]

            # Lo stesso immobile pubblicato anche su una seconda piattaforma,
            # con titolo diverso, coordinate spostate e capienza a volte
            # dichiarata diversa. È il caso che la deduplica deve reggere.
            if self.rng.random() < self.duplicate_rate:
                twin = dict(unit)
                twin["lat"] += self.rng.gauss(0, 0.0012)     # ~130 m
                twin["lon"] += self.rng.gauss(0, 0.0016)
                twin["title"] = self._retitle(unit["title"])
                twin["base_price_eur"] = round(unit["base_price_eur"] * self.rng.uniform(0.95, 1.12), 2)
                if self.rng.random() < 0.25:
                    twin["max_guests"] = max(1, unit["max_guests"] + self.rng.choice([-1, 1]))
                # Il CIN e' identico: e' la stessa unita' immobiliare.
                secondary = self._as_raw(
                    "demo_booking", f"bk-{i}", ListingIntent.SHORT_LET, twin, now
                )
                out.append(secondary)
                self.ground_truth_clusters[secondary.source_listing_id] = unit["unit_key"]

        for j in range(self.n_sale):
            market = self.rng.choice(markets)
            comune = self.rng.choice(cfg["macro_markets"][market]["comuni"])
            out.append(self._make_sale(j, market, comune, now))

        self._generated = out
        return out

    # ── calendario ───────────────────────────────────────────────────────────

    def fetch_prices(self, perimeter: Perimeter, listings: list[RawListing],
                     start: date, end: date) -> Iterable[PriceObservation]:
        """Calendario sintetico coerente con i prior stagionali.

        Genera osservazioni con `available` gia' risolto. Sui dati veri questo
        e' il campo piu' insidioso di tutto il sistema: una notte non
        disponibile puo' essere venduta oppure semplicemente bloccata dal
        proprietario, e le due cose sono indistinguibili dall'esterno. Vedi
        `analytics/revenue.py` per come il modello gestisce l'ambiguita'.
        """
        from ..models import Listing  # import locale: evita ciclo a import-time

        cfg = config.liguria()
        observed_at = datetime.now()
        out: list[PriceObservation] = []

        for raw in listings:
            if raw.intent is not ListingIntent.SHORT_LET:
                continue
            payload = raw.payload
            market = payload.get("macro_market")
            profile = geo.market_profile(market)
            occ_prior = cfg["occupancy_prior"][profile]
            adr_prior = cfg["seasonality_prior"][profile]
            base = float(payload.get("base_price_eur") or 100.0)
            listing_id = Listing.make_id(raw.source, raw.source_listing_id)

            # Alcuni host chiudono l'immobile in bassa stagione: la pipeline
            # deve distinguerlo da un immobile invenduto.
            closes_off_season = self.rng.random() < 0.35

            day = start
            while day <= end:
                month = day.month
                occ = occ_prior[month]
                price = round(base * adr_prior[month] * self.rng.uniform(0.94, 1.06), 2)

                if closes_off_season and occ_prior[month] < 0.2:
                    out.append(PriceObservation(
                        listing_id=listing_id, stay_date=day, observed_at=observed_at,
                        available=False, price_eur=None,
                    ))
                else:
                    booked = self.rng.random() < occ
                    out.append(PriceObservation(
                        listing_id=listing_id, stay_date=day, observed_at=observed_at,
                        available=not booked,
                        price_eur=None if booked else price,
                        min_nights=payload.get("min_nights"),
                    ))
                day += timedelta(days=1)

        return out

    # ── costruzione unita' ───────────────────────────────────────────────────

    def _make_unit(self, i: int, market: str, comune: str) -> dict:
        lat0, lon0 = _MARKET_CENTERS[market]
        guests = self.rng.choices([2, 3, 4, 5, 6, 8], weights=[22, 14, 30, 16, 12, 6])[0]
        bedrooms = max(1, round(guests / 2))
        base = _MARKET_BASE_ADR[market] * (0.62 + 0.19 * guests) / 1.38
        sea_view = self.rng.random() < 0.42
        if sea_view:
            base *= 1.22

        amenities = self.rng.sample(_AMENITIES, k=self.rng.randint(5, 11))
        if sea_view and "vista_mare" not in amenities:
            amenities.append("vista_mare")

        unit_key = f"unit-{i}"
        # CIN sintetico: nella realta' e' assegnato dalla banca dati nazionale.
        cin = "IT" + hashlib.sha1(unit_key.encode()).hexdigest()[:9].upper()

        return {
            "unit_key": unit_key,
            "title": self._make_title(comune, guests, sea_view),
            "comune": comune,
            "macro_market": market,
            "lat": round(lat0 + self.rng.gauss(0, 0.010), 6),
            "lon": round(lon0 + self.rng.gauss(0, 0.014), 6),
            "property_type": "entire_home" if self.rng.random() < 0.88 else "private_room",
            "max_guests": guests,
            "bedrooms": bedrooms,
            "bathrooms": 1 if guests <= 4 else 2,
            "surface_sqm": round(18 + 12.5 * guests + self.rng.gauss(0, 8), 1),
            "amenities": sorted(amenities),
            "base_price_eur": round(base * self.rng.uniform(0.86, 1.16), 2),
            "cleaning_fee_eur": float(self.rng.choice([35, 45, 50, 60, 70, 80])),
            "min_nights": self.rng.choice([1, 2, 2, 3, 3, 5, 7]),
            "rating": round(self.rng.uniform(4.1, 5.0), 2),
            "reviews_count": int(abs(self.rng.gauss(48, 42))),
            "licence_code": cin,
            "host_id": f"host-{self.rng.randint(1, 240)}",
        }

    def _make_sale(self, j: int, market: str, comune: str, now: datetime) -> RawListing:
        lat0, lon0 = _MARKET_CENTERS[market]
        sqm = round(self.rng.uniform(38, 130), 1)
        # €/mq sintetico correlato all'ADR del mercato: mercati che rendono di
        # piu' costano di piu'. La correlazione e' voluta, cosi' il modello di
        # investimento non trova per costruzione affari impossibili ovunque.
        eur_sqm = _MARKET_BASE_ADR[market] * 26 * self.rng.uniform(0.72, 1.34)
        payload = {
            "title": f"Trilocale in vendita, {comune}",
            "comune": comune,
            "macro_market": market,
            "lat": round(lat0 + self.rng.gauss(0, 0.010), 6),
            "lon": round(lon0 + self.rng.gauss(0, 0.014), 6),
            "property_type": "entire_home",
            "surface_sqm": sqm,
            "bedrooms": max(1, int(sqm // 32)),
            "bathrooms": 1 if sqm < 75 else 2,
            "max_guests": max(2, int(sqm // 16)),
            "asking_price_eur": round(sqm * eur_sqm, -2),
            "omi_min_eur_sqm": round(eur_sqm * 0.82, -1),
            "omi_max_eur_sqm": round(eur_sqm * 1.24, -1),
            "amenities": [],
        }
        return self._as_raw("demo_sale", f"sale-{j}", ListingIntent.SALE, payload, now)

    def _make_title(self, comune: str, guests: int, sea_view: bool) -> str:
        adj = self.rng.choice(["Luminoso", "Accogliente", "Grazioso", "Elegante", "Nuovo"])
        kind = self.rng.choice(["appartamento", "bilocale", "trilocale", "monolocale", "casa"])
        extra = " vista mare" if sea_view else ""
        return f"{adj} {kind}{extra} a {comune} — {guests} ospiti"

    def _retitle(self, title: str) -> str:
        """Stesso immobile, titolo scritto da zero per l'altra piattaforma."""
        words = title.replace("—", " ").split()
        self.rng.shuffle(words)
        return " ".join(words[: max(4, len(words) - 3)])

    def _as_raw(self, source: str, sid: str, intent: ListingIntent,
                payload: dict, now: datetime) -> RawListing:
        return RawListing(
            source=source,
            source_listing_id=sid,
            intent=intent,
            fetched_at=now,
            payload=payload,
            url=f"https://example.invalid/{source}/{sid}",
        )
