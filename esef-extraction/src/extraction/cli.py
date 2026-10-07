"""Command line entry point: ``esef <command>`` or ``python -m extraction <command>``."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from urllib.parse import urlparse

from extraction.settings import Settings, load_settings

log = logging.getLogger("extraction")


def _listing_path(settings: Settings, country: str) -> Path:
    return settings.interim_dir / f"filings_{country.lower()}.csv"


def cmd_list_filings(args: argparse.Namespace, settings: Settings) -> int:
    from extraction.sources.filings_api import FilingsApiClient
    from extraction.sources.http import PoliteSession
    from extraction.sources.listing import fetch_country_listing

    http = PoliteSession(
        user_agent=settings.user_agent,
        allowed_host=urlparse(settings.api_base).netloc,
        min_interval=settings.request_interval,
        timeout=settings.timeout,
    )
    client = FilingsApiClient(http, settings.api_base, page_size=args.page_size)
    df, path = fetch_country_listing(client, args.country, settings.interim_dir, settings.raw_dir)
    log.info("%d filings written to %s (%d HTTP requests)", len(df), path, http.request_count)
    return 0


def _propose_sample(settings: Settings, listing_path: Path | None = None, config_path: Path | None = None) -> int:
    from extraction.schema.sample import load_sample_config
    from extraction.sources.listing import read_listing
    from extraction.sources.sample import write_proposal

    listing_path = listing_path or _listing_path(settings, "IT")
    if not listing_path.exists():
        log.error("%s not found: run `esef list-filings --country IT` first", listing_path)
        return 2
    config = load_sample_config(config_path or settings.config_dir / "sample_candidates.yaml")
    out, summary = write_proposal(read_listing(listing_path), config, settings.interim_dir)
    log.info("sample proposal written to %s", out)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if summary["warnings"]:
        log.warning("proposal has %d warning(s), see above", len(summary["warnings"]))
    if not config.is_approved:
        log.warning("STOP: sample status is '%s'; steps 4-9 wait for approval", config.status)
    return 0


def cmd_propose_sample(args: argparse.Namespace, settings: Settings) -> int:
    return _propose_sample(settings, args.listing, args.config)


def cmd_run(args: argparse.Namespace, settings: Settings) -> int:
    """Offline pipeline on files already on disk (no network access)."""
    rc = _propose_sample(settings)
    if rc:
        return rc
    log.warning("steps 4-9 (download, extraction, validation, reports) are not implemented yet")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="esef", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list-filings", help="Passo 2: elenco completo delle relazioni di un Paese (rete)")
    p.add_argument("--country", default="IT")
    p.add_argument("--page-size", type=int, default=200)
    p.set_defaults(func=cmd_list_filings)

    p = sub.add_parser("propose-sample", help="Passo 3: proposta di campione (offline)")
    p.add_argument("--listing", type=Path, help="default: data/interim/filings_it.csv")
    p.add_argument("--config", type=Path, help="default: config/sample_candidates.yaml")
    p.set_defaults(func=cmd_propose_sample)

    p = sub.add_parser("run", help="pipeline offline sui file gia' scaricati")
    p.set_defaults(func=cmd_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    return args.func(args, load_settings())


if __name__ == "__main__":
    raise SystemExit(main())
