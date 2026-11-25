"""Solidity SMTChecker. solc is GPL-3.0 and is not linked or vendored.

The check runs only for a shortlist contract, and only when ``solc`` is
already installed. ``--model-checker-timeout`` bounds the query. The
targets are overflow, underflow, division by zero, and assert. A proved
violation is 1. The same violation in a value-moving function is 3.
An unproved target adds 0. Counterexample calldata is not stored.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional

PIN = {
    "url": "https://github.com/ethereum/solidity",
    "license": "GPL-3.0",
    "link": False,
}
DEFAULT_TIMEOUT_S = 10
_ENGINES = {"chc", "bmc"}
_TARGETS = ["underflow", "overflow", "divByZero", "assert"]
_VALUE_FN = frozenset({
    "withdraw", "deposit", "redeem", "mint", "burn", "transfer", "transferfrom",
    "swap", "borrow", "repay", "liquidate", "liquidationcall", "skim", "harvest",
    "claim", "stake", "unstake",
})
_HEX = re.compile(r"0x[0-9a-fA-F]{8,}")
_FUNC = re.compile(r"\bfunction\s+([A-Za-z_][A-Za-z0-9_]*)")
_PROVED = re.compile(r"happens here", re.I)
_MIGHT = re.compile(r"\bmight\b", re.I)
Runner = Callable[[list[str], str, int], tuple[int, str]]


def solc_bin() -> Optional[str]:
    override = (os.environ.get("ETH_SCANNER_SOLC_BIN") or "").strip()
    if override and Path(override).is_file():
        return override
    return shutil.which("solc")


def standard_input(source: str, *, engine: str, timeout_ms: int) -> dict[str, Any]:
    """One file, one engine, and the four targets. No extra output."""
    chosen = engine if engine in _ENGINES else "chc"
    return {
        "language": "Solidity",
        "sources": {"Target.sol": {"content": source or ""}},
        "settings": {
            "modelChecker": {
                "engine": chosen,
                "timeout": int(timeout_ms),
                "targets": list(_TARGETS),
                "showUnproved": False,
            },
            "outputSelection": {"*": {"": []}},
        },
    }


def parse_smt(raw: str) -> list[dict[str, Any]]:
    """Proved violations only. Drop hex and unproved warnings."""
    try:
        data = json.loads(raw or "")
    except json.JSONDecodeError:
        return []
    errors = data.get("errors") if isinstance(data, dict) else None
    if not isinstance(errors, list):
        return []
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in errors:
        if not isinstance(item, dict):
            continue
        message = str(item.get("message") or "")
        component = str(item.get("component") or "")
        if component != "SMTChecker" and "CHC:" not in message and "BMC:" not in message:
            continue
        if _MIGHT.search(message) or not _PROVED.search(message):
            continue
        kind = _kind(message)
        if not kind:
            continue
        function = _function(item, message)
        key = (kind, function)
        if key in seen:
            continue
        seen.add(key)
        value = function.lower() in _VALUE_FN
        rows.append({
            "kind": kind,
            "function": function[:80],
            "value_moving": value,
            "weight": 3 if value else 1,
        })
        if len(rows) >= 8:
            break
    return rows


def smt_points(rows: list[dict[str, Any]]) -> int:
    total = sum(int(row.get("weight") or 0) for row in rows)
    return min(3, max(0, total))


def run_smt(
    source: str,
    *,
    on_shortlist: bool = False,
    engine: str = "chc",
    timeout_s: int = DEFAULT_TIMEOUT_S,
    runner: Optional[Runner] = None,
    which: Optional[Callable[[str], Optional[str]]] = None,
) -> dict[str, Any]:
    """One shortlist contract. A public run is refused by the shortlist gate."""
    report: dict[str, Any] = {
        "engine": "smt",
        "status": "skipped",
        "ran": False,
        "violations": [],
        "points": 0,
        "heat_contribution": 0,
        "note": "",
    }
    if not on_shortlist:
        report["note"] = "SMTChecker runs only for a shortlist contract."
        return report
    if not (source or "").strip():
        report["note"] = "SMTChecker needs verified source."
        return report
    chosen = engine if engine in _ENGINES else "chc"
    seconds = _seconds(timeout_s)
    located = which("solc") if which is not None else solc_bin()
    if runner is None and not located:
        report["note"] = "solc is not installed. SMTChecker was not run."
        return report
    payload = json.dumps(standard_input(source, engine=chosen, timeout_ms=seconds * 1000))
    argv = [located or "solc", "--standard-json"]
    try:
        _code, text = (runner or _run_cli)(argv, payload, seconds + 5)
    except subprocess.TimeoutExpired:
        report["status"] = "timeout"
        report["ran"] = True
        report["note"] = "SMTChecker timed out. No violation was kept."
        return report
    except Exception as exc:  # noqa: BLE001
        report["status"] = "error"
        report["note"] = "SMTChecker failed (%s). No violation was kept." % type(exc).__name__
        return report
    rows = parse_smt(text)
    points = smt_points(rows)
    report["ran"] = True
    report["status"] = "violation" if rows else "ok"
    report["violations"] = rows
    report["points"] = points
    report["heat_contribution"] = points
    report["note"] = (
        "A value-moving violation weighs 3. Any other proved violation weighs 1."
        if rows
        else "SMTChecker found no proved violation."
    )
    return report


def _kind(message: str) -> str:
    text = message.lower()
    if "underflow" in text:
        return "underflow"
    if "overflow" in text:
        return "overflow"
    if "division by zero" in text or "div by zero" in text:
        return "div-by-zero"
    if "assertion" in text:
        return "assert"
    return ""


def _function(item: dict[str, Any], message: str) -> str:
    for row in item.get("secondarySourceLocations") or []:
        if isinstance(row, dict):
            name = str(row.get("function") or "").strip()
            if name:
                return name.split(".")[-1]
    match = _FUNC.search(message)
    return match.group(1) if match else ""


def _seconds(timeout_s: int) -> int:
    try:
        value = int(timeout_s)
    except (TypeError, ValueError):
        value = DEFAULT_TIMEOUT_S
    return max(5, min(20, value))


def _run_cli(argv: list[str], payload: str, timeout_s: int) -> tuple[int, str]:
    proc = subprocess.run(
        argv,
        input=payload,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )
    return proc.returncode, proc.stdout or ""


def redact(text: str) -> str:
    return _HEX.sub("0x…", text or "")
