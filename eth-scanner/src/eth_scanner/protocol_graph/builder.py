"""Build a defensive protocol graph from source + on-chain reads.

Nodes: target, implementation, admin/owner, tokens held, oracle-like
callees. Never sends transactions.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from eth_scanner.invariants.live import enrich_owner_kind, run_live_invariants


_ORACLE_HINT = re.compile(
    r"\b(oracle|aggregator|chainlink|latestAnswer|latestRoundData|twap|priceFeed|feed)\b",
    re.I,
)
_CALL_ADDR = re.compile(r"\b(?:I[A-Z][\w]*|address)\s*\(\s*(0x[a-fA-F0-9]{40})\s*\)")
_EXT_CALL = re.compile(r"\.(?:call|delegatecall|staticcall)\s*\{|\.call\(")
_IMPORT_OR_INTERFACE = re.compile(r"(?:import|interface)\s+[^\n;]+", re.I)


@dataclass
class GraphNode:
    id: str
    kind: str  # target|implementation|admin|token|oracle|external|unknown
    address: Optional[str] = None
    label: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GraphEdge:
    src: str
    dst: str
    relation: str  # proxies|implements|admin-of|holds|reads-price|calls
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProtocolGraph:
    address: str
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "notes": list(self.notes),
        }


def build_protocol_graph(
    address: str,
    *,
    source: str = "",
    is_proxy: bool = False,
    implementation: Optional[str] = None,
    contract_name: Optional[str] = None,
    funds_breakdown: Optional[list[dict[str, Any]]] = None,
    rpc_url: str = "",
    contract_class: str = "unknown",
) -> ProtocolGraph:
    addr = (address or "").strip().lower()
    g = ProtocolGraph(address=addr)
    g.nodes.append(GraphNode(
        id="target",
        kind="target",
        address=addr,
        label=contract_name or addr,
        meta={"is_proxy": bool(is_proxy), "contract_class": contract_class},
    ))

    impl = (implementation or "").strip().lower() or None
    if is_proxy and impl:
        g.nodes.append(GraphNode(id="implementation", kind="implementation", address=impl, label="implementation"))
        g.edges.append(GraphEdge("target", "implementation", "proxies"))
        g.notes.append("proxy → implementation %s" % impl)

    # Admin / owner from live eth_call suite.
    try:
        live = run_live_invariants(addr, contract_class=contract_class or "custody", rpc_url=rpc_url, timeout_s=8.0)
        for row in live:
            if row.id == "roles-owner":
                owner = (row.extras or {}).get("owner")
                kind = (row.extras or {}).get("kind") or "unknown"
                if owner:
                    if kind in {"eoa-or-contract", "unknown"} and rpc_url:
                        kind = enrich_owner_kind(rpc_url, str(owner))
                    nid = "admin"
                    g.nodes.append(GraphNode(
                        id=nid,
                        kind="admin",
                        address=str(owner).lower(),
                        label="owner/admin",
                        meta={"kind": kind},
                    ))
                    g.edges.append(GraphEdge("admin", "target", "admin-of", {"kind": kind}))
                    g.notes.append("admin=%s kind=%s" % (owner, kind))
    except Exception as exc:  # noqa: BLE001
        g.notes.append("admin probe skipped: %s" % str(exc)[:120])

    # Tokens held from funds breakdown.
    for i, row in enumerate(funds_breakdown or []):
        if not isinstance(row, dict):
            continue
        token = (row.get("token") or row.get("address") or row.get("asset") or "").strip().lower()
        if not token.startswith("0x") or len(token) != 42:
            continue
        nid = "token-%d" % i
        g.nodes.append(GraphNode(
            id=nid,
            kind="token",
            address=token,
            label=str(row.get("symbol") or token),
            meta={"usd": row.get("usd"), "raw": row.get("raw")},
        ))
        g.edges.append(GraphEdge("target", nid, "holds"))

    # Oracle / external call hints from source text (static).
    src = source or ""
    if _ORACLE_HINT.search(src):
        g.nodes.append(GraphNode(id="oracle-hint", kind="oracle", label="oracle-like API in source"))
        g.edges.append(GraphEdge("target", "oracle-hint", "reads-price"))
        g.notes.append("source mentions oracle/price-feed APIs")
    for m in _CALL_ADDR.finditer(src[:200_000]):
        other = m.group(1).lower()
        if other == addr:
            continue
        nid = "ext-%s" % other[-6:]
        if any(n.id == nid for n in g.nodes):
            continue
        kind = "oracle" if _ORACLE_HINT.search(m.group(0)) else "external"
        g.nodes.append(GraphNode(id=nid, kind=kind, address=other, label=other))
        g.edges.append(GraphEdge("target", nid, "calls" if kind == "external" else "reads-price"))
    if _EXT_CALL.search(src):
        g.notes.append("source contains low-level call/delegatecall sites")

    imports = _IMPORT_OR_INTERFACE.findall(src[:50_000])
    if imports:
        g.notes.append("imports/interfaces=%d" % len(imports))

    return g
