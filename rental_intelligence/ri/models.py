"""Contratto dati condiviso fra tutti gli agenti.

Come nel `multiagent_pipeline` gia' presente nel repo, gli agenti non si
importano fra loro: comunicano solo attraverso `PipelineState`. Qui vivono le
strutture che attraversano quel confine.

Le sole due strutture che i connettori possono produrre sono `RawListing` e
`PriceObservation`. Tutto il resto e' derivato: se un campo non e' ricostruibile
dal raw, e' un bug del connettore, non del modello.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


# ═════════════════════════════════════════════════════════════════════════════
# Enum
# ═════════════════════════════════════════════════════════════════════════════

class PropertyType(str, Enum):
    ENTIRE_HOME = "entire_home"       # appartamento/casa intera
    PRIVATE_ROOM = "private_room"
    HOTEL_ROOM = "hotel_room"
    B_AND_B = "b_and_b"
    RESIDENCE = "residence"           # residence / aparthotel
    UNKNOWN = "unknown"


class ListingIntent(str, Enum):
    """Cosa viene offerto dall'annuncio: non mescolare mai i due mondi."""
    SHORT_LET = "short_let"           # affitto breve turistico (Airbnb, Booking)
    SALE = "sale"                     # vendita (Idealista, Immobiliare, OMI)
    LONG_LET = "long_let"             # affitto residenziale 4+4 / transitorio


class Season(str, Enum):
    ALTA = "alta"
    MEDIA = "media"
    SPALLA = "spalla"
    BASSA = "bassa"


class Verdict(str, Enum):
    COMPRA = "compra"
    VALUTA = "valuta"
    EVITA = "evita"
    DATI_INSUFFICIENTI = "dati_insufficienti"


class Compliance(str, Enum):
    ALLOWED = "allowed"
    REQUIRES_LICENCE = "requires_licence"
    PROHIBITED = "prohibited"


# ═════════════════════════════════════════════════════════════════════════════
# 1. Livello raw — output dei connettori
# ═════════════════════════════════════════════════════════════════════════════

class RawListing(BaseModel):
    """Payload grezzo restituito da un connettore, prima di ogni normalizzazione.

    Lo conserviamo integralmente: quando fra sei mesi il modello di pricing
    dara' un risultato strano, l'unico modo per capire se e' colpa del modello
    o del parsing e' rileggere il raw.
    """
    model_config = ConfigDict(extra="forbid")

    source: str
    source_listing_id: str
    intent: ListingIntent
    fetched_at: datetime
    payload: dict[str, Any]
    url: Optional[str] = None


# ═════════════════════════════════════════════════════════════════════════════
# 2. Livello normalizzato — output dell'agente 2
# ═════════════════════════════════════════════════════════════════════════════

class Listing(BaseModel):
    """Annuncio normalizzato, ancora legato alla singola piattaforma."""
    model_config = ConfigDict(extra="forbid")

    listing_id: str
    source: str
    source_listing_id: str
    intent: ListingIntent
    url: Optional[str] = None
    title: Optional[str] = None

    # Geografia
    comune: Optional[str] = None
    macro_market: Optional[str] = None
    provincia: Optional[str] = None
    istat_code: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    geo_precision_m: float = Field(
        default=150.0,
        description=(
            "Raggio di incertezza dichiarato sulla posizione. Airbnb offusca la "
            "posizione degli annunci non prenotati: trattare le coordinate come "
            "esatte e' il primo modo per sbagliare la deduplica."
        ),
    )

    # Caratteristiche fisiche
    property_type: PropertyType = PropertyType.UNKNOWN
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None
    max_guests: Optional[int] = None
    surface_sqm: Optional[float] = None
    amenities: list[str] = Field(default_factory=list)

    # Segnali commerciali
    base_price_eur: Optional[float] = None
    cleaning_fee_eur: Optional[float] = None
    min_nights: Optional[int] = None
    rating: Optional[float] = None
    reviews_count: Optional[int] = None
    first_review: Optional[date] = None
    last_review: Optional[date] = None

    # Host
    host_key: Optional[str] = Field(
        default=None,
        description="Hash dell'identificativo host. Mai il valore in chiaro (GDPR).",
    )
    host_listings_count: Optional[int] = None

    # Prezzo di vendita (solo intent=SALE)
    asking_price_eur: Optional[float] = None

    # Identificativo regolamentare: la chiave d'oro per la deduplica
    licence_code: Optional[str] = Field(
        default=None,
        description="CIN / CIR normalizzato (maiuscolo, senza separatori).",
    )

    fetched_at: datetime
    quality_flags: list[str] = Field(default_factory=list)

    extra: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Campi specifici della sorgente che non hanno posto nello schema comune "
            "(es. i valori OMI di riferimento per un annuncio di vendita). Tenerli "
            "qui evita sia di gonfiare il modello con colonne quasi sempre vuote, "
            "sia di perderli."
        ),
    )

    @staticmethod
    def make_id(source: str, source_listing_id: str) -> str:
        raw = f"{source}::{source_listing_id}".encode("utf-8")
        return hashlib.sha1(raw).hexdigest()[:16]


class PriceObservation(BaseModel):
    """Una notte osservata per un annuncio, a una certa data di rilevazione.

    Questa e' la tabella che rende possibile stimare l'occupazione. Con un solo
    snapshot si puo' stimare solo il prezzo; l'occupazione richiede di guardare
    lo stesso calendario piu' volte nel tempo.
    """
    model_config = ConfigDict(extra="forbid")

    listing_id: str
    stay_date: date
    observed_at: datetime
    available: bool
    price_eur: Optional[float] = None
    min_nights: Optional[int] = None


# ═════════════════════════════════════════════════════════════════════════════
# 3. Livello entita' — output della deduplica
# ═════════════════════════════════════════════════════════════════════════════

class Property(BaseModel):
    """Immobile fisico: uno o piu' annunci sulla stessa unita' immobiliare."""
    model_config = ConfigDict(extra="forbid")

    property_id: str
    listing_ids: list[str]
    sources: list[str]
    comune: Optional[str] = None
    macro_market: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    property_type: PropertyType = PropertyType.UNKNOWN
    max_guests: Optional[int] = None
    bedrooms: Optional[int] = None
    licence_code: Optional[str] = None
    merge_evidence: list[str] = Field(
        default_factory=list,
        description="Perche' questi annunci sono stati fusi. Serve a poter disfare.",
    )
    merge_confidence: float = 1.0


# ═════════════════════════════════════════════════════════════════════════════
# 4. Livello mercato — output dell'agente 3
# ═════════════════════════════════════════════════════════════════════════════

class MarketSegment(BaseModel):
    """Chiave di segmentazione. L'unita' di analisi non e' il singolo annuncio."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    macro_market: str
    property_type: PropertyType
    capacity_bucket: str

    def key(self) -> str:
        return f"{self.macro_market}|{self.property_type.value}|{self.capacity_bucket}"


class MarketStats(BaseModel):
    """Statistiche di un segmento. `sample_size` e `confidence` non sono
    decorazioni: sotto una certa numerosita' i percentili non significano nulla
    e l'agente 5 deve dirlo invece di narrare un numero."""
    model_config = ConfigDict(extra="forbid")

    segment: MarketSegment
    sample_size: int
    n_price_observations: int

    adr_p25: Optional[float] = None
    adr_p50: Optional[float] = None
    adr_p75: Optional[float] = None
    adr_p90: Optional[float] = None

    occupancy_est: Optional[float] = None
    occupancy_method: str = "prior"
    revpar_est: Optional[float] = None
    annual_revenue_est: Optional[float] = None

    seasonality_index: dict[int, float] = Field(default_factory=dict)
    confidence: str = "bassa"          # bassa | media | alta
    caveats: list[str] = Field(default_factory=list)


class PricingAdvice(BaseModel):
    """Raccomandazione di prezzo per un immobile in un segmento."""
    model_config = ConfigDict(extra="forbid")

    property_id: str
    segment_key: str
    current_adr: Optional[float] = None
    suggested_adr_by_month: dict[int, float] = Field(default_factory=dict)
    suggested_adr_annual_avg: Optional[float] = None
    position_vs_market: Optional[str] = None   # sotto | in_linea | sopra
    percentile_in_segment: Optional[float] = None
    expected_revenue_delta_eur: Optional[float] = None
    rationale: list[str] = Field(default_factory=list)


class DealCandidate(BaseModel):
    """Immobile in vendita agganciato al suo segmento di mercato locativo.

    È il ponte fra i due mondi: senza di questo il sistema sa dire quanto si
    affitta e quanto costa comprare, ma non sa metterli in relazione.
    """
    model_config = ConfigDict(extra="forbid")

    listing_id: str
    comune: str
    macro_market: str
    asking_price_eur: float
    surface_sqm: Optional[float] = None
    price_per_sqm: Optional[float] = None
    omi_min_eur_sqm: Optional[float] = None
    omi_max_eur_sqm: Optional[float] = None
    vs_omi_pct: Optional[float] = None
    segment_key: Optional[str] = None
    expected_annual_revenue_eur: Optional[float] = None


# ═════════════════════════════════════════════════════════════════════════════
# 5. Livello investimento — output dell'agente 4
# ═════════════════════════════════════════════════════════════════════════════

class AcquisitionBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purchase_price: float
    agency_fee: float
    notary_fee: float
    transfer_taxes: float
    renovation: float
    furnishing: float
    setup: float
    total: float


class OperatingBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gross_revenue: float
    ota_commission: float
    cleaning: float
    utilities: float
    condo_fees: float
    insurance: float
    maintenance: float
    property_management: float
    imu: float
    tari: float
    total_opex: float
    noi: float                      # net operating income, ante imposte sul reddito
    income_tax: float
    tax_regime_used: str
    tax_regime_alternative_cost: Optional[float] = None
    net_cashflow_pre_debt: float
    debt_service: float
    net_cashflow: float


class UnderwritingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: str
    property_ref: str
    acquisition: AcquisitionBreakdown
    operating: OperatingBreakdown

    gross_yield: float
    net_yield: float
    cap_rate: float
    cash_on_cash: Optional[float] = None
    dscr: Optional[float] = None
    payback_years: Optional[float] = None
    break_even_occupancy: Optional[float] = None
    npv: Optional[float] = None
    irr: Optional[float] = None

    verdict: Verdict = Verdict.DATI_INSUFFICIENTI
    verdict_reasons: list[str] = Field(default_factory=list)
    sensitivity: dict[str, dict[str, float]] = Field(default_factory=dict)


# ═════════════════════════════════════════════════════════════════════════════
# 6. Qualita' dati — output del supervisore
# ═════════════════════════════════════════════════════════════════════════════

class QualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n_raw: int = 0
    n_listings: int = 0
    n_properties: int = 0
    n_dropped: int = 0
    dedup_ratio: float = 0.0
    coverage_by_source: dict[str, int] = Field(default_factory=dict)
    segments_below_min_sample: list[str] = Field(default_factory=list)
    blocking_issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.blocking_issues


# ═════════════════════════════════════════════════════════════════════════════
# 7. Stato della pipeline
# ═════════════════════════════════════════════════════════════════════════════

class Perimeter(BaseModel):
    """Cosa analizzare. Tutti i campi sono opzionali: assenti = nessun filtro."""
    model_config = ConfigDict(extra="forbid")

    macro_markets: Optional[list[str]] = None
    comuni: Optional[list[str]] = None
    property_types: Optional[list[PropertyType]] = None
    min_guests: Optional[int] = None
    max_guests: Optional[int] = None
    year: Optional[int] = None


class PipelineState(BaseModel):
    """Stato che scorre fra i nodi. Ogni agente legge i campi dei predecessori
    e scrive solo i propri."""
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    perimeter: Perimeter = Field(default_factory=Perimeter)

    # A1 Ingestion
    raw_listings: list[RawListing] = Field(default_factory=list)
    price_observations: list[PriceObservation] = Field(default_factory=list)
    ingestion_meta: dict[str, Any] = Field(default_factory=dict)

    # A2 Resolution
    listings: list[Listing] = Field(default_factory=list)
    properties: list[Property] = Field(default_factory=list)
    resolution_meta: dict[str, Any] = Field(default_factory=dict)

    # Supervisor
    quality: Optional[QualityReport] = None

    # A3 Market
    market_stats: list[MarketStats] = Field(default_factory=list)
    pricing_advice: list[PricingAdvice] = Field(default_factory=list)
    deal_candidates: list[DealCandidate] = Field(default_factory=list)
    market_meta: dict[str, Any] = Field(default_factory=dict)

    # A4 Underwriting
    underwriting: list[UnderwritingResult] = Field(default_factory=list)
    underwriting_meta: dict[str, Any] = Field(default_factory=dict)

    # A5 Report
    report: Optional[dict[str, Any]] = None
    report_path: Optional[str] = None

    # Diagnostica trasversale
    errors: list[str] = Field(default_factory=list)
    trace: list[dict[str, Any]] = Field(default_factory=list)
