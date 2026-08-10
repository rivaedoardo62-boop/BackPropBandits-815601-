"""Interfaccia a riga di comando.

    python -m rental_intelligence.ri.cli run --mercati cinque_terre,tigullio
    python -m rental_intelligence.ri.cli sources
    python -m rental_intelligence.ri.cli markets
    python -m rental_intelligence.ri.cli underwrite --prezzo 280000 --adr 140 --occ 0.48
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from . import config, connectors, geo
from .analytics import finance
from .analytics.revenue import annual_revenue
from .models import Perimeter
from .orchestrator import run_pipeline, summary


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)-28s %(message)s",
        datefmt="%H:%M:%S",
    )


# ── comandi ──────────────────────────────────────────────────────────────────

def cmd_run(args: argparse.Namespace) -> int:
    perimeter = Perimeter(
        macro_markets=[m.strip() for m in args.mercati.split(",")] if args.mercati else None,
        comuni=[c.strip() for c in args.comuni.split(",")] if args.comuni else None,
        min_guests=args.min_ospiti,
        max_guests=args.max_ospiti,
    )
    state = run_pipeline(perimeter, save_report=not args.no_save)
    print(summary(state))

    if args.json:
        print(json.dumps(state.report, ensure_ascii=False, indent=2, default=str))
    return 0 if not state.errors else 1


def cmd_sources(_: argparse.Namespace) -> int:
    from .connectors.official_apis import credentials_status

    registry = config.sources().get("sources") or {}
    creds = credentials_status()
    implemented = set(connectors.available())

    print(f"{'sorgente':24s} {'conformita':18s} {'attiva':8s} {'impl.':7s} {'cred.':7s}")
    print("─" * 72)
    for name, spec in registry.items():
        cred = creds.get(name)
        print(
            f"{name:24s} "
            f"{spec.get('compliance', '?'):18s} "
            f"{'si' if spec.get('enabled') else 'no':8s} "
            f"{'si' if name in implemented else 'no':7s} "
            f"{('si' if cred else 'no') if cred is not None else '—':7s}"
        )
    print()
    print(f"attive a runtime (RI_SOURCES): {', '.join(config.active_sources())}")
    return 0


def cmd_markets(_: argparse.Namespace) -> int:
    cfg = config.liguria()
    for name, market in (cfg.get("macro_markets") or {}).items():
        comuni = ", ".join(market.get("comuni", []))
        print(f"\n  {name}  [{market.get('provincia')}]  profilo {geo.market_profile(name)}")
        print(f"      {market.get('profilo', '').strip()}")
        print(f"      comuni: {comuni}")
    print(f"\n  totale: {len(cfg.get('macro_markets') or {})} mercati, "
          f"{len(geo.all_comuni())} comuni")
    return 0


def cmd_underwrite(args: argparse.Namespace) -> int:
    """Valutazione singola, senza pipeline: utile per un'ipotesi al volo."""
    revenue = annual_revenue(args.adr, args.occ, args.mercato)
    result = finance.underwrite(
        scenario="manuale",
        property_ref=args.etichetta,
        purchase_price=args.prezzo,
        annual_gross_revenue=revenue["annual_gross_revenue"],
        nights_sold=revenue["nights_sold"],
        adr=revenue["effective_adr"],
        surface_sqm=args.mq,
        rendita_catastale=args.rendita,
    )

    acq, ops = result.acquisition, result.operating
    print(f"\n  {result.property_ref}")
    print("  " + "─" * 62)
    print(f"  prezzo di acquisto        {acq.purchase_price:>12,.0f} €")
    print(f"  + agenzia                 {acq.agency_fee:>12,.0f} €")
    print(f"  + notaio                  {acq.notary_fee:>12,.0f} €")
    print(f"  + imposte d'atto          {acq.transfer_taxes:>12,.0f} €")
    print(f"  + ristrutturazione        {acq.renovation:>12,.0f} €")
    print(f"  + arredo e avvio          {acq.furnishing + acq.setup:>12,.0f} €")
    print(f"  = costo totale            {acq.total:>12,.0f} €")
    print()
    print(f"  ricavo lordo annuo        {ops.gross_revenue:>12,.0f} €  "
          f"({revenue['nights_sold']:.0f} notti @ {revenue['effective_adr']:.0f} €)")
    print(f"  - commissioni OTA         {ops.ota_commission:>12,.0f} €")
    print(f"  - pulizie                 {ops.cleaning:>12,.0f} €")
    print(f"  - property management     {ops.property_management:>12,.0f} €")
    print(f"  - utenze/condominio/altro "
          f"{ops.utilities + ops.condo_fees + ops.insurance + ops.tari:>12,.0f} €")
    print(f"  - manutenzione            {ops.maintenance:>12,.0f} €")
    print(f"  - IMU                     {ops.imu:>12,.0f} €")
    print(f"  = NOI                     {ops.noi:>12,.0f} €")
    print(f"  - imposte ({ops.tax_regime_used:9s})    {ops.income_tax:>12,.0f} €   "
          f"(alternativa: {ops.tax_regime_alternative_cost:,.0f} €)")
    print(f"  = flusso netto            {ops.net_cashflow:>12,.0f} €")
    print()
    print(f"  rendimento lordo          {result.gross_yield:>12.2%}")
    print(f"  rendimento netto          {result.net_yield:>12.2%}")
    print(f"  cap rate                  {result.cap_rate:>12.2%}")
    if result.break_even_occupancy is not None:
        print(f"  break-even occupazione    {result.break_even_occupancy:>12.1%}   "
              f"(mercato: {args.occ:.1%})")
    if result.payback_years:
        print(f"  rientro capitale          {result.payback_years:>12.1f} anni")
    if result.npv is not None:
        print(f"  VAN                       {result.npv:>12,.0f} €")
    if result.irr is not None:
        print(f"  TIR                       {result.irr:>12.2%}")
    print()
    print(f"  VERDETTO: {result.verdict.value.upper()}")
    for reason in result.verdict_reasons:
        print(f"      · {reason}")
    print()
    print("  sensibilita' del rendimento netto:")
    for variable, grid in result.sensitivity.items():
        cells = "  ".join(f"{k}:{v:>7.2%}" for k, v in grid.items())
        print(f"      {variable:18s} {cells}")
    print()
    print("  ⚠  aliquote e costi da config/fiscale.yaml, non verificati contro la")
    print("     normativa vigente. Fai validare le voci `verify: true` prima di decidere.")
    return 0


# ── parser ───────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rental-intelligence",
        description="Sistema multi-agente per il mercato degli affitti brevi in Liguria",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="esegue la pipeline completa")
    p_run.add_argument("--mercati", help="macro-mercati separati da virgola")
    p_run.add_argument("--comuni", help="comuni separati da virgola")
    p_run.add_argument("--min-ospiti", type=int)
    p_run.add_argument("--max-ospiti", type=int)
    p_run.add_argument("--json", action="store_true", help="stampa il report completo")
    p_run.add_argument("--no-save", action="store_true")
    p_run.set_defaults(func=cmd_run)

    p_sources = sub.add_parser("sources", help="stato delle sorgenti dati")
    p_sources.set_defaults(func=cmd_sources)

    p_markets = sub.add_parser("markets", help="macro-mercati configurati")
    p_markets.set_defaults(func=cmd_markets)

    p_uw = sub.add_parser("underwrite", help="valutazione singola di un acquisto")
    p_uw.add_argument("--prezzo", type=float, required=True, help="prezzo di acquisto in €")
    p_uw.add_argument("--adr", type=float, required=True, help="ADR medio annuo atteso in €")
    p_uw.add_argument("--occ", type=float, required=True, help="occupazione annua attesa (0-1)")
    p_uw.add_argument("--mq", type=float, help="superficie in mq")
    p_uw.add_argument("--rendita", type=float, help="rendita catastale in € (per IMU e imposte)")
    p_uw.add_argument("--mercato", default="tigullio", help="macro-mercato per la stagionalita'")
    p_uw.add_argument("--etichetta", default="ipotesi manuale")
    p_uw.set_defaults(func=cmd_underwrite)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
