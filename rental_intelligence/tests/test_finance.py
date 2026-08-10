"""Test del modello finanziario.

Ogni test verifica un'invariante economica, non solo che il codice non esploda.
Sono i test che permettono di cambiare un'aliquota in fiscale.yaml e sapere
subito se si e' rotto qualcosa a valle.
"""

from __future__ import annotations

import copy

import pytest

from rental_intelligence.ri import config
from rental_intelligence.ri.analytics import finance
from rental_intelligence.ri.analytics.revenue import annual_revenue
from rental_intelligence.ri.models import Verdict


@pytest.fixture
def cfg():
    return copy.deepcopy(config.fiscale())


# ── acquisizione ─────────────────────────────────────────────────────────────

def test_costo_acquisizione_supera_sempre_il_prezzo(cfg):
    acq = finance.acquisition_costs(250_000, cfg=cfg)
    assert acq.total > acq.purchase_price
    # Le componenti devono ricomporre il totale: se questa salta, un costo
    # e' stato aggiunto al totale senza comparire nel dettaglio.
    parts = (acq.purchase_price + acq.agency_fee + acq.notary_fee
             + acq.transfer_taxes + acq.renovation + acq.furnishing + acq.setup)
    assert acq.total == pytest.approx(parts, abs=0.01)


def test_regime_prezzo_valore_riduce_le_imposte_datto(cfg):
    """Con la rendita catastale nota, la base imponibile e' quasi sempre piu'
    bassa del prezzo: e' il beneficio del regime prezzo-valore."""
    senza = finance.acquisition_costs(300_000, cfg=cfg)
    con = finance.acquisition_costs(300_000, rendita_catastale=900, cfg=cfg)
    assert con.transfer_taxes < senza.transfer_taxes


# ── gestione ─────────────────────────────────────────────────────────────────

def test_cedolare_tassa_il_lordo_non_il_netto(cfg):
    """Il punto fiscale che quasi tutti i calcolatori online sbagliano.

    Sotto cedolare secca l'imponibile e' il corrispettivo lordo: le commissioni
    OTA non si deducono. Quindi l'imposta deve essere esattamente
    aliquota x ricavo lordo, indipendentemente da quanto pesano i costi.
    """
    cfg["imposte"]["regime"] = "cedolare"
    aliquota = cfg["imposte"]["cedolare"]["aliquota_pct"]
    ops = finance.operating_model(30_000, 180, cfg=cfg)
    assert ops.tax_regime_used == "cedolare"
    assert ops.income_tax == pytest.approx(30_000 * aliquota, abs=0.01)


def test_regime_migliore_sceglie_il_meno_oneroso(cfg):
    cfg["imposte"]["regime"] = "migliore"
    ops = finance.operating_model(30_000, 180, cfg=cfg)
    assert ops.tax_regime_alternative_cost is not None
    assert ops.income_tax <= ops.tax_regime_alternative_cost


def test_con_costi_alti_lordinario_puo_battere_la_cedolare(cfg):
    """Con commissioni e gestione molto alte il margine si assottiglia, ma la
    cedolare continua a tassare il lordo: e' il caso in cui il regime ordinario
    diventa conveniente. Se questo test smette di passare, il modello ha perso
    la distinzione fra base lorda e base netta."""
    cfg["imposte"]["regime"] = "migliore"
    cfg["gestione"]["commissione_ota_pct"] = 0.20
    cfg["gestione"]["property_management_pct"] = 0.30
    cfg["imposte"]["ordinario"]["aliquota_irpef_marginale_pct"] = 0.23

    ops = finance.operating_model(25_000, 150, cfg=cfg)
    assert ops.tax_regime_used == "ordinario"


def test_le_pulizie_scalano_con_i_soggiorni_non_con_le_notti(cfg):
    """Raddoppiare la durata media del soggiorno dimezza il numero di pulizie."""
    base = finance.operating_model(20_000, 200, cfg=cfg)
    cfg2 = copy.deepcopy(cfg)
    cfg2["gestione"]["soggiorno_medio_notti"] = cfg["gestione"]["soggiorno_medio_notti"] * 2
    doppio = finance.operating_model(20_000, 200, cfg=cfg2)
    assert doppio.cleaning == pytest.approx(base.cleaning / 2, rel=0.01)


# ── break-even ───────────────────────────────────────────────────────────────

def test_break_even_cresce_con_i_costi_fissi(cfg):
    basso = finance.break_even_occupancy(150, 365, 4_000, 0.40, cost_per_night=15)
    alto = finance.break_even_occupancy(150, 365, 9_000, 0.40, cost_per_night=15)
    assert basso is not None and alto is not None
    assert alto > basso


def test_break_even_impossibile_restituisce_none():
    """Se il margine per notte e' negativo, nessuna occupazione porta al
    pareggio. Il modello deve dirlo invece di restituire un numero enorme che
    sembra una risposta."""
    assert finance.break_even_occupancy(50, 365, 5_000, 0.60, cost_per_night=30) is None


def test_ignorare_le_pulizie_sottostima_il_break_even():
    con = finance.break_even_occupancy(160, 365, 6_000, 0.42, cost_per_night=17)
    senza = finance.break_even_occupancy(160, 365, 6_000, 0.42, cost_per_night=0)
    assert con > senza


# ── VAN / TIR ────────────────────────────────────────────────────────────────

def test_van_positivo_quando_il_flusso_supera_il_tasso_di_sconto(cfg):
    cfg["valutazione"]["tasso_sconto_pct"] = 0.03
    result = finance.npv_irr(200_000, 25_000, 200_000, cfg=cfg)
    assert result["npv"] > 0
    assert result["irr"] is not None and result["irr"] > 0.03


def test_tir_none_se_i_flussi_non_cambiano_mai_segno():
    """Un investimento che perde soldi in ogni periodo non ha un TIR: la
    funzione deve restituire None, non un numero inventato."""
    assert finance._irr([-100_000, -5_000, -5_000, -5_000]) is None


def test_tir_coerente_con_una_rendita_perpetua_nota():
    """Investo 100.000 e ricevo 10.000 all'anno per 30 anni: il TIR deve
    stare vicino al 9.3% (valore analitico noto)."""
    flows = [-100_000] + [10_000] * 30
    irr = finance._irr(flows)
    assert irr is not None
    assert 0.088 < irr < 0.098


# ── underwriting completo ────────────────────────────────────────────────────

def test_underwrite_produce_un_verdetto_coerente(cfg):
    revenue = annual_revenue(140, 0.48, "tigullio")
    result = finance.underwrite(
        scenario="test",
        property_ref="test",
        purchase_price=280_000,
        annual_gross_revenue=revenue["annual_gross_revenue"],
        nights_sold=revenue["nights_sold"],
        adr=revenue["effective_adr"],
        cfg=cfg,
    )
    assert result.verdict in set(Verdict)
    assert result.verdict_reasons, "un verdetto senza motivazioni non e' verificabile"
    # Il netto non puo' superare il lordo: se succede, un costo ha segno sbagliato.
    assert result.net_yield < result.gross_yield


def test_prezzo_piu_alto_abbassa_il_rendimento(cfg):
    revenue = annual_revenue(140, 0.50, "tigullio")
    kwargs = dict(
        scenario="test", property_ref="test",
        annual_gross_revenue=revenue["annual_gross_revenue"],
        nights_sold=revenue["nights_sold"], adr=revenue["effective_adr"], cfg=cfg,
    )
    economico = finance.underwrite(purchase_price=200_000, **kwargs)
    caro = finance.underwrite(purchase_price=400_000, **kwargs)
    assert economico.net_yield > caro.net_yield


def test_la_sensibilita_e_monotona_sui_ricavi(cfg):
    revenue = annual_revenue(140, 0.48, "tigullio")
    result = finance.underwrite(
        scenario="test", property_ref="test", purchase_price=280_000,
        annual_gross_revenue=revenue["annual_gross_revenue"],
        nights_sold=revenue["nights_sold"], adr=revenue["effective_adr"], cfg=cfg,
    )
    ricavi = result.sensitivity["ricavi"]
    assert ricavi["-30%"] < ricavi["-20%"] < ricavi["-10%"] < ricavi["base"] < ricavi["+10%"]


# ── stagionalita' ────────────────────────────────────────────────────────────

def test_la_stagionalita_alza_il_ricavo_in_un_mercato_balneare():
    """ADR e occupazione sono correlati positivamente in Liguria: agosto e'
    caro E pieno. La media dei prodotti mensili supera il prodotto delle medie,
    quindi ignorare la stagionalita' sottostima il ricavo."""
    con = annual_revenue(120, 0.45, "cinque_terre", apply_seasonality=True)
    senza = annual_revenue(120, 0.45, "cinque_terre", apply_seasonality=False)
    assert con["annual_gross_revenue"] > senza["annual_gross_revenue"]


def test_il_ricavo_mensile_copre_dodici_mesi():
    result = annual_revenue(100, 0.5, "tigullio")
    assert sorted(result["monthly"]) == list(range(1, 13))
    assert sum(result["monthly"].values()) == pytest.approx(
        result["annual_gross_revenue"], rel=0.001)


def test_la_cella_base_della_sensibilita_coincide_col_rendimento_netto(cfg):
    """Difetto reale trovato in fase di verifica: la griglia di sensibilita'
    non riceveva la rendita catastale, quindi ricadeva sulle stime di ripiego
    per IMU e imposte d'atto. Risultato: due numeri diversi per la stessa
    ipotesi nella stessa schermata."""
    revenue = annual_revenue(155, 0.52, "cinque_terre")
    result = finance.underwrite(
        scenario="test", property_ref="test", purchase_price=240_000,
        annual_gross_revenue=revenue["annual_gross_revenue"],
        nights_sold=revenue["nights_sold"], adr=revenue["effective_adr"],
        surface_sqm=60, rendita_catastale=700, cfg=cfg,
    )
    assert result.sensitivity["ricavi"]["base"] == pytest.approx(result.net_yield, abs=0.0005)
    assert result.sensitivity["prezzo_acquisto"]["base"] == pytest.approx(
        result.net_yield, abs=0.0005)
