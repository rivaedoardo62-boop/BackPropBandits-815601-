"""Command line entry point: ``python -m extraction <command>``.

Commands available in this phase (Passi 1-3):

- ``filings-index``   download the list of filings of a country (online);
- ``verify-api``      re-run the API probe requests of docs/api_notes.md (online);
- ``sample-proposal`` build data/interim/sample_proposal.csv (offline);
- ``pipeline``        run the offline stages on data already downloaded.

The download, extraction, validation and report stages (Passi 4-9) are added
only after the sample has been approved.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from extraction.settings import Settings

log = logging.getLogger("extraction")


def _api(settings: Settings):
    from extraction.sources.filings_api import FilingsApi
    from extraction.sources.http import PoliteSession

    http = PoliteSession(
        settings.user_agent,
        min_delay_s=settings.request_delay_s,
        timeout_s=settings.timeout_s,
        max_retries=settings.max_retries,
    )
    return FilingsApi(http, settings.api_base_url)


def cmd_filings_index(args: argparse.Namespace, settings: Settings) -> int:
    from extraction.sources.filings_index import build_filings_index, write_filings_index

    country = args.country.upper()
    frame, metadata = build_filings_index(
        _api(settings), country=country, raw_dir=settings.raw_dir, page_size=args.page_size
    )
    csv_path = settings.interim_dir / f"filings_{country.lower()}.csv"
    meta_path = write_filings_index(frame, metadata, csv_path)
    log.info(
        "%d filings of %d entities -> %s (provenance: %s)",
        len(frame), metadata["entities"], csv_path, meta_path,
    )
    return 0


def cmd_verify_api(args: argparse.Namespace, settings: Settings) -> int:
    from extraction.sources.api_probe import run_probes

    report = run_probes(
        _api(settings),
        country=args.country.upper(),
        lei=args.lei,
        period_end=args.period_end,
        download=not args.skip_downloads,
    )
    settings.interim_dir.mkdir(parents=True, exist_ok=True)
    out = settings.interim_dir / "api_probe.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    for probe in report["probes"]:
        log.info("%-32s %s", probe["name"], probe.get("outcome"))
    log.info("probe report -> %s", out)
    return 0 if all(p.get("ok") for p in report["probes"]) else 1


def cmd_sample_proposal(args: argparse.Namespace, settings: Settings) -> int:
    from extraction.sample import build_sample_proposal, load_sample_config

    filings_csv = Path(args.filings) if args.filings else settings.interim_dir / "filings_it.csv"
    config_path = Path(args.config) if args.config else settings.config_dir / "sample.yaml"
    if not filings_csv.exists():
        log.error("%s not found: run 'filings-index --country IT' first", filings_csv)
        return 2
    proposal, problems = build_sample_proposal(filings_csv, load_sample_config(config_path))
    out = settings.interim_dir / "sample_proposal.csv"
    proposal.to_csv(out, index=False, encoding="utf-8")
    log.info("%d rows (%d issuers) -> %s", len(proposal), proposal["lei"].nunique(), out)
    for problem in problems:
        log.warning(problem)
    return 0 if not problems else 1


def cmd_pipeline(args: argparse.Namespace, settings: Settings) -> int:
    # Offline stages only: nothing is downloaded here.
    args.filings = None
    args.config = None
    return cmd_sample_proposal(args, settings)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="extraction", description=__doc__.split("\n\n")[0])
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("filings-index", help="download the filings list of a country")
    p.add_argument("--country", default="IT")
    p.add_argument("--page-size", type=int, default=200)
    p.set_defaults(func=cmd_filings_index)

    p = sub.add_parser("verify-api", help="re-run the API verification probes")
    p.add_argument("--country", default="IT")
    p.add_argument("--lei", required=True, help="LEI used for the LEI-filter probes")
    p.add_argument("--period-end", required=True, help="period end (YYYY-MM-DD) of the probe filing")
    p.add_argument(
        "--skip-downloads",
        action="store_true",
        help="do not download the probe package/xBRL-JSON (no hash check)",
    )
    p.set_defaults(func=cmd_verify_api)

    p = sub.add_parser("sample-proposal", help="build data/interim/sample_proposal.csv")
    p.add_argument("--filings", help="filings index CSV (default: data/interim/filings_it.csv)")
    p.add_argument("--config", help="sample config (default: config/sample.yaml)")
    p.set_defaults(func=cmd_sample_proposal)

    p = sub.add_parser("pipeline", help="run the offline stages on downloaded data")
    p.set_defaults(func=cmd_pipeline)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    return args.func(args, Settings.from_env())


if __name__ == "__main__":
    sys.exit(main())
