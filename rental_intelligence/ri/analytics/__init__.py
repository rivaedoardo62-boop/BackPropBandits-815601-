"""Moduli analitici deterministici.

Nessuna di queste funzioni chiama un LLM. È una separazione voluta: i numeri si
calcolano, si testano e si riproducono; il linguaggio naturale li spiega. Se
un giorno l'agente 5 sparisse, il sistema continuerebbe a produrre lo stesso
verdetto d'investimento.
"""

from . import dedup, finance, pricing, revenue  # noqa: F401

__all__ = ["dedup", "finance", "pricing", "revenue"]
