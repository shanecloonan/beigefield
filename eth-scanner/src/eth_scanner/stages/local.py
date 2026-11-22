"""Finish the source-only stages during a scan.

Similarity and cross-contract reads are local. Their facts add no heat.
A missing source marks the stage skipped. The evidence heat is unchanged.
"""

from __future__ import annotations

from typing import Any, Optional

from eth_scanner.advanced.reachability import reachability_report
from eth_scanner.similarity.index import search
from eth_scanner.stages.fusion import complete_stage


def finish_local_stages(breakdown: Optional[dict[str, Any]], source: str) -> dict[str, Any]:
    """Record similarity and cross-contract. Heat stays where the evidence left it."""
    before = int((breakdown or {}).get("fused_heat") or 0)
    text = source or ""
    if not text.strip():
        done = complete_stage(breakdown, "similarity", status="skipped")
        done = complete_stage(done, "cross-contract", status="skipped")
    else:
        neighbors = search(text)
        paths = reachability_report(text)
        similar = [
            {"fact": "similarity", "heat": 0, "direction": "support", "confidence": 0.3}
            for _row in (neighbors.get("candidates") or [])
        ]
        reached = [
            {"fact": str(row.get("kind") or "cross-contract"), "heat": 0, "direction": "support", "confidence": 0.4}
            for row in (paths.get("leads") or [])
        ]
        done = complete_stage(breakdown, "similarity", facts=similar, confidence=0.3)
        done = complete_stage(done, "cross-contract", facts=reached, confidence=0.4)
        done["similarity"] = {
            "candidates": list(neighbors.get("candidates") or []),
            "heat_contribution": 0,
        }
        done["cross_contract"] = {
            "leads": list(paths.get("leads") or []),
            "heat_contribution": 0,
        }
    if int(done.get("fused_heat") or 0) != before:
        done["fused_heat"] = before
    return done
