"""I cinque agenti piu' il supervisore.

Nessun agente importa un altro agente: comunicano solo attraverso
`PipelineState`. Il vincolo e' lo stesso adottato nel multiagent_pipeline gia'
presente nel repo, e serve a poter sostituire o testare un agente senza toccare
gli altri.
"""

from . import (  # noqa: F401
    a1_ingestion,
    a2_resolution,
    a3_market,
    a4_underwriting,
    a5_report,
    supervisor,
)

__all__ = [
    "a1_ingestion",
    "a2_resolution",
    "supervisor",
    "a3_market",
    "a4_underwriting",
    "a5_report",
]
