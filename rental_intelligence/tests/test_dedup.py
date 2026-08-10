"""Test della deduplica.

Il generatore sintetico conosce la verita': sa quali annunci sono lo stesso
immobile fisico. È l'unico modo onesto di misurare la qualita' di un
algoritmo di entity resolution senza un dataset etichettato a mano.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from rental_intelligence.ri.analytics import dedup
from rental_intelligence.ri.models import Listing, ListingIntent, PropertyType


def make_listing(**overrides) -> Listing:
    base = dict(
        listing_id="x",
        source="a",
        source_listing_id="1",
        intent=ListingIntent.SHORT_LET,
        title="Bilocale vista mare a Vernazza",
        comune="Vernazza",
        macro_market="cinque_terre",
        lat=44.135,
        lon=9.684,
        property_type=PropertyType.ENTIRE_HOME,
        max_guests=4,
        bedrooms=2,
        surface_sqm=55.0,
        amenities=["wifi", "cucina", "vista_mare", "lavatrice"],
        fetched_at=datetime(2026, 8, 10, 12, 0),
    )
    base.update(overrides)
    return Listing(**base)


# ── punteggio ────────────────────────────────────────────────────────────────

def test_cin_identico_forza_la_fusione():
    a = make_listing(listing_id="a", source="airbnb", licence_code="IT-011 023 ABC")
    b = make_listing(
        listing_id="b", source="booking", licence_code="it011023abc",
        title="Un titolo completamente diverso", lat=44.20, lon=9.80, max_guests=8,
    )
    result = dedup.score_pair(a, b)
    assert result.exact_licence
    assert result.score == 1.0


def test_cin_diversi_escludono_la_coppia():
    """Due CIN diversi sono l'unico segnale che da solo puo' dire 'no'."""
    a = make_listing(listing_id="a", source="airbnb", licence_code="IT001")
    b = make_listing(listing_id="b", source="booking", licence_code="IT002")
    assert dedup.score_pair(a, b).score == 0.0


def test_offuscamento_geografico_non_impedisce_il_match():
    """~130 m di scarto e' l'offuscamento tipico delle OTA: la coppia deve
    restare sopra soglia."""
    a = make_listing(listing_id="a", source="airbnb")
    b = make_listing(
        listing_id="b", source="booking",
        lat=44.1362, lon=9.6855,               # ~150 m
        title="Vernazza mare bilocale vista",
    )
    assert dedup.score_pair(a, b).score >= dedup.MATCH_THRESHOLD


def test_immobili_lontani_non_matchano():
    a = make_listing(listing_id="a", source="airbnb")
    b = make_listing(listing_id="b", source="booking", lat=44.31, lon=9.21,
                     comune="Rapallo", title="Trilocale centro Rapallo")
    assert dedup.score_pair(a, b).score < dedup.MATCH_THRESHOLD


def test_dato_mancante_non_penalizza():
    """Un annuncio senza superficie non deve risultare meno simile di uno che
    la dichiara uguale: assenza di dato non e' disaccordo."""
    a = make_listing(listing_id="a", source="airbnb")
    b_completo = make_listing(listing_id="b", source="booking", lat=44.1352, lon=9.6845)
    b_parziale = make_listing(listing_id="c", source="booking", lat=44.1352, lon=9.6845,
                              surface_sqm=None, bedrooms=None)
    pieno = dedup.score_pair(a, b_completo).score
    parziale = dedup.score_pair(a, b_parziale).score
    assert parziale >= pieno - 0.12


def test_normalizzazione_licenza():
    assert dedup.normalize_licence("IT-011 023/ABC") == "IT011023ABC"
    assert dedup.normalize_licence("  ") is None
    assert dedup.normalize_licence(None) is None


# ── clustering ───────────────────────────────────────────────────────────────

def test_stessa_piattaforma_non_viene_mai_fusa():
    """Due unita' nello stesso stabile pubblicate dallo stesso portale sono
    quasi sempre immobili diversi. Fonderli e' un errore piu' costoso del
    contrario, perche' rimuove offerta reale dal conteggio."""
    a = make_listing(listing_id="a", source="airbnb", licence_code=None)
    b = make_listing(listing_id="b", source="airbnb", licence_code=None)
    props, meta = dedup.deduplicate([a, b])
    assert meta["n_properties"] == 2


def test_gli_annunci_in_vendita_restano_fuori():
    short = make_listing(listing_id="a", source="airbnb")
    sale = make_listing(listing_id="b", source="portale", intent=ListingIntent.SALE,
                        asking_price_eur=300_000)
    props, meta = dedup.deduplicate([short, sale])
    assert meta["n_input"] == 1
    assert len(props) == 1


def test_deduplica_sul_dataset_sintetico_recupera_la_verita():
    """Test end-to-end contro la verita' nota del generatore.

    Il demo espone il CIN su tutti gli annunci, quindi qui si misura il
    percorso a chiave esatta. Il test successivo toglie il CIN e misura il
    percorso probabilistico, che e' la situazione reale finche' la copertura
    del registro non sale.
    """
    from rental_intelligence.ri.agents import a1_ingestion, a2_resolution
    from rental_intelligence.ri.models import Perimeter, PipelineState

    state = PipelineState(perimeter=Perimeter(macro_markets=["cinque_terre"]))
    state = a1_ingestion.run(state)
    state = a2_resolution.run(state)

    truth = {}
    for raw in state.raw_listings:
        if raw.intent is ListingIntent.SHORT_LET:
            truth[Listing.make_id(raw.source, raw.source_listing_id)] = \
                raw.payload["unit_key"]

    n_true_units = len(set(truth.values()))
    assert len(state.properties) == n_true_units, (
        f"attesi {n_true_units} immobili distinti, trovati {len(state.properties)}"
    )

    # Nessun cluster deve mescolare due unita' diverse.
    for prop in state.properties:
        units = {truth[lid] for lid in prop.listing_ids if lid in truth}
        assert len(units) == 1, f"cluster {prop.property_id} mescola {units}"


def test_deduplica_senza_cin_resta_utile():
    """Senza CIN il matching e' probabilistico. Non deve essere perfetto, ma
    deve recuperare una quota sostanziale dei duplicati senza fonderne di
    sbagliati: la precisione conta piu' del richiamo, perche' una fusione
    errata cancella offerta reale."""
    from rental_intelligence.ri.agents import a1_ingestion, a2_resolution
    from rental_intelligence.ri.models import Perimeter, PipelineState

    state = PipelineState(perimeter=Perimeter(macro_markets=["cinque_terre"]))
    state = a1_ingestion.run(state)
    state = a2_resolution.run(state)

    truth = {
        Listing.make_id(r.source, r.source_listing_id): r.payload["unit_key"]
        for r in state.raw_listings if r.intent is ListingIntent.SHORT_LET
    }
    stripped = [l.model_copy(update={"licence_code": None}) for l in state.listings]
    props, meta = dedup.deduplicate(stripped)

    n_true = len(set(truth.values()))
    n_short = meta["n_input"]

    # Precisione: nessun cluster deve mescolare unita' diverse.
    impure = sum(
        1 for p in props
        if len({truth[lid] for lid in p.listing_ids if lid in truth}) > 1
    )
    assert impure == 0, f"{impure} cluster mescolano immobili diversi"

    # Richiamo. La soglia e' fissata a 0.60, ben sotto il valore attuale
    # (1.00 sul sintetico), perche' serve da guardia di regressione e non da
    # dichiarazione di prestazione: sui dati veri il richiamo sara' piu' basso,
    # perche' i duplicati reali divergono molto piu' di quelli generati qui.
    duplicates_true = n_short - n_true
    duplicates_found = n_short - len(props)
    if duplicates_true > 0:
        recall = duplicates_found / duplicates_true
        assert recall >= 0.60, f"richiamo troppo basso senza CIN: {recall:.0%}"


def test_il_vincolo_di_esclusivita_blocca_la_chiusura_transitiva():
    """Difetto reale trovato dai test, non ipotetico.

    A~B e B~C fondono anche A e C tramite union-find, anche quando A e C sono
    due annunci della stessa piattaforma — cioe' esattamente la coppia che il
    confronto diretto rifiuta di valutare. Senza il vincolo, questo produceva
    19 cluster con immobili diversi mescolati su 420.
    """
    common = dict(lat=44.1350, lon=9.6840, max_guests=4, bedrooms=2,
                  surface_sqm=60.0, title="Attico terrazzo panoramico soleggiato")

    a = make_listing(listing_id="a", source="airbnb", licence_code=None, **common)
    b = make_listing(listing_id="b", source="booking", licence_code=None, **common)
    c = make_listing(listing_id="c", source="airbnb", licence_code=None, **common)

    props, meta = dedup.deduplicate([a, b, c])

    for prop in props:
        sources = [lid for lid in prop.listing_ids]
        assert len(sources) == len(set(sources))
        # Nessun cluster puo' contenere due annunci della stessa piattaforma.
        srcs = [l.source for l in (a, b, c) if l.listing_id in prop.listing_ids]
        assert len(srcs) == len(set(srcs)), f"cluster con sorgenti duplicate: {srcs}"

    assert meta["n_rejected_source_conflict"] >= 1


def test_meta_riporta_la_copertura_del_cin():
    a = make_listing(listing_id="a", source="airbnb", licence_code="IT001")
    b = make_listing(listing_id="b", source="booking", licence_code=None,
                     lat=44.30, lon=9.20)
    _, meta = dedup.deduplicate([a, b])
    assert meta["licence_coverage"] == pytest.approx(0.5)
