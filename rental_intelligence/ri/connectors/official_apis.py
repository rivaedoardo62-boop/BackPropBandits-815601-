"""Adattatori verso API ufficiali e provider in licenza.

Questi connettori sono deliberatamente incompleti: la firma, il gate di
conformita', il mapping dei campi e la gestione degli errori ci sono; le
chiamate HTTP no. La ragione e' che ognuna di queste API richiede un
accreditamento che va ottenuto prima, e ogni contratto arriva con la sua
documentazione, i suoi rate limit e i suoi vincoli di caching e ridistribuzione.

Scrivere ora una chiamata "plausibile" verso un endpoint che non ho letto
significherebbe consegnarti codice che sembra funzionante e non lo e'. Il punto
di rottura e' segnato con `NotImplementedError` e un messaggio che dice
esattamente cosa serve per completarlo.

Cosa e' gia' pronto e riutilizzabile senza toccare nulla:
  - il gate di conformita' (non parte senza credenziali);
  - la conversione verso `RawListing`, identica per tutte le sorgenti;
  - il punto in cui inserire retry/backoff e rispetto dei rate limit.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Iterable

from ..models import ListingIntent, Perimeter, RawListing
from .base import Connector, register


class _StubApiConnector(Connector):
    """Base comune degli adattatori verso API esterne."""

    doc_hint: str = ""

    def fetch_listings(self, perimeter: Perimeter) -> Iterable[RawListing]:
        raise NotImplementedError(
            f"[{self.name}] adattatore non completato.\n"
            f"Serve: {self.doc_hint}\n"
            "Una volta ottenuto l'accesso, implementa qui la sola chiamata HTTP e "
            "restituisci RawListing con payload = risposta grezza (nessuna "
            "normalizzazione: se ne occupa l'agente 2)."
        )

    @staticmethod
    def _wrap(source: str, sid: str, intent: ListingIntent, payload: dict,
              url: str | None = None) -> RawListing:
        return RawListing(
            source=source, source_listing_id=str(sid), intent=intent,
            fetched_at=datetime.now(), payload=payload, url=url,
        )


@register
class IdealistaConnector(_StubApiConnector):
    """API ufficiale Idealista — annunci di vendita e affitto in Italia.

    È la sorgente naturale per il lato "quanto costa comprare". La quota
    gratuita e' molto ridotta: progetta la raccolta come un job notturno che
    aggiorna un perimetro ristretto, non come una query interattiva.
    """

    name = "idealista_api"
    intent_supported = ("sale", "long_let")
    doc_hint = (
        "chiave e segreto Idealista (IDEALISTA_API_KEY / IDEALISTA_API_SECRET), "
        "flusso OAuth2 client_credentials, e la documentazione dell'endpoint di "
        "ricerca con i parametri di paginazione e i limiti di quota"
    )


@register
class BookingDemandConnector(_StubApiConnector):
    """Booking.com Demand API — disponibilita' e prezzi per partner approvati.

    L'unica via lecita per i dati Booking. L'approvazione della partnership e'
    il percorso critico del progetto: avviala prima di scrivere qualunque altra
    riga di codice, perche' i tempi non dipendono da te.
    """

    name = "booking_demand_api"
    intent_supported = ("short_let",)
    doc_hint = (
        "credenziali partner (BOOKING_DEMAND_API_KEY / BOOKING_AFFILIATE_ID) e la "
        "documentazione degli endpoint accommodations/availability, incluse le "
        "clausole contrattuali su caching e ridistribuzione dei prezzi"
    )


@register
class StrProviderConnector(_StubApiConnector):
    """Provider commerciale di dati short-term-rental.

    Questa e' la scorciatoia che consiglio per la v1: i provider di questo tipo
    vendono ADR, occupazione e RevPAR per mercato gia' deduplicati e gia'
    normalizzati. Comprarli salta l'intero problema di raccolta e la meta'
    difficile della deduplica, e ti lascia costruire il valore aggiunto vero,
    che sono gli agenti 3, 4 e 5.

    Attenzione ai contratti: quasi tutti vietano la ridistribuzione del dato
    granulare. Puoi usarli per generare le TUE analisi, non per rivendere il
    loro dataset.
    """

    name = "str_provider"
    intent_supported = ("short_let",)
    doc_hint = (
        "contratto con il provider, STR_PROVIDER_API_KEY e STR_PROVIDER_BASE_URL, "
        "e lo schema del suo endpoint di market data"
    )


@register
class OmiConnector(Connector):
    """Quotazioni Immobiliari OMI (Agenzia delle Entrate) da file locale.

    OMI non e' un'API: e' un dataset che si scarica. Lo trattiamo come sorgente
    a se' invece di infilarlo nel CSV generico perche' il suo schema (zona OMI,
    tipologia, stato conservativo, valore min/max al mq) e' stabile e vale la
    pena tipizzarlo.

    Serve a due cose: stimare il prezzo d'acquisto quando non hai un annuncio,
    e dire se un annuncio in vendita e' sopra o sotto i valori ufficiali di zona.
    """

    name = "omi"
    intent_supported = ("sale",)

    def fetch_listings(self, perimeter: Perimeter) -> Iterable[RawListing]:
        from .. import config

        path_dir = config.import_dir() / "omi"
        if not path_dir.exists() or not any(path_dir.glob("*.csv")):
            raise FileNotFoundError(
                f"nessun file OMI trovato in {path_dir}. Scarica le quotazioni dal "
                "portale dell'Agenzia delle Entrate, verifica le condizioni di riuso "
                "e appoggia i CSV in quella cartella."
            )
        raise NotImplementedError(
            "[omi] parser non completato: lo schema dei file OMI varia per semestre e "
            "per tracciato distribuito. Apri il file che hai scaricato, verifica i nomi "
            "esatti delle colonne (zona, tipologia, stato conservativo, compr_min, "
            "compr_max, loc_min, loc_max) e mappali qui. Non li indovino a priori."
        )


def credentials_status() -> dict[str, bool]:
    """Diagnostica: quali sorgenti accreditate hanno le credenziali a posto."""
    from .. import config

    status: dict[str, bool] = {}
    for name, spec in (config.sources().get("sources") or {}).items():
        keys = spec.get("env_keys") or []
        if keys:
            status[name] = all(bool(os.getenv(k)) for k in keys)
    return status
