"""Punto d'ingresso a riga di comando.

Comandi della Fase 1 disponibili finora:
  fetch-filings      Passo 2: elenco relazioni per Paese da filings.xbrl.org
  sample-candidates  Passo 3: emittenti con relazioni FY2024 e FY2025 utilizzabili
  propose-sample     Passo 3: proposta di campione da config/sample_proposal.yaml
  pipeline           esecuzione offline dei passi disponibili sui file già scaricati
"""

from __future__ import annotations

import argparse
import sys

from extraction.settings import load_settings


def _cmd_fetch_filings(args: argparse.Namespace) -> int:
    from pathlib import Path

    from extraction.sources.filings_api import fetch_filings, load_pages, write_filings_csv
    from extraction.sources.http import PoliteSession

    s = load_settings()
    out = s.interim_dir / f"filings_{args.country.lower()}.csv"
    if args.from_raw:
        # Rielaborazione offline delle risposte già salvate: nessuna richiesta di rete.
        pages, retrieved_at = load_pages(Path(args.from_raw))
        df = write_filings_csv(pages, retrieved_at, out)
        print(f"{len(df)} relazioni scritte in {out} (da {args.from_raw}, 0 richieste)")
        return 0
    session = PoliteSession(s.user_agent, s.min_delay_s, s.timeout_s)
    df = fetch_filings(session, args.country, out, raw_dir=s.raw_dir / "api", page_size=args.page_size)
    print(f"{len(df)} relazioni scritte in {out} ({session.request_count} richieste)")
    return 0


def _cmd_sample_candidates(args: argparse.Namespace) -> int:
    from extraction.sample import build_candidates

    s = load_settings()
    src = s.interim_dir / "filings_it.csv"
    out = s.interim_dir / "sample_candidates.csv"
    df = build_candidates(src, out, fiscal_years=tuple(args.years))
    print(f"{len(df)} righe emittente×esercizio scritte in {out}")
    return 0


def _cmd_propose_sample(args: argparse.Namespace) -> int:
    from extraction.sample import build_proposal

    s = load_settings()
    out = s.interim_dir / "sample_proposal.csv"
    df = build_proposal(
        s.config_dir / "sample_proposal.yaml",
        s.interim_dir / "sample_candidates.csv",
        out,
    )
    print(f"proposta di {df['lei'].nunique()} emittenti scritta in {out}")
    return 0


def _cmd_pipeline(args: argparse.Namespace) -> int:
    """Nessuna richiesta di rete: rielabora le risposte API già salvate in data/raw/api."""
    s = load_settings()
    raw_dirs = sorted((s.raw_dir / "api").glob(f"filings_{args.country.lower()}_*"))
    if not raw_dirs:
        print(
            f"nessuna risposta API salvata in {s.raw_dir / 'api'}: eseguire prima "
            f"`fetch-filings --country {args.country}`",
            file=sys.stderr,
        )
        return 2
    steps = [
        ["fetch-filings", "--country", args.country, "--from-raw", str(raw_dirs[-1])],
        ["sample-candidates"],
        ["propose-sample"],
    ]
    for step in steps:
        print(f"== {' '.join(step[:1])}")
        rc = main(step)
        if rc:
            return rc
    print("Passi 4-9 non ancora implementati: in attesa dell'approvazione del campione.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="esef-extraction")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("fetch-filings", help="scarica l'elenco delle relazioni (API filings.xbrl.org)")
    p.add_argument("--country", default="IT")
    p.add_argument("--page-size", type=int, default=200)
    p.add_argument("--from-raw", help="cartella di pagine API già salvate (data/raw/api/...)")
    p.set_defaults(func=_cmd_fetch_filings)

    p = sub.add_parser("sample-candidates", help="emittenti con relazioni per gli esercizi richiesti")
    p.add_argument("--years", type=int, nargs="+", default=[2024, 2025])
    p.set_defaults(func=_cmd_sample_candidates)

    p = sub.add_parser("propose-sample", help="genera data/interim/sample_proposal.csv")
    p.set_defaults(func=_cmd_propose_sample)

    p = sub.add_parser("pipeline", help="esegue offline i passi disponibili")
    p.add_argument("--country", default="IT")
    p.set_defaults(func=_cmd_pipeline)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
