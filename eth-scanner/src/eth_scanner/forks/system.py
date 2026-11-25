"""Name the fund-flow dependencies a local anvil fork should already hold.

The set is capped and ordered so an oracle, AMM, lender, or bridge is
kept ahead of a plain external address. ``--run`` reads ``eth_getCode``
on a loopback anvil only. The fork URL is never stored. Heat stays 0.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from eth_scanner.flow.graph import build_flow

_ADDR = re.compile(r"^0x[a-f0-9]{40}$")
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}
_RANK = {"oracle": 0, "amm": 1, "lending": 2, "bridge": 3, "external": 4}
MAX_DEPENDENCIES = 12
_READ = "eth_getCode"
_REFUSED = frozenset({
    "eth_sendTransaction",
    "eth_sendRawTransaction",
    "eth_sendUnsignedTransaction",
    "eth_newPendingTransactionFilter",
    "eth_getFilterChanges",
    "txpool_content",
    "txpool_inspect",
    "eth_subscribe",
})

Caller = Callable[[str, str, list[Any]], Any]


def _loopback(url: str) -> bool:
    raw = (url or "").strip()
    if not raw:
        return False
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    return parsed.scheme in {"http", "https"} and host in _LOOPBACK


def _dependencies(report: dict[str, Any], root: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for node in report.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        addr = str(node.get("id") or "").lower()
        if addr == root or addr in seen or not _ADDR.match(addr):
            continue
        seen.add(addr)
        role = str(node.get("role") or "external")
        if role not in _RANK:
            role = "external"
        rows.append({"address": addr, "role": role})
    rows.sort(key=lambda row: (_RANK[row["role"]], row["address"]))
    return rows


def _present(result: Any) -> tuple[bool, int]:
    if not isinstance(result, str) or not result.startswith("0x"):
        return False, 0
    body = result[2:]
    if len(body) < 2 or set(body) <= {"0"}:
        return False, 0
    return True, len(body) // 2


def _write(dest: Path, address: str, deps: list[dict[str, str]]) -> list[str]:
    dest.mkdir(parents=True, exist_ok=True)
    manifest = {
        "address": address,
        "dependencies": deps,
        "heat_contribution": 0,
        "note": "Addresses to resolve on a loopback anvil. No calldata is stored.",
    }
    (dest / "system.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    test_dir = dest / "test"
    test_dir.mkdir(exist_ok=True)
    checks = ['        require(address(%s).code.length > 0, "target");' % address]
    for row in deps:
        checks.append('        require(address(%s).code.length > 0, "dependency");' % row["address"])
    source = "\n".join([
        "// SPDX-License-Identifier: MIT",
        "pragma solidity ^0.8.20;",
        "",
        "// Read-only code check. Run it against a loopback anvil. No value is moved.",
        "contract SystemFork {",
        "    function test_system_has_code() public view {",
        *checks,
        "    }",
        "}",
        "",
    ])
    (test_dir / "SystemFork.t.sol").write_text(source, encoding="utf-8")
    return ["system.json", "test/SystemFork.t.sol"]


def plan_system(
    source: str,
    *,
    address: str = "",
    fork_url: str = "",
    on_shortlist: bool = False,
    verified: bool = False,
    execute: bool = False,
    caller: Optional[Caller] = None,
    dest: Optional[Path] = None,
) -> dict[str, Any]:
    """Plan a loopback system fork. A non-loopback URL is refused first."""
    root = (address or "").strip().lower()
    report: dict[str, Any] = {
        "status": "skipped",
        "address": root,
        "dependencies": [],
        "dependency_count": 0,
        "truncated": False,
        "loaded": 0,
        "executed": False,
        "refused": False,
        "system": False,
        "calls": [],
        "heat_contribution": 0,
        "note": "",
    }
    url = (fork_url or "").strip()
    if url and not _loopback(url):
        report["status"] = "refused"
        report["refused"] = True
        report["note"] = "A system fork reads only a loopback anvil. No public RPC was contacted."
        return report
    if not on_shortlist:
        report["note"] = "A system fork runs only for a shortlist contract."
        return report
    if not verified:
        report["note"] = "A system fork runs only on verified source."
        return report
    if not (source or "").strip():
        report["note"] = "Verified source is required."
        return report
    if not _ADDR.match(root):
        report["note"] = "A system fork needs the target address."
        return report
    flow = build_flow(source, address=root)
    chosen = _dependencies(flow, root)
    report["truncated"] = len(chosen) > MAX_DEPENDENCIES
    chosen = chosen[:MAX_DEPENDENCIES]
    report["dependencies"] = chosen
    report["dependency_count"] = len(chosen)
    if not chosen:
        report["status"] = "empty"
        report["note"] = "No dependency address was named in the fund-flow graph."
        return report
    if dest is not None:
        report["files"] = _write(dest, root, chosen)
    report["system"] = True
    report["heat_contribution"] = 0
    if not execute:
        report["status"] = "ok"
        report["note"] = (
            "Dependency set for a loopback anvil. "
            "Code is read only when --run is set. Heat stays 0."
        )
        return report
    if not url:
        report["status"] = "skipped"
        report["note"] = "Pass a loopback anvil URL with --run. Nothing was contacted."
        return report
    if caller is None:
        report["status"] = "skipped"
        report["note"] = "No local fork client was provided. Nothing was contacted."
        return report
    loaded = 0
    try:
        for row in chosen:
            if _READ in _REFUSED:
                raise ValueError("refused")
            report["calls"].append(_READ)
            present, size = _present(caller(url, _READ, [row["address"], "latest"]))
            row["present"] = present
            row["code_bytes"] = size
            if present:
                loaded += 1
        target_present, _ = _present(caller(url, _READ, [root, "latest"]))
        report["calls"].append(_READ)
    except Exception:
        report["status"] = "skipped"
        report["loaded"] = 0
        report["executed"] = False
        report["note"] = "The local code read failed. The fork URL is not stored."
        return report
    report["loaded"] = loaded
    report["executed"] = True
    report["target_present"] = target_present
    report["status"] = "ok"
    report["note"] = "eth_getCode on a loopback anvil. No transaction was sent. Heat stays 0."
    return report


def public_report(report: dict[str, Any]) -> dict[str, Any]:
    """Fields safe to print. The fork URL is not one of them."""
    deps = report.get("dependencies") or []
    return {
        "status": report.get("status"),
        "address": report.get("address"),
        "dependencies": [row.get("address") for row in deps if isinstance(row, dict)],
        "roles": {
            str(row.get("address")): row.get("role")
            for row in deps
            if isinstance(row, dict)
        },
        "truncated": bool(report.get("truncated")),
        "loaded": int(report.get("loaded") or 0),
        "executed": bool(report.get("executed")),
        "system": bool(report.get("system")),
        "heat": 0,
        "heat_breakdown": {"system": bool(report.get("system"))},
        "note": report.get("note"),
    }
