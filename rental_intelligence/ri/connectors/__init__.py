"""Connettori verso le sorgenti dati.

L'import dei moduli qui sotto e' quello che popola il registro (`base.register`),
quindi l'ordine conta solo per la leggibilita', non per il comportamento.
"""

from .base import (  # noqa: F401
    ComplianceError,
    Connector,
    MissingCredentials,
    available,
    build,
    register,
)
from . import csv_import, demo, official_apis  # noqa: F401,E402

__all__ = [
    "Connector",
    "ComplianceError",
    "MissingCredentials",
    "build",
    "available",
    "register",
]
