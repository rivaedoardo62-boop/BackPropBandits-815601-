"""Agente 2 — Normalizzazione, geolocalizzazione e deduplica.

Questo agente non era previsto nell'idea iniziale a tre agenti, ed e' quello
che decide se tutto il resto ha senso. Il motivo, in una riga: se lo stesso
appartamento compare tre volte perche' e' pubblicato su tre piattaforme, ogni
statistica calcolata a valle e' distorta nella stessa direzione, e nessuna
sofisticazione dell'analisi di mercato lo corregge.

Fa tre cose, in ordine:
  1. normalizza i payload grezzi in `Listing` tipizzati;
  2. risolve comune -> macro-mercato, scartando cio' che e' fuori perimetro;
  3. raggruppa gli annunci in immobili fisici (`Property`).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime
from typing import Any, Optional

from .. import geo
from ..analytics import dedup
from ..models import Listing, ListingIntent, PipelineState, PropertyType, RawListing

logger = logging.getLogger(__name__)

_PROPERTY_TYPE_MAP = {
    "entire_home": PropertyType.ENTIRE_HOME,
    "entire home/apt": PropertyType.ENTIRE_HOME,
    "entire rental unit": PropertyType.ENTIRE_HOME,
    "intero alloggio": PropertyType.ENTIRE_HOME,
    "appartamento": PropertyType.ENTIRE_HOME,
    "casa": PropertyType.ENTIRE_HOME,
    "private_room": PropertyType.PRIVATE_ROOM,
    "private room": PropertyType.PRIVATE_ROOM,
    "camera privata": PropertyType.PRIVATE_ROOM,
    "hotel_room": PropertyType.HOTEL_ROOM,
    "hotel room": PropertyType.HOTEL_ROOM,
    "albergo": PropertyType.HOTEL_ROOM,
    "b_and_b": PropertyType.B_AND_B,
    "bed and breakfast": PropertyType.B_AND_B,
    "residence": PropertyType.RESIDENCE,
}


def run(state: PipelineState) -> PipelineState:
    listings: list[Listing] = []
    dropped: dict[str, int] = {}

    for raw in state.raw_listings:
        listing, reason = _normalize(raw)
        if listing is None:
            dropped[reason or "sconosciuto"] = dropped.get(reason or "sconosciuto", 0) + 1
            continue
        if not _in_perimeter(listing, state):
            dropped["fuori_perimetro"] = dropped.get("fuori_perimetro", 0) + 1
            continue
        listings.append(listing)

    properties, dedup_meta = dedup.deduplicate(listings)

    state.listings = listings
    state.properties = properties
    state.resolution_meta = {
        "n_input": len(state.raw_listings),
        "n_normalized": len(listings),
        "dropped": dropped,
        "n_sale_listings": sum(1 for l in listings if l.intent is ListingIntent.SALE),
        "n_short_let_listings": sum(1 for l in listings if l.intent is ListingIntent.SHORT_LET),
        "dedup": dedup_meta,
        "ran_at": datetime.now().isoformat(timespec="seconds"),
    }
    state.trace.append({
        "agent": "a2_resolution",
        "n_listings": len(listings),
        "n_properties": len(properties),
        "dedup_ratio": dedup_meta.get("dedup_ratio"),
    })

    logger.info("normalizzati %d annunci -> %d immobili (riduzione %.1f%%)",
                len(listings), len(properties),
                100 * float(dedup_meta.get("dedup_ratio") or 0))
    return state


# ── normalizzazione ──────────────────────────────────────────────────────────

def _normalize(raw: RawListing) -> tuple[Optional[Listing], Optional[str]]:
    p: dict[str, Any] = raw.payload

    comune, macro_market, provincia = geo.resolve_comune(p.get("comune"))
    if comune is None:
        # Volutamente nessun fuzzy matching: un comune non riconosciuto e' un
        # segnale da far emergere, non da indovinare. Se ricorre spesso, va
        # aggiunto a liguria.yaml o alla tabella degli alias.
        return None, "comune_non_riconosciuto"

    ptype = _map_property_type(p.get("property_type"))
    flags: list[str] = []

    lat, lon = _coord(p.get("lat")), _coord(p.get("lon"))
    if lat is None or lon is None:
        flags.append("coordinate_mancanti")

    max_guests = _int(p.get("max_guests"))
    if max_guests is None and raw.intent is ListingIntent.SHORT_LET:
        flags.append("capienza_mancante")

    price = _float(p.get("base_price_eur"))
    if raw.intent is ListingIntent.SHORT_LET and (price is None or price <= 0):
        flags.append("prezzo_mancante")
    if price is not None and price > 3000:
        # Non scartiamo: in Liguria una villa a Portofino puo' legittimamente
        # superare la soglia. Marchiamo, e l'analisi decide se troncare.
        flags.append("prezzo_anomalo_alto")

    licence = dedup.normalize_licence(p.get("licence_code"))
    if raw.intent is ListingIntent.SHORT_LET and not licence:
        flags.append("cin_assente")

    amenities = p.get("amenities") or []
    if isinstance(amenities, str):
        amenities = [a.strip().lower() for a in amenities.split(",") if a.strip()]

    listing = Listing(
        listing_id=Listing.make_id(raw.source, raw.source_listing_id),
        source=raw.source,
        source_listing_id=raw.source_listing_id,
        intent=raw.intent,
        url=raw.url,
        title=p.get("title"),
        comune=comune,
        macro_market=macro_market,
        provincia=provincia,
        istat_code=geo.istat_code(comune),
        lat=lat,
        lon=lon,
        property_type=ptype,
        bedrooms=_int(p.get("bedrooms")),
        bathrooms=_float(p.get("bathrooms")),
        max_guests=max_guests,
        surface_sqm=_float(p.get("surface_sqm")),
        amenities=sorted({str(a).strip().lower() for a in amenities if str(a).strip()}),
        base_price_eur=price,
        cleaning_fee_eur=_float(p.get("cleaning_fee_eur")),
        min_nights=_int(p.get("min_nights")),
        rating=_float(p.get("rating")),
        reviews_count=_int(p.get("reviews_count")),
        first_review=_date(p.get("first_review")),
        last_review=_date(p.get("last_review")),
        host_key=_hash_host(p.get("host_id")),
        host_listings_count=_int(p.get("host_listings_count")),
        asking_price_eur=_float(p.get("asking_price_eur")),
        licence_code=licence,
        fetched_at=raw.fetched_at,
        quality_flags=flags,
        extra={k: p[k] for k in ("omi_min_eur_sqm", "omi_max_eur_sqm", "omi_zone",
                                 "stato_conservativo", "piano", "anno_costruzione")
               if k in p and p[k] is not None},
    )

    if listing.intent is ListingIntent.SALE and not listing.asking_price_eur:
        return None, "vendita_senza_prezzo"

    return listing, None


def _in_perimeter(listing: Listing, state: PipelineState) -> bool:
    p = state.perimeter
    if p.macro_markets and listing.macro_market not in p.macro_markets:
        return False
    if p.comuni and listing.comune not in p.comuni:
        return False
    if p.property_types and listing.property_type not in p.property_types:
        return False
    if p.min_guests and (listing.max_guests or 0) < p.min_guests:
        return False
    if p.max_guests and (listing.max_guests or 0) > p.max_guests:
        return False
    return True


# ── conversioni tolleranti ───────────────────────────────────────────────────

def _map_property_type(value: Any) -> PropertyType:
    if not value:
        return PropertyType.UNKNOWN
    return _PROPERTY_TYPE_MAP.get(str(value).strip().lower(), PropertyType.UNKNOWN)


def _float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> Optional[int]:
    f = _float(value)
    return int(f) if f is not None else None


def _coord(value: Any) -> Optional[float]:
    f = _float(value)
    # Filtro grossolano ma efficace: (0, 0) e' il valore che i CSV mal
    # compilati usano al posto di "sconosciuto", e finirebbe nel Golfo di Guinea.
    return f if f is not None and abs(f) > 0.001 else None


def _date(value: Any) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _hash_host(value: Any) -> Optional[str]:
    """Identificativo host pseudonimizzato.

    L'id host in chiaro e' un dato personale: serve solo a capire se due
    annunci hanno lo stesso gestore, e per quello basta un hash. Conservarlo in
    chiaro aggiungerebbe un obbligo GDPR senza aggiungere capacita' analitica.
    """
    if not value:
        return None
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]
