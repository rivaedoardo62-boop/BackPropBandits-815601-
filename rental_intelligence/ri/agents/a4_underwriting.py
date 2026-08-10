"""Agente 4 — Valutazione dell'investimento.

Separato dall'agente 3 per una ragione precisa: "a che prezzo affittare" e
"conviene comprare" sono due domande diverse, con due destinatari diversi
(proprietario vs investitore) e due modelli diversi. Un immobile puo' avere un
ottimo pricing e restare un pessimo acquisto, se il prezzo di vendita e' fuori
mercato o le spese condominiali mangiano il margine.

Ogni numero prodotto qui e' deterministico: viene da `analytics/finance.py` e
si puo' rifare a mano su un foglio di calcolo. Il verdetto e' meccanico, deriva
da soglie scritte in `config/fiscale.yaml`. L'LLM dell'agente 5 lo spiega e
non lo tocca.
"""

from __future__ import annotations

import logging
from datetime import datetime

from ..analytics import finance
from ..analytics.revenue import annual_revenue
from ..models import PipelineState, Verdict

logger = logging.getLogger(__name__)

# Quante opportunita' valutare per esecuzione. Il calcolo e' istantaneo, ma un
# report con 300 valutazioni non e' un report: e' un foglio di calcolo travestito.
MAX_CANDIDATES = 15


def run(state: PipelineState, max_candidates: int = MAX_CANDIDATES) -> PipelineState:
    stats_by_key = {s.segment.key(): s for s in state.market_stats}
    results = []
    skipped: dict[str, int] = {}

    for deal in state.deal_candidates[:max_candidates]:
        if not deal.segment_key or deal.segment_key not in stats_by_key:
            skipped["segmento_assente"] = skipped.get("segmento_assente", 0) + 1
            continue

        stats = stats_by_key[deal.segment_key]
        if not stats.adr_p50 or not stats.occupancy_est:
            skipped["statistiche_incomplete"] = skipped.get("statistiche_incomplete", 0) + 1
            continue

        revenue = annual_revenue(stats.adr_p50, stats.occupancy_est, deal.macro_market)

        result = finance.underwrite(
            scenario="base",
            property_ref=f"{deal.comune} — {deal.asking_price_eur:,.0f} € "
                         f"({deal.surface_sqm or '?'} mq)",
            purchase_price=deal.asking_price_eur,
            annual_gross_revenue=revenue["annual_gross_revenue"],
            nights_sold=revenue["nights_sold"],
            adr=revenue["effective_adr"],
            surface_sqm=deal.surface_sqm,
        )

        # La confidenza del mercato limita la confidenza del verdetto: un
        # "compra" costruito su un segmento con occupazione da prior non e' un
        # "compra", e' un'ipotesi. Declassarlo qui evita che l'agente 5 debba
        # ricordarsene, e che l'utente legga un verdetto piu' forte del dato.
        if stats.confidence == "bassa" and result.verdict is Verdict.COMPRA:
            result.verdict = Verdict.VALUTA
            result.verdict_reasons.append(
                f"verdetto declassato da 'compra' a 'valuta': il segmento "
                f"{deal.segment_key} ha confidenza bassa "
                f"(campione {stats.sample_size}, occupazione da '{stats.occupancy_method}')"
            )

        results.append(result)

    state.underwriting = results
    state.underwriting_meta = {
        "n_evaluated": len(results),
        "n_candidates_available": len(state.deal_candidates),
        "skipped": skipped,
        "by_verdict": {
            v.value: sum(1 for r in results if r.verdict is v) for v in Verdict
        },
        "config_warning": (
            "aliquote e costi provengono da config/fiscale.yaml e NON sono verificati "
            "contro la normativa vigente: fai validare le voci marcate `verify: true` "
            "da un commercialista e le imposte d'atto da un notaio prima di decidere"
        ),
        "ran_at": datetime.now().isoformat(timespec="seconds"),
    }
    state.trace.append({
        "agent": "a4_underwriting",
        "n_evaluated": len(results),
        "by_verdict": state.underwriting_meta["by_verdict"],
    })

    logger.info("valutate %d opportunita': %s", len(results),
                state.underwriting_meta["by_verdict"])
    return state
