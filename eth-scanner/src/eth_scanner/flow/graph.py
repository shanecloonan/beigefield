"""External calls, approvals, and value edges among a contract's dependencies.

Roles are guessed from interface names and a few view selectors. A path
score counts value-moving edges that also touch an oracle, AMM, lender,
or bridge. The score is a lead. It does not add heat, and no calldata is
stored.
"""

from __future__ import annotations

import re
from typing import Any, Optional

_CALL = re.compile(
    r"(?P<iface>[A-Za-z_][A-Za-z0-9_]*)\(\s*(?P<addr>0x[a-fA-F0-9]{40})\s*\)\s*\.\s*(?P<method>[A-Za-z_][A-Za-z0-9_]*)",
)
_APPROVE = re.compile(r"\.approve\s*\(\s*(?P<spender>0x[a-fA-F0-9]{40})")
_VALUE = re.compile(
    r"\.transferFrom\s*\(|safeTransferFrom\s*\(|safeTransfer\s*\(|"
    r"\.transfer\s*\(|\.call\s*\{\s*value|\.send\s*\(",
    re.I,
)


def _add_node(nodes: dict[str, dict[str, Any]], addr: str, role: str, label: str) -> None:
    current = nodes.get(addr)
    if current is None:
        nodes[addr] = {"id": addr, "role": role, "label": label[:80], "heat_contribution": 0}
        return
    if current.get("role") == "external" and role != "external":
        current["role"] = role


_ROLES = (
    ("oracle", re.compile(r"oracle|aggregator|chainlink|price|latestAnswer|latestRoundData|twap", re.I)),
    ("amm", re.compile(r"swap|pair|pool|router|getReserves|uniswap|curve", re.I)),
    ("lending", re.compile(r"borrow|lend|liquidate|aave|compound|morpho", re.I)),
    ("bridge", re.compile(r"bridge|mailbox|portal|gateway|lock|inbox", re.I)),
)


def role_of(label: str) -> str:
    text = label or ""
    for name, pattern in _ROLES:
        if pattern.search(text):
            return name
    return "external"


def build_flow(source: str, *, address: str = "", selectors: Optional[list[str]] = None) -> dict[str, Any]:
    """Graph from source text. Selectors with no source become a surface note."""
    from eth_scanner.heuristics.invariant_pass import functions, strip_comments

    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []
    root = (address or "target").lower()
    nodes[root] = {"id": root, "role": "target", "heat_contribution": 0}
    text = source or ""
    for match in _CALL.finditer(text):
        addr = match.group("addr").lower()
        label = "%s.%s" % (match.group("iface"), match.group("method"))
        _add_node(nodes, addr, role_of(label), label)
        edges.append({"src": root, "dst": addr, "relation": "calls", "label": label[:80]})
    for match in _APPROVE.finditer(text):
        spender = match.group("spender").lower()
        _add_node(nodes, spender, "external", "approve")
        edges.append({"src": root, "dst": spender, "relation": "approves", "label": "approve"})
    clean = strip_comments(text, "solidity") if text else ""
    for fn in functions(text, clean, "solidity") if text else []:
        body = str(fn.get("body") or "")
        callees = []
        for match in _CALL.finditer(body):
            addr = match.group("addr").lower()
            label = "%s.%s" % (match.group("iface"), match.group("method"))
            callees.append((addr, role_of(label)))
        for match in _APPROVE.finditer(body):
            callees.append((match.group("spender").lower(), "external"))
        moves = bool(_VALUE.search(body))
        for left, right in zip(callees, callees[1:]):
            edges.append({
                "src": left[0],
                "dst": right[0],
                "relation": "moves-value" if moves else "calls",
                "label": str(fn.get("name") or "")[:40],
            })
        if moves:
            for addr, role in callees:
                if role != "external":
                    edges.append({"src": root, "dst": addr, "relation": "moves-value", "label": str(fn.get("name") or "")[:40]})
    if selectors:
        joined = " ".join(selectors)
        role = role_of(joined)
        if role != "external":
            nodes.setdefault("surface", {"id": "surface", "role": role, "label": "bytecode", "heat_contribution": 0})
            edges.append({"src": root, "dst": "surface", "relation": "calls", "label": "bytecode"})
    paths = _paths(nodes, edges)
    return {
        "status": "ok" if len(nodes) > 1 or edges else "empty",
        "address": root,
        "nodes": [nodes[key] for key in sorted(nodes)],
        "edges": edges,
        "paths": paths,
        "flow_score": _score(paths),
        "selectors": list(selectors or [])[:32],
        "flow": bool(edges),
        "heat_contribution": 0,
        "note": "External calls, approvals, and value edges. A path score is a lead and adds no heat.",
    }


def _paths(nodes: dict[str, dict[str, Any]], edges: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Two-hop paths that move value and touch a dependency role."""
    by_src: dict[str, list[dict[str, str]]] = {}
    for edge in edges:
        by_src.setdefault(edge["src"], []).append(edge)
    found: list[dict[str, Any]] = []
    for first in edges:
        if first["relation"] not in {"calls", "approves", "moves-value"}:
            continue
        for second in by_src.get(first["dst"], []):
            roles = {nodes.get(first["dst"], {}).get("role"), nodes.get(second["dst"], {}).get("role")}
            roles.discard("target")
            roles.discard("external")
            roles.discard(None)
            moves = first["relation"] == "moves-value" or second["relation"] == "moves-value"
            if not moves or not roles:
                continue
            found.append({
                "hops": [first["dst"], second["dst"]],
                "roles": sorted(roles),
                "heat_contribution": 0,
            })
            if len(found) >= 8:
                return found
    if not found:
        for edge in edges:
            role = nodes.get(edge["dst"], {}).get("role")
            if edge["relation"] == "moves-value" and role not in {None, "target", "external"}:
                found.append({"hops": [edge["dst"]], "roles": [role], "heat_contribution": 0})
    return found[:8]


def _score(paths: list[dict[str, Any]]) -> int:
    """0 to 6. Longer role-bearing paths count more. Still not heat."""
    if not paths:
        return 0
    total = 0
    for path in paths:
        total += 1 + len(path.get("roles") or [])
    return min(6, total)
