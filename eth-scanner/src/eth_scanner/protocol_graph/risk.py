"""Risk factors from a protocol graph. Scores are evidence inputs, not verdicts.

Heat still requires the Lane A evidence gate; these factors annotate likelihood.
"""

from __future__ import annotations

from typing import Any, Optional

from eth_scanner.protocol_graph.builder import ProtocolGraph

# Public post-mortem / incident fingerprints (addresses or name markers).
# Read-only knowledge — no PoC code. Expand in Phase D.
KNOWN_INCIDENT_MARKERS = frozenset({
    "euler",
    "beanstalk",
    "ronin",
    "wormhole",
    "nomad",
    "cream",
    "harvest",
    "bzx",
    "fei",
    "rari",
})


def score_graph_risks(
    graph: ProtocolGraph,
    *,
    funds_usd: Optional[float] = None,
    source: str = "",
) -> dict[str, Any]:
    funds = float(funds_usd) if funds_usd is not None else 0.0
    factors: list[dict[str, Any]] = []

    admin = next((n for n in graph.nodes if n.kind == "admin"), None)
    if admin:
        kind = (admin.meta or {}).get("kind") or "unknown"
        if kind == "eoa" and funds >= 100_000:
            factors.append({
                "id": "eoa-admin-large-funds",
                "likelihood": 0.7,
                "detail": "EOA admin/upgrader on contract with funds >= $100k",
                "funds_usd": funds,
            })
        elif kind == "eoa":
            factors.append({
                "id": "eoa-admin",
                "likelihood": 0.4,
                "detail": "EOA admin/upgrader",
                "funds_usd": funds,
            })
        elif kind == "zero":
            factors.append({
                "id": "renounced-or-zero-admin",
                "likelihood": 0.2,
                "detail": "admin/owner is zero address",
            })

    if any(n.kind == "implementation" for n in graph.nodes):
        # Proxy present — upgrade risk depends on admin kind (already captured).
        factors.append({
            "id": "upgradeable-proxy",
            "likelihood": 0.35,
            "detail": "proxy/implementation edge present",
        })

    if any(n.kind == "oracle" for n in graph.nodes) or any(
        e.relation == "reads-price" for e in graph.edges
    ):
        factors.append({
            "id": "oracle-dependency",
            "likelihood": 0.45,
            "detail": "oracle/price-feed dependency hinted in source or graph",
        })

    src_l = (source or "").lower()
    hits = sorted(m for m in KNOWN_INCIDENT_MARKERS if m in src_l)
    if hits:
        factors.append({
            "id": "known-incident-dependency-marker",
            "likelihood": 0.55,
            "detail": "source mentions historically incident-linked protocol markers: %s" % ",".join(hits),
            "markers": hits,
        })

    # Weighted score: funds * max likelihood (capped display helper, not heat).
    max_l = max((float(f["likelihood"]) for f in factors), default=0.0)
    weighted = funds * max_l
    return {
        "factors": factors,
        "max_likelihood": max_l,
        "funds_usd": funds,
        "funds_times_likelihood": weighted,
        "policy": (
            "Protocol-graph risks annotate likelihood only. "
            "They do not add heat alone; Lane A evidence gate still applies."
        ),
    }
