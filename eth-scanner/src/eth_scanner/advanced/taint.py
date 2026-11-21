"""Source-level flows into delegatecall, oracle reads, and value moves.

These are leads. They add no heat. A delegatecall to address(this) or to a
literal is not treated as untrusted input. An oracle read counts only when
the same function later moves value.
"""

from __future__ import annotations

import re
from typing import Any

from eth_scanner.heuristics.invariant_pass import functions, strip_comments

_DELEGATE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\.delegatecall\s*\(", re.I)
_LITERAL_DELEGATE = re.compile(r"address\s*\(\s*this\s*\)\s*\.delegatecall", re.I)
_ORACLE = re.compile(
    r"\b(?:latestAnswer|latestRoundData|getRoundData|consult|getPrice|latestAnswer)\s*\(",
    re.I,
)
_VALUE = re.compile(
    r"\.transfer\s*\(|\.transferFrom\s*\(|safeTransfer(?:From)?\s*\(|\.call\s*\{[^}]*value",
    re.I,
)


def trace_source(source: str) -> list[dict[str, Any]]:
    clean = strip_comments(source or "", "solidity")
    flows: list[dict[str, Any]] = []
    for fn in functions(source or "", clean, "solidity"):
        body = str(fn.get("body") or "")
        name = str(fn.get("name") or "")
        for match in _DELEGATE.finditer(body):
            window = body[max(0, match.start() - 24):match.end()]
            if _LITERAL_DELEGATE.search(window):
                continue
            target = match.group(1)
            if target.lower() == "address":
                continue
            flows.append({
                "function": name,
                "sink": "delegatecall",
                "detail": target,
                "heat_contribution": 0,
            })
        if _ORACLE.search(body) and _VALUE.search(body):
            oracle_at = _ORACLE.search(body)
            value_at = _VALUE.search(body)
            if oracle_at and value_at and oracle_at.start() < value_at.start():
                flows.append({
                    "function": name,
                    "sink": "value-after-oracle",
                    "detail": "oracle read precedes a value move",
                    "heat_contribution": 0,
                })
    return flows


def taint_report(source: str) -> dict[str, Any]:
    flows = trace_source(source)
    return {
        "status": "ok",
        "flows": flows,
        "heat_contribution": 0,
        "note": "Taint leads add no heat.",
    }
