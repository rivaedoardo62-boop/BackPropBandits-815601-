"""Test di pipeline, gate di conformita' e stima di occupazione."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from rental_intelligence.ri import connectors, geo
from rental_intelligence.ri.analytics import pricing, revenue
from rental_intelligence.ri.models import Perimeter, PipelineState, PriceObservation
from rental_intelligence.ri.orchestrator import run_pipeline


# ── conformita' ──────────────────────────────────────────────────────────────

def test_le_sorgenti_vietate_non_si_possono_istanziare():
    """Il gate legale sta nel codice, non nella buona volonta'.

    Nel registro le sorgenti di scraping esistono solo come voci documentate:
    non c'e' una classe registrata, e se qualcuno la scrivesse il gate di
    conformita' la fermerebbe comunque.
    """
    assert "airbnb_scraping" not in connectors.available()
    assert "booking_scraping" not in connectors.available()
    with pytest.raises(KeyError):
        connectors.build("airbnb_scraping")


def test_le_sorgenti_accreditate_senza_chiavi_non_partono(monkeypatch):
    for key in ("IDEALISTA_API_KEY", "IDEALISTA_API_SECRET"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(connectors.MissingCredentials):
        connectors.build("idealista_api")


# ── geografia ────────────────────────────────────────────────────────────────

def test_gli_alias_di_frazione_si_risolvono_al_comune():
    """Le OTA presentano Corniglia e Manarola come se fossero comuni: senza
    rimappatura i conteggi per comune sarebbero sbagliati."""
    assert geo.resolve_comune("Corniglia")[0] == "Vernazza"
    assert geo.resolve_comune("Manarola")[0] == "Riomaggiore"
    assert geo.resolve_comune("Arma di Taggia")[0] == "Taggia"


def test_i_comuni_fuori_liguria_non_si_risolvono():
    """Nessun fuzzy matching: un comune sconosciuto e' un segnale da mostrare,
    non da indovinare."""
    assert geo.resolve_comune("Milano") == (None, None, None)
    assert geo.resolve_comune("Vernazzza") == (None, None, None)


def test_la_normalizzazione_ignora_accenti_e_maiuscole():
    assert geo.resolve_comune("MONTEROSSO AL MARE")[0] == "Monterosso al Mare"
    assert geo.resolve_comune("santa margherita ligure")[0] == "Santa Margherita Ligure"


def test_genova_ha_profilo_urbano():
    assert geo.market_profile("genova_citta") == "urbano"
    assert geo.market_profile("cinque_terre") == "costiero"


def test_distanza_haversine_su_valore_noto():
    """Genova - La Spezia in linea d'aria: circa 75-80 km."""
    d = geo.haversine_m(44.407, 8.934, 44.103, 9.828)
    assert 74_000 < d < 82_000


# ── occupazione ──────────────────────────────────────────────────────────────

def _obs(listing_id, day, observed_at, available):
    return PriceObservation(
        listing_id=listing_id, stay_date=day, observed_at=observed_at,
        available=available, price_eur=100.0 if available else None,
    )


def test_il_panel_distingue_venduto_da_bloccato():
    """Il caso che giustifica l'intero modulo storage.

    30 notti aperte alla prima rilevazione, 15 chiuse alla seconda -> venduto.
    30 notti chiuse fin dall'inizio -> bloccate dall'host, fuori dal
    denominatore. L'occupazione corretta e' 15/30 = 50%, non 45/60 = 75%.
    """
    t1 = datetime(2026, 8, 1, 9, 0)
    t2 = datetime(2026, 8, 15, 9, 0)
    obs = []
    for i in range(30):                       # notti aperte, meta' poi vendute
        day = date(2026, 10, 1) + timedelta(days=i)
        obs.append(_obs("L", day, t1, True))
        obs.append(_obs("L", day, t2, i >= 15))
    for i in range(30):                       # notti sempre chiuse
        day = date(2026, 12, 1) + timedelta(days=i)
        obs.append(_obs("L", day, t1, False))
        obs.append(_obs("L", day, t2, False))

    est = revenue.occupancy_from_panel(obs)
    assert est is not None
    assert est.method == "panel"
    assert est.occupancy == pytest.approx(0.50, abs=0.01)


def test_lo_snapshot_scarta_una_quota_di_notti_bloccate():
    t = datetime(2026, 8, 1, 9, 0)
    obs = [_obs("L", date(2026, 9, 1) + timedelta(days=i), t, i >= 50) for i in range(100)]
    est = revenue.occupancy_from_snapshot(obs, blocked_share=0.25)
    assert est is not None
    assert est.occupancy == pytest.approx(0.50 * 0.75, abs=0.01)
    assert est.confidence == "bassa"


def test_il_metodo_a_recensioni_e_dichiarato_inaffidabile():
    est = revenue.occupancy_from_reviews(
        reviews_count=48, first_review=date(2024, 1, 1), last_review=date(2026, 1, 1)
    )
    assert est is not None
    assert est.method == "reviews"
    assert est.confidence == "bassa"
    assert est.caveats


def test_il_prior_e_lultima_risorsa_e_lo_dice():
    est = revenue.occupancy_from_prior("cinque_terre")
    assert est.method == "prior"
    assert any("prior" in c for c in est.caveats)


def test_locupazione_non_supera_mai_il_massimo_plausibile():
    est = revenue.occupancy_from_reviews(
        reviews_count=5000, first_review=date(2025, 1, 1), last_review=date(2026, 1, 1)
    )
    assert est is not None
    assert est.occupancy <= revenue.MAX_PLAUSIBLE_OCCUPANCY


# ── pricing ──────────────────────────────────────────────────────────────────

def test_la_calibrazione_stagionale_rifiuta_dati_parziali():
    """Con tre mesi di dati un indice stagionale annuale sarebbe una
    proiezione travestita da misura: la funzione deve rifiutarsi."""
    t = datetime(2026, 8, 1)
    obs = [
        PriceObservation(listing_id="L", stay_date=date(2026, m, 15),
                         observed_at=t, available=True, price_eur=100.0)
        for m in (7, 8, 9)
    ]
    with pytest.raises(ValueError, match="mancano osservazioni"):
        pricing.calibrate_seasonality(obs)


def test_i_bucket_di_capienza_coprono_tutto():
    assert geo.capacity_bucket(2) == "1-2"
    assert geo.capacity_bucket(4) == "3-4"
    assert geo.capacity_bucket(12) == "7+"
    assert geo.capacity_bucket(None) == "sconosciuta"


# ── pipeline end-to-end ──────────────────────────────────────────────────────

def test_la_pipeline_gira_end_to_end():
    state = run_pipeline(Perimeter(macro_markets=["cinque_terre"]), save_report=False)
    assert state.raw_listings
    assert state.listings
    assert state.properties
    assert state.market_stats
    assert state.report is not None
    assert not state.errors


def test_ogni_agente_lascia_traccia():
    state = run_pipeline(Perimeter(macro_markets=["tigullio"]), save_report=False)
    agents = [t["agent"] for t in state.trace]
    for expected in ("a1_ingestion", "a2_resolution", "supervisor", "a3_market", "a5_report"):
        assert expected in agents


def test_il_gate_qualita_blocca_i_perimetri_troppo_piccoli():
    """Con un perimetro che non produce abbastanza annunci, il sistema deve
    dire di non poter analizzare invece di produrre percentili su otto punti."""
    state = run_pipeline(Perimeter(comuni=["Framura"]), save_report=False)
    assert state.quality is not None
    if not state.quality.passed:
        assert state.report["meta"]["modalita_narrazione"] == "bloccato"
        assert state.report["narrazione"]["blocchi"]


def test_il_report_dichiara_sempre_la_natura_sintetica_dei_dati_demo():
    state = run_pipeline(Perimeter(macro_markets=["tigullio"]), save_report=False)
    warnings = " ".join(state.quality.warnings) if state.quality else ""
    assert "sintetico" in warnings


def test_senza_chiave_il_report_esce_comunque():
    """L'LLM e' un miglioramento, non un ingranaggio strutturale."""
    state = run_pipeline(Perimeter(macro_markets=["tigullio"]), save_report=False)
    assert state.report["meta"]["modalita_narrazione"] in {"template", "bloccato"}
    assert state.report["mercato"]["segmenti"]


def test_il_perimetro_filtra_davvero():
    state = run_pipeline(Perimeter(macro_markets=["cinque_terre"]), save_report=False)
    assert {l.macro_market for l in state.listings} == {"cinque_terre"}


# ── persistenza ──────────────────────────────────────────────────────────────

def test_la_persistenza_conserva_le_rilevazioni_ripetute(tmp_path):
    """La chiave primaria include observed_at: due rilevazioni della stessa
    notte devono coesistere, altrimenti il panel non esiste."""
    from rental_intelligence.ri import storage

    db = tmp_path / "test.sqlite"
    obs = [
        _obs("L", date(2026, 10, 1), datetime(2026, 8, 1, 9, 0), True),
        _obs("L", date(2026, 10, 1), datetime(2026, 8, 15, 9, 0), False),
    ]
    with storage.connect(db) as conn:
        storage.save_observations(conn, obs)
    with storage.connect(db) as conn:
        loaded = storage.load_observations(conn)
        depth = storage.panel_depth(conn)

    assert len(loaded) == 2
    assert depth["snapshots"] == 2
