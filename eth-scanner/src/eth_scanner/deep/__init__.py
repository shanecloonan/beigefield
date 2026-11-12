"""Phase A deep analysis — static/symbolic engines off the Vercel path.

Defensive only. Never sends transactions. Never emits exploit / PoC /
attack sequences. Single-engine generic detectors do not add heat;
cross-engine agreement raises confidence only.
"""

from eth_scanner.deep.findings import (
    EngineFinding,
    agreement_summary,
    dedupe_findings,
    heat_eligible_clusters,
)
from eth_scanner.deep.worker import run_deep_claim, run_deep_one

__all__ = [
    "EngineFinding",
    "agreement_summary",
    "dedupe_findings",
    "heat_eligible_clusters",
    "run_deep_claim",
    "run_deep_one",
]
