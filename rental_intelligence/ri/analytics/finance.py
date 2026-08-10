"""Modello finanziario dell'investimento: da "quanto rende" a "conviene".

Ogni numero prodotto qui e' deterministico e ricalcolabile a mano: nessuna
parte del giudizio d'investimento passa da un modello linguistico. L'LLM
dell'agente 5 riceve questi risultati gia' calcolati e li spiega; non li
inventa, non li ricalcola, non li corregge.

Tutti i parametri vengono da `config/fiscale.yaml`, che porta in testa
l'avvertenza da leggere prima di fidarsi delle aliquote.

Un punto fiscale che cambia materialmente il risultato e che quasi tutti i
calcolatori online sbagliano: sotto **cedolare secca** la base imponibile e' il
corrispettivo LORDO, comprese le somme addebitate all'ospite per le pulizie, e
le commissioni delle piattaforme NON sono deducibili. Con commissioni OTA al
16% e property management al 20%, la cedolare al 21% su un lordo di 20.000 €
costa 4.200 € pur essendo il margine reale molto piu' basso. È esattamente il
caso in cui il regime ordinario, che tassa il netto, puo' convenire. Il modello
calcola entrambi e usa il migliore, riportando quanto costa l'alternativa.
"""

from __future__ import annotations

from typing import Optional

from .. import config
from ..models import (
    AcquisitionBreakdown,
    OperatingBreakdown,
    UnderwritingResult,
    Verdict,
)


# ═════════════════════════════════════════════════════════════════════════════
# Acquisizione
# ═════════════════════════════════════════════════════════════════════════════

def acquisition_costs(
    purchase_price: float,
    *,
    surface_sqm: Optional[float] = None,
    rendita_catastale: Optional[float] = None,
    renovation_eur: Optional[float] = None,
    furnishing_eur: Optional[float] = None,
    cfg: Optional[dict] = None,
) -> AcquisitionBreakdown:
    """Costo pieno per portare l'immobile a reddito.

    Il denominatore di ogni rendimento e' questo, non il prezzo di acquisto:
    calcolare il rendimento sul solo prezzo gonfia il risultato del 10-20% e
    rende due immobili con costi accessori diversi apparentemente equivalenti.
    """
    f = (cfg or config.fiscale())["acquisizione"]

    agency = purchase_price * float(f["provvigione_agenzia_pct"])
    notary = float(f["notaio_eur"])

    tax_cfg = f["imposte_atto"]
    if tax_cfg["base"] == "catastale" and rendita_catastale:
        taxable = (rendita_catastale
                   * float(tax_cfg["rivalutazione_rendita"])
                   * float(tax_cfg["moltiplicatore_catastale"]))
    else:
        # Senza rendita catastale nota si ricade sul prezzo. È prudenziale:
        # sovrastima l'imposta rispetto al regime prezzo-valore.
        taxable = purchase_price

    transfer = (taxable * float(tax_cfg["aliquota_registro_pct"])
                + float(tax_cfg["imposta_ipotecaria_eur"])
                + float(tax_cfg["imposta_catastale_eur"]))

    if renovation_eur is None:
        per_sqm = float(f.get("ristrutturazione_eur_mq_default", 0) or 0)
        renovation_eur = per_sqm * (surface_sqm or 0)
    furnishing = float(f["arredo_eur_default"]) if furnishing_eur is None else furnishing_eur
    setup = float(f["pratiche_avvio_eur"])

    total = purchase_price + agency + notary + transfer + renovation_eur + furnishing + setup

    return AcquisitionBreakdown(
        purchase_price=round(purchase_price, 2),
        agency_fee=round(agency, 2),
        notary_fee=round(notary, 2),
        transfer_taxes=round(transfer, 2),
        renovation=round(renovation_eur, 2),
        furnishing=round(furnishing, 2),
        setup=round(setup, 2),
        total=round(total, 2),
    )


# ═════════════════════════════════════════════════════════════════════════════
# Gestione annua
# ═════════════════════════════════════════════════════════════════════════════

def operating_model(
    gross_revenue: float,
    nights_sold: float,
    *,
    rendita_catastale: Optional[float] = None,
    property_value: Optional[float] = None,
    debt_service: float = 0.0,
    cfg: Optional[dict] = None,
) -> OperatingBreakdown:
    """Conto economico annuo dell'immobile a reddito."""
    conf = cfg or config.fiscale()
    g = conf["gestione"]
    t = conf["imposte"]

    ota = gross_revenue * float(g["commissione_ota_pct"])

    los = max(float(g["soggiorno_medio_notti"]), 1.0)
    n_stays = nights_sold / los
    cleaning = n_stays * float(g["pulizia_eur_per_soggiorno"])

    utilities = float(g["utenze_fisse_eur_anno"]) + nights_sold * float(g["utenze_variabili_eur_notte"])
    condo = float(g["spese_condominiali_eur_anno"])
    insurance = float(g["assicurazione_eur_anno"])
    maintenance = gross_revenue * float(g["manutenzione_pct_ricavi"])
    pm = gross_revenue * float(g["property_management_pct"])
    tari = float(g["tari_eur_anno"])

    imu = 0.0
    imu_cfg = t["imu"]
    if rendita_catastale:
        imu_base = (rendita_catastale
                    * float(imu_cfg["rivalutazione_rendita"])
                    * float(imu_cfg["moltiplicatore"]))
        imu = imu_base * float(imu_cfg["aliquota_per_mille"]) / 1000.0
    elif property_value:
        # Approssimazione grossolana quando la rendita non e' nota: la rendita
        # tipica si colloca intorno allo 0.4-0.6% del valore di mercato. È una
        # stima da sostituire con il dato catastale reale appena disponibile.
        imu_base = property_value * 0.005 * float(imu_cfg["rivalutazione_rendita"]) * \
            float(imu_cfg["moltiplicatore"])
        imu = imu_base * float(imu_cfg["aliquota_per_mille"]) / 1000.0

    total_opex = ota + cleaning + utilities + condo + insurance + maintenance + pm + imu + tari
    noi = gross_revenue - total_opex

    # ── imposte sul reddito: i due regimi a confronto ────────────────────────
    # Cedolare: aliquota piatta sul LORDO, nessun costo deducibile.
    cedolare_rate = float(t["cedolare"]["aliquota_pct"])
    tax_cedolare = gross_revenue * cedolare_rate

    # Ordinario: IRPEF marginale sul reddito netto dei costi (IMU esclusa dalla
    # deducibilita' sugli immobili non strumentali: la riaggiungiamo alla base).
    ord_cfg = t["ordinario"]
    taxable_ordinary = max(noi + imu, 0.0) * (1 - float(ord_cfg["abbattimento_forfettario_pct"]))
    tax_ordinary = taxable_ordinary * float(ord_cfg["aliquota_irpef_marginale_pct"])

    if t["regime"] == "cedolare":
        income_tax, regime_used, alternative = tax_cedolare, "cedolare", tax_ordinary
    elif t["regime"] == "ordinario":
        income_tax, regime_used, alternative = tax_ordinary, "ordinario", tax_cedolare
    else:  # "migliore": sceglie il regime meno oneroso
        if tax_cedolare <= tax_ordinary:
            income_tax, regime_used, alternative = tax_cedolare, "cedolare", tax_ordinary
        else:
            income_tax, regime_used, alternative = tax_ordinary, "ordinario", tax_cedolare

    net_pre_debt = noi - income_tax
    net_cashflow = net_pre_debt - debt_service

    return OperatingBreakdown(
        gross_revenue=round(gross_revenue, 2),
        ota_commission=round(ota, 2),
        cleaning=round(cleaning, 2),
        utilities=round(utilities, 2),
        condo_fees=round(condo, 2),
        insurance=round(insurance, 2),
        maintenance=round(maintenance, 2),
        property_management=round(pm, 2),
        imu=round(imu, 2),
        tari=round(tari, 2),
        total_opex=round(total_opex, 2),
        noi=round(noi, 2),
        income_tax=round(income_tax, 2),
        tax_regime_used=regime_used,
        tax_regime_alternative_cost=round(alternative, 2),
        net_cashflow_pre_debt=round(net_pre_debt, 2),
        debt_service=round(debt_service, 2),
        net_cashflow=round(net_cashflow, 2),
    )


# ═════════════════════════════════════════════════════════════════════════════
# Mutuo
# ═════════════════════════════════════════════════════════════════════════════

def mortgage(purchase_price: float, cfg: Optional[dict] = None) -> dict[str, float]:
    """Rata annua a tasso fisso (ammortamento francese)."""
    m = (cfg or config.fiscale())["mutuo"]
    if not m.get("attivo"):
        return {"principal": 0.0, "annual_payment": 0.0, "equity": purchase_price, "rate": 0.0}

    principal = purchase_price * float(m["ltv"])
    rate = float(m["tasso_annuo_pct"]) / 12.0
    n = int(m["durata_anni"]) * 12

    if rate <= 0:
        monthly = principal / n
    else:
        monthly = principal * rate / (1 - (1 + rate) ** -n)

    return {
        "principal": round(principal, 2),
        "annual_payment": round(monthly * 12, 2),
        "equity": round(purchase_price - principal, 2),
        "rate": float(m["tasso_annuo_pct"]),
        "years": int(m["durata_anni"]),
    }


# ═════════════════════════════════════════════════════════════════════════════
# NPV / IRR / break-even
# ═════════════════════════════════════════════════════════════════════════════

def npv_irr(
    initial_outflow: float,
    annual_cashflow: float,
    property_value: float,
    cfg: Optional[dict] = None,
) -> dict[str, Optional[float]]:
    """VAN e TIR su orizzonte finito, con valore di uscita."""
    v = (cfg or config.fiscale())["valutazione"]
    years = int(v["orizzonte_anni"])
    discount = float(v["tasso_sconto_pct"])
    rev_growth = float(v["crescita_ricavi_annua_pct"])
    appreciation = float(v["rivalutazione_immobile_annua_pct"])
    exit_cost = float(v["costo_uscita_pct"])

    flows = [-initial_outflow]
    for year in range(1, years + 1):
        cf = annual_cashflow * (1 + rev_growth) ** (year - 1)
        if year == years:
            cf += property_value * (1 + appreciation) ** years * (1 - exit_cost)
        flows.append(cf)

    npv = sum(cf / (1 + discount) ** i for i, cf in enumerate(flows))
    return {"npv": round(npv, 2), "irr": _irr(flows), "horizon_years": years}


def _irr(flows: list[float], lo: float = -0.95, hi: float = 3.0,
         tol: float = 1e-7, max_iter: int = 200) -> Optional[float]:
    """TIR per bisezione: nessuna dipendenza esterna, e non diverge come Newton
    sui profili di cassa irregolari tipici del real estate."""
    def f(rate: float) -> float:
        return sum(cf / (1 + rate) ** i for i, cf in enumerate(flows))

    f_lo, f_hi = f(lo), f(hi)
    if f_lo * f_hi > 0:
        return None    # nessun cambio di segno: TIR non definito su questo range
    for _ in range(max_iter):
        mid = (lo + hi) / 2
        f_mid = f(mid)
        if abs(f_mid) < tol:
            return round(mid, 6)
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return round((lo + hi) / 2, 6)


def break_even_occupancy(
    adr: float,
    nights_available: int,
    fixed_costs: float,
    variable_rate: float,
    *,
    cost_per_night: float = 0.0,
    cfg: Optional[dict] = None,
) -> Optional[float]:
    """Occupazione minima per andare a pareggio di cassa.

    È la metrica singola piu' leggibile del modello: dice a un proprietario
    quante notti deve vendere per non perdere soldi, ed e' immediatamente
    confrontabile con l'occupazione media del suo segmento. Un break-even al
    62% in un mercato che gira al 45% e' gia' una risposta.

    Attenzione a cosa NON dice: e' il pareggio di *cassa*, non il rendimento
    sul capitale. Un immobile puo' avere break-even al 25% e rendere lo 0.8%,
    perche' copre le spese correnti senza remunerare i 330.000 € investiti. Le
    due metriche vanno lette insieme.

    Tre categorie di costo, trattate diversamente:
      - `fixed_costs`   annui e indipendenti dall'occupazione (IMU, condominio,
                        assicurazione, TARI, utenze fisse, rata del mutuo);
      - `variable_rate` quota dei ricavi (commissioni OTA, property management,
                        manutenzione, imposta sul reddito sotto cedolare);
      - `cost_per_night` costi per notte venduta (pulizie ripartite sulla durata
                        media del soggiorno, utenze variabili). Ometterli
                        sottostima il break-even di parecchi punti: su un ADR di
                        160 € una pulizia da 55 € ogni 4 notti pesa l'8-9%.
    """
    if adr <= 0 or nights_available <= 0 or variable_rate >= 1:
        return None
    contribution_per_night = adr * (1 - variable_rate) - cost_per_night
    if contribution_per_night <= 0:
        return None    # nessuna occupazione porta al pareggio: il modello e' in perdita strutturale
    nights_needed = fixed_costs / contribution_per_night
    return round(min(nights_needed / nights_available, 2.0), 4)


# ═════════════════════════════════════════════════════════════════════════════
# Underwriting completo
# ═════════════════════════════════════════════════════════════════════════════

def underwrite(
    *,
    scenario: str,
    property_ref: str,
    purchase_price: float,
    annual_gross_revenue: float,
    nights_sold: float,
    adr: float,
    surface_sqm: Optional[float] = None,
    rendita_catastale: Optional[float] = None,
    renovation_eur: Optional[float] = None,
    furnishing_eur: Optional[float] = None,
    cfg: Optional[dict] = None,
) -> UnderwritingResult:
    """Valutazione completa di un'operazione di acquisto a reddito."""
    conf = cfg or config.fiscale()

    acq = acquisition_costs(
        purchase_price,
        surface_sqm=surface_sqm,
        rendita_catastale=rendita_catastale,
        renovation_eur=renovation_eur,
        furnishing_eur=furnishing_eur,
        cfg=conf,
    )
    loan = mortgage(purchase_price, conf)
    ops = operating_model(
        annual_gross_revenue,
        nights_sold,
        rendita_catastale=rendita_catastale,
        property_value=purchase_price,
        debt_service=loan["annual_payment"],
        cfg=conf,
    )

    gross_yield = annual_gross_revenue / acq.total if acq.total else 0.0
    net_yield = ops.net_cashflow_pre_debt / acq.total if acq.total else 0.0
    cap_rate = ops.noi / purchase_price if purchase_price else 0.0

    equity = acq.total - loan["principal"]
    cash_on_cash = ops.net_cashflow / equity if equity > 0 else None
    dscr = (ops.net_cashflow_pre_debt / loan["annual_payment"]
            if loan["annual_payment"] > 0 else None)
    payback = acq.total / ops.net_cashflow_pre_debt if ops.net_cashflow_pre_debt > 0 else None

    g, t = conf["gestione"], conf["imposte"]
    variable_rate = (float(g["commissione_ota_pct"])
                     + float(g["property_management_pct"])
                     + float(g["manutenzione_pct_ricavi"])
                     + (float(t["cedolare"]["aliquota_pct"])
                        if ops.tax_regime_used == "cedolare" else 0.0))
    # Pulizie e utenze variabili scalano con le notti vendute, non con i ricavi:
    # vanno nel costo per notte, non nell'aliquota variabile.
    cost_per_night = (float(g["pulizia_eur_per_soggiorno"])
                      / max(float(g["soggiorno_medio_notti"]), 1.0)
                      + float(g["utenze_variabili_eur_notte"]))
    fixed_costs = (float(g["utenze_fisse_eur_anno"]) + ops.condo_fees + ops.insurance
                   + ops.imu + ops.tari + loan["annual_payment"])
    beo = break_even_occupancy(adr, 365, fixed_costs, min(variable_rate, 0.95),
                               cost_per_night=cost_per_night, cfg=conf)

    valuation = npv_irr(equity if loan["principal"] else acq.total,
                        ops.net_cashflow, purchase_price, conf)

    verdict, reasons = _verdict(
        net_yield=net_yield, dscr=dscr, beo=beo,
        npv=valuation["npv"], cfg=conf,
    )

    return UnderwritingResult(
        scenario=scenario,
        property_ref=property_ref,
        acquisition=acq,
        operating=ops,
        gross_yield=round(gross_yield, 4),
        net_yield=round(net_yield, 4),
        cap_rate=round(cap_rate, 4),
        cash_on_cash=round(cash_on_cash, 4) if cash_on_cash is not None else None,
        dscr=round(dscr, 3) if dscr is not None else None,
        payback_years=round(payback, 1) if payback else None,
        break_even_occupancy=beo,
        npv=valuation["npv"],
        irr=valuation["irr"],
        verdict=verdict,
        verdict_reasons=reasons,
        sensitivity=sensitivity_grid(
            purchase_price=purchase_price,
            annual_gross_revenue=annual_gross_revenue,
            nights_sold=nights_sold,
            acquisition_total=acq.total,
            surface_sqm=surface_sqm,
            rendita_catastale=rendita_catastale,
            renovation_eur=renovation_eur,
            furnishing_eur=furnishing_eur,
            cfg=conf,
        ),
    )


def _verdict(*, net_yield: float, dscr: Optional[float], beo: Optional[float],
             npv: Optional[float], cfg: dict) -> tuple[Verdict, list[str]]:
    """Verdetto meccanico, basato su soglie esplicite e configurabili.

    Deliberatamente non e' l'LLM a decidere. Un giudizio d'investimento deve
    essere riproducibile e verificabile riga per riga: chi legge deve poter
    dire "non sono d'accordo con la soglia del 5.5%" e cambiarla, non
    "non sono d'accordo con quello che ha pensato il modello".
    """
    s = cfg["valutazione"]["soglie"]
    reasons: list[str] = []
    fails = 0
    warns = 0

    if net_yield >= float(s["net_yield_buono"]):
        reasons.append(f"rendimento netto {net_yield:.2%} sopra la soglia di buono "
                       f"({float(s['net_yield_buono']):.2%})")
    elif net_yield >= float(s["net_yield_accettabile"]):
        reasons.append(f"rendimento netto {net_yield:.2%}: accettabile ma non brillante")
        warns += 1
    else:
        reasons.append(f"rendimento netto {net_yield:.2%} sotto la soglia minima "
                       f"({float(s['net_yield_accettabile']):.2%})")
        fails += 1

    if dscr is not None:
        if dscr < float(s["dscr_minimo"]):
            reasons.append(f"DSCR {dscr:.2f} sotto il minimo {float(s['dscr_minimo']):.2f}: "
                           "il flusso di cassa non copre la rata con margine")
            fails += 1
        else:
            reasons.append(f"DSCR {dscr:.2f}: la rata e' coperta")

    if beo is not None:
        limit = float(s["break_even_occupancy_max"])
        if beo > limit:
            reasons.append(f"break-even al {beo:.0%} di occupazione, sopra il limite "
                           f"{limit:.0%}: margine di sicurezza troppo sottile")
            fails += 1
        else:
            reasons.append(f"break-even al {beo:.0%} di occupazione")

    if npv is not None:
        if npv > 0:
            reasons.append(f"VAN positivo ({npv:,.0f} €) al tasso di sconto configurato")
        else:
            reasons.append(f"VAN negativo ({npv:,.0f} €): il capitale rende meno "
                           "dell'alternativa al tasso di sconto scelto")
            warns += 1

    if fails == 0 and warns == 0:
        return Verdict.COMPRA, reasons
    if fails == 0:
        return Verdict.VALUTA, reasons
    if fails >= 2:
        return Verdict.EVITA, reasons
    return Verdict.VALUTA, reasons


def sensitivity_grid(
    *,
    purchase_price: float,
    annual_gross_revenue: float,
    nights_sold: float,
    acquisition_total: float,
    surface_sqm: Optional[float] = None,
    rendita_catastale: Optional[float] = None,
    renovation_eur: Optional[float] = None,
    furnishing_eur: Optional[float] = None,
    cfg: Optional[dict] = None,
) -> dict[str, dict[str, float]]:
    """Come cambia il rendimento netto se le ipotesi sbagliano.

    Il numero puntuale e' la parte meno interessante di una valutazione
    immobiliare, perche' e' quello che sicuramente non si avverera'. Qui
    interessa se il caso pessimistico resta sopra lo zero: e' quello che
    distingue un investimento da una scommessa.

    Tutti i parametri dell'immobile vanno propagati anche qui, non solo al
    calcolo principale. Ometterli faceva ricadere la griglia sulle stime di
    ripiego (IMU dal valore invece che dalla rendita, imposte d'atto sul prezzo
    invece che sulla base catastale), e la cella "base" non coincideva con il
    rendimento riportato sopra: due numeri diversi per la stessa ipotesi, nella
    stessa schermata.
    """
    conf = cfg or config.fiscale()
    common = dict(surface_sqm=surface_sqm, rendita_catastale=rendita_catastale,
                  renovation_eur=renovation_eur, furnishing_eur=furnishing_eur)
    grid: dict[str, dict[str, float]] = {}

    for label, factor in [("-30%", 0.70), ("-20%", 0.80), ("-10%", 0.90),
                          ("base", 1.00), ("+10%", 1.10)]:
        ops = operating_model(
            annual_gross_revenue * factor, nights_sold * factor,
            rendita_catastale=rendita_catastale, property_value=purchase_price, cfg=conf,
        )
        grid.setdefault("ricavi", {})[label] = round(
            ops.net_cashflow_pre_debt / acquisition_total, 4) if acquisition_total else 0.0

    for label, factor in [("-15%", 0.85), ("-10%", 0.90), ("base", 1.00),
                          ("+10%", 1.10), ("+20%", 1.20)]:
        price = purchase_price * factor
        acq = acquisition_costs(price, cfg=conf, **common)
        ops = operating_model(annual_gross_revenue, nights_sold,
                              rendita_catastale=rendita_catastale,
                              property_value=price, cfg=conf)
        grid.setdefault("prezzo_acquisto", {})[label] = round(
            ops.net_cashflow_pre_debt / acq.total, 4) if acq.total else 0.0

    return grid
