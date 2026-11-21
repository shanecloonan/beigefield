"""A protocol drawn across chains.

Each part is a chain, an address, and a role. Two parts on different
chains become one cross-chain edge. The graph stores no calldata and no
bridge message. Heat stays 0.
"""

from __future__ import annotations

from typing import Any

from eth_scanner.chains.registry import normalize_chain, normalize_solana_address

_DROPPED = ("message", "data", "calldata", "payload", "input")


def _address(chain: str, raw: object) -> str:
    text = str(raw or "").strip()
    if chain == "solana":
        return normalize_solana_address(text)
    if text.lower().startswith("0x") and len(text) == 42 and all(
        ch in "0123456789abcdef" for ch in text[2:].lower()
    ):
        return text.lower()
    raise ValueError("invalid address")


def system_graph(parts: list[dict[str, Any]]) -> dict[str, Any]:
    nodes: dict[tuple[str, str], dict[str, Any]] = {}
    dropped = 0
    for part in parts or []:
        if not isinstance(part, dict):
            dropped += 1
            continue
        chain = normalize_chain(part.get("chain"))
        try:
            address = _address(chain, part.get("address"))
        except ValueError:
            dropped += 1
            continue
        role = str(part.get("role") or "unknown").strip().lower() or "unknown"
        node = nodes.setdefault(
            (chain, address),
            {"chain": chain, "address": address, "roles": []},
        )
        if role not in node["roles"]:
            node["roles"].append(role)
    ordered = [nodes[key] for key in sorted(nodes)]
    edges: list[dict[str, str]] = []
    for left in ordered:
        for right in ordered:
            if (left["chain"], left["address"]) >= (right["chain"], right["address"]):
                continue
            relation = "cross-chain" if left["chain"] != right["chain"] else "same-chain"
            edges.append({
                "src": "%s:%s" % (left["chain"], left["address"]),
                "dst": "%s:%s" % (right["chain"], right["address"]),
                "relation": relation,
            })
    if not ordered:
        return {
            "status": "skipped",
            "reason": "no protocol parts",
            "nodes": [],
            "edges": [],
            "dropped": dropped,
            "heat_contribution": 0,
        }
    return {
        "status": "ok",
        "reason": "",
        "nodes": ordered,
        "edges": edges,
        "cross_chain": sum(1 for edge in edges if edge["relation"] == "cross-chain"),
        "dropped": dropped,
        "heat_contribution": 0,
        "note": "Roles across chains. No message, no calldata, and no heat.",
    }
