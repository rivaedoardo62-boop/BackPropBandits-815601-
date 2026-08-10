"""Importatore CSV/XLSX: il canale con cui entrano i dati reali.

È il connettore piu' importante del sistema in produzione, perche' e' quello
attraverso cui passano:
  - i dataset acquistati in licenza da provider STR;
  - gli export dell'extranet dei TUOI annunci (dati di cui sei titolare);
  - i dataset open (OMI, ISTAT, registri CIN);
  - qualunque raccolta fatta con un accordo scritto con il titolare.

Non e' glamour, ma sposta il rischio legale fuori dal codice: il codice legge
un file, chi ha prodotto quel file risponde della sua provenienza.
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

from .. import config
from ..models import ListingIntent, Perimeter, PriceObservation, RawListing
from .base import Connector, register

# Mappatura colonna-file -> campo interno. Volutamente permissiva sui nomi:
# ogni provider chiama le cose a modo suo e riscrivere il parser a ogni
# fornitore nuovo e' esattamente il lavoro che questo dizionario evita.
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "source_listing_id": ("listing_id", "id", "property_id", "unit_id", "codice"),
    "title": ("title", "name", "titolo", "descrizione_breve"),
    "comune": ("comune", "city", "citta", "municipality", "localita"),
    "lat": ("lat", "latitude", "latitudine"),
    "lon": ("lon", "lng", "longitude", "longitudine"),
    "property_type": ("property_type", "room_type", "tipologia", "tipo"),
    "max_guests": ("max_guests", "accommodates", "guests", "posti_letto", "ospiti"),
    "bedrooms": ("bedrooms", "camere", "n_camere"),
    "bathrooms": ("bathrooms", "bagni", "n_bagni"),
    "surface_sqm": ("surface_sqm", "mq", "superficie", "size_sqm"),
    "base_price_eur": ("price", "adr", "prezzo", "base_price", "nightly_rate"),
    "cleaning_fee_eur": ("cleaning_fee", "pulizia", "costo_pulizia"),
    "min_nights": ("minimum_nights", "min_nights", "notti_minime"),
    "rating": ("rating", "review_scores_rating", "punteggio"),
    "reviews_count": ("number_of_reviews", "reviews", "n_recensioni"),
    "licence_code": ("licence", "license", "cin", "cir", "codice_identificativo"),
    "host_id": ("host_id", "id_host", "gestore_id"),
    "asking_price_eur": ("asking_price", "prezzo_richiesta", "prezzo_vendita", "price_eur"),
    "amenities": ("amenities", "servizi", "dotazioni"),
    "url": ("url", "listing_url", "link"),
}


def _build_reverse_map(fieldnames: list[str]) -> dict[str, str]:
    """colonna-del-file -> campo-interno, confronto case/space-insensitive."""
    normalized = {f.strip().lower().replace(" ", "_"): f for f in fieldnames}
    mapping: dict[str, str] = {}
    for internal, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                mapping[internal] = normalized[alias]
                break
    return mapping


def _to_float(value) -> float | None:
    if value in (None, "", "NA", "N/A", "-"):
        return None
    text = str(value).strip().replace("€", "").replace("$", "").replace(" ", "")
    # "1.234,56" (it) vs "1,234.56" (en)
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".") if text.rindex(",") > text.rindex(".") \
            else text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _to_int(value) -> int | None:
    f = _to_float(value)
    return int(f) if f is not None else None


@register
class CsvImportConnector(Connector):
    """Legge tutti i CSV in `data/import/` (o in una cartella indicata).

    Convenzione sul nome del file, che determina l'intent:
        *_short_let*.csv  -> annunci di affitto breve
        *_sale*.csv       -> annunci di vendita
        *_calendar*.csv   -> calendario prezzi/disponibilita'
    Un file che non corrisponde a nessuno dei tre viene ignorato con un avviso,
    invece di essere indovinato.
    """

    name = "csv_import"
    intent_supported = ("short_let", "sale", "long_let")

    def __init__(self, directory: str | Path | None = None) -> None:
        super().__init__()
        self.directory = Path(directory) if directory else config.import_dir()
        self.skipped: list[str] = []

    # ── annunci ──────────────────────────────────────────────────────────────

    def fetch_listings(self, perimeter: Perimeter) -> Iterable[RawListing]:
        out: list[RawListing] = []
        if not self.directory.exists():
            return out

        for path in sorted(self.directory.rglob("*.csv")):
            stem = path.stem.lower()
            if "calendar" in stem:
                continue
            if "sale" in stem or "vendita" in stem:
                intent = ListingIntent.SALE
            elif "short_let" in stem or "affitti" in stem or "str" in stem:
                intent = ListingIntent.SHORT_LET
            elif "long_let" in stem or "residenziale" in stem:
                intent = ListingIntent.LONG_LET
            else:
                self.skipped.append(
                    f"{path.name}: intent non deducibile dal nome file "
                    "(attesi: *_short_let*, *_sale*, *_long_let*, *_calendar*)"
                )
                continue
            out.extend(self._read_listing_file(path, intent))
        return out

    def _read_listing_file(self, path: Path, intent: ListingIntent) -> list[RawListing]:
        out: list[RawListing] = []
        source = f"csv:{path.stem}"
        now = datetime.now()

        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as fh:
            sample = fh.read(8192)
            fh.seek(0)
            delimiter = ";" if sample.count(";") > sample.count(",") else ","
            reader = csv.DictReader(fh, delimiter=delimiter)
            if not reader.fieldnames:
                self.skipped.append(f"{path.name}: file senza intestazione")
                return out

            colmap = _build_reverse_map(list(reader.fieldnames))
            if "source_listing_id" not in colmap:
                self.skipped.append(
                    f"{path.name}: manca una colonna identificativo "
                    f"(una fra {COLUMN_ALIASES['source_listing_id']})"
                )
                return out

            for row_no, row in enumerate(reader, start=2):
                sid = (row.get(colmap["source_listing_id"]) or "").strip()
                if not sid:
                    continue

                payload: dict = {"_row": row_no, "_file": path.name}
                for internal, column in colmap.items():
                    if internal == "source_listing_id":
                        continue
                    payload[internal] = row.get(column)

                for numeric in ("lat", "lon", "bathrooms", "surface_sqm",
                                "base_price_eur", "cleaning_fee_eur", "rating",
                                "asking_price_eur"):
                    if numeric in payload:
                        payload[numeric] = _to_float(payload[numeric])
                for integer in ("max_guests", "bedrooms", "min_nights", "reviews_count"):
                    if integer in payload:
                        payload[integer] = _to_int(payload[integer])
                if isinstance(payload.get("amenities"), str):
                    payload["amenities"] = [
                        a.strip().strip('"').lower()
                        for a in payload["amenities"].replace("{", "").replace("}", "").split(",")
                        if a.strip()
                    ]

                out.append(RawListing(
                    source=source,
                    source_listing_id=sid,
                    intent=intent,
                    fetched_at=now,
                    payload=payload,
                    url=payload.get("url"),
                ))
        return out

    # ── calendario ───────────────────────────────────────────────────────────

    def fetch_prices(self, perimeter: Perimeter, listings: list[RawListing],
                     start: date, end: date) -> Iterable[PriceObservation]:
        """Legge i file `*_calendar*.csv`.

        Formato atteso (nomi flessibili come sopra):
            listing_id, date, available, price[, minimum_nights]
        `available` accetta t/f, true/false, 1/0, si/no.
        """
        from ..models import Listing

        out: list[PriceObservation] = []
        if not self.directory.exists():
            return out

        # Le osservazioni sono legate all'id interno, che dipende dalla source:
        # ricostruiamo la corrispondenza dagli annunci gia' letti.
        by_sid: dict[str, str] = {
            raw.source_listing_id: Listing.make_id(raw.source, raw.source_listing_id)
            for raw in listings
        }
        truthy = {"t", "true", "1", "yes", "y", "si", "s", "disponibile"}

        for path in sorted(self.directory.rglob("*calendar*.csv")):
            observed_at = datetime.fromtimestamp(path.stat().st_mtime)
            with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as fh:
                sample = fh.read(8192)
                fh.seek(0)
                delimiter = ";" if sample.count(";") > sample.count(",") else ","
                for row in csv.DictReader(fh, delimiter=delimiter):
                    norm = {k.strip().lower(): v for k, v in row.items() if k}
                    sid = (norm.get("listing_id") or norm.get("id") or "").strip()
                    raw_date = (norm.get("date") or norm.get("data") or "").strip()
                    if not sid or not raw_date:
                        continue
                    listing_id = by_sid.get(sid)
                    if listing_id is None:
                        continue
                    try:
                        stay = date.fromisoformat(raw_date[:10])
                    except ValueError:
                        continue
                    if not (start <= stay <= end):
                        continue

                    available = str(norm.get("available", "")).strip().lower() in truthy
                    out.append(PriceObservation(
                        listing_id=listing_id,
                        stay_date=stay,
                        observed_at=observed_at,
                        available=available,
                        price_eur=_to_float(norm.get("price") or norm.get("prezzo")),
                        min_nights=_to_int(norm.get("minimum_nights") or norm.get("min_nights")),
                    ))
        return out
