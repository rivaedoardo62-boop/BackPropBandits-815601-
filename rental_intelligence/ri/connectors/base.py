"""Contratto dei connettori e gate di conformita'.

Il gate e' il punto piu' importante del modulo. La raccolta dati e' l'unico
punto della pipeline dove un errore non produce un numero sbagliato ma un
problema legale, quindi il controllo sta nel codice: un connettore la cui
sorgente e' marcata `prohibited` o `requires_licence` senza credenziali non
parte, e non c'e' flag per aggirarlo.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from datetime import date
from typing import Iterable

from .. import config
from ..models import Compliance, Perimeter, PriceObservation, RawListing


class ComplianceError(RuntimeError):
    """Sollevata quando si tenta di usare una sorgente non consentita."""


class MissingCredentials(RuntimeError):
    """Sorgente lecita ma non configurata: manca la chiave o l'accreditamento."""


class Connector(ABC):
    """Interfaccia unica per ogni sorgente.

    Un connettore fa una cosa sola: restituire `RawListing` e, se la sorgente
    lo consente, `PriceObservation`. Nessuna normalizzazione, nessuna
    inferenza, nessuna pulizia. Tutto quel lavoro appartiene all'agente 2, ed
    e' li' che deve restare per poter essere testato su dati raw congelati.
    """

    name: str = "abstract"
    intent_supported: tuple[str, ...] = ()

    def __init__(self) -> None:
        self.spec = self._load_spec()
        self._check_compliance()

    # ── conformita' ──────────────────────────────────────────────────────────

    def _load_spec(self) -> dict:
        registry = config.sources().get("sources") or {}
        if self.name not in registry:
            raise ComplianceError(
                f"sorgente '{self.name}' non dichiarata in config/sources.yaml. "
                "Ogni sorgente deve essere registrata con il suo stato di conformita' "
                "prima di poter essere usata."
            )
        return registry[self.name]

    def _check_compliance(self) -> None:
        status = Compliance(self.spec.get("compliance", "prohibited"))

        if status is Compliance.PROHIBITED:
            alternatives = ", ".join(self.spec.get("alternative", [])) or "nessuna"
            raise ComplianceError(
                f"la sorgente '{self.name}' e' marcata come vietata dai termini di "
                f"servizio del titolare. Alternative previste: {alternatives}."
            )

        if status is Compliance.REQUIRES_LICENCE:
            missing = [k for k in self.spec.get("env_keys", []) if not os.getenv(k)]
            if missing:
                raise MissingCredentials(
                    f"la sorgente '{self.name}' richiede accreditamento. "
                    f"Variabili d'ambiente mancanti: {', '.join(missing)}."
                )

    @property
    def enabled(self) -> bool:
        return bool(self.spec.get("enabled", False))

    # ── raccolta ─────────────────────────────────────────────────────────────

    @abstractmethod
    def fetch_listings(self, perimeter: Perimeter) -> Iterable[RawListing]:
        """Annunci grezzi che ricadono nel perimetro."""

    def fetch_prices(
        self,
        perimeter: Perimeter,
        listings: list[RawListing],
        start: date,
        end: date,
    ) -> Iterable[PriceObservation]:
        """Calendario prezzi/disponibilita'.

        Default vuoto: molte sorgenti (OMI, ISTAT, export di annunci in vendita)
        non hanno un calendario, e va bene cosi'. Senza calendario l'agente 3
        stima l'occupazione dai prior invece che dai dati, e lo dichiara nel
        campo `occupancy_method`.
        """
        return []


# ── registro ─────────────────────────────────────────────────────────────────

_REGISTRY: dict[str, type[Connector]] = {}


def register(cls: type[Connector]) -> type[Connector]:
    _REGISTRY[cls.name] = cls
    return cls


def build(name: str) -> Connector:
    if name not in _REGISTRY:
        known = ", ".join(sorted(_REGISTRY)) or "nessuno"
        raise KeyError(f"connettore '{name}' non implementato. Disponibili: {known}.")
    return _REGISTRY[name]()


def available() -> list[str]:
    return sorted(_REGISTRY)
