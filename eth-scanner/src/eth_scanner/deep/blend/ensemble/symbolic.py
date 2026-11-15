"""Solidity SMTChecker lane (CHC and BMC) beside Halmos.

Runs on the verified harness. No new DSL. A counterexample is evidence.
Heat moves only when the log carries caller_profit_delta > 0, and even then
the number is handed to the existing caller-profit gate by the orchestrator.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

from eth_scanner.deep.blend.ensemble.versions import pin_version
from eth_scanner.deep.blend.parse import is_setup_or_compile_failure

_DELTA_RX = re.compile(r"caller_profit_delta[=:](\d+)")


def _solc_bin() -> Optional[str]:
    import os
    override = (os.environ.get("ETH_SCANNER_SOLC_BIN") or "").strip()
    if override:
        return override
    return shutil.which("solc")


def _one(engine: str, project: Path, timeout_s: int) -> dict[str, Any]:
    binary = _solc_bin()
    version = pin_version("smtchecker")
    if not binary:
        return {
            "engine": engine,
            "status": "skipped",
            "note": "solc not on PATH — SMTChecker %s skipped" % engine.upper(),
            "version": version,
            "heat_contribution": 0,
            "label": "evidence only",
            "caller_profit_delta": 0,
        }
    sol = project / "src" / "ConservationHarness.sol"
    if not sol.is_file():
        return {
            "engine": engine,
            "status": "skipped",
            "note": "harness missing",
            "version": version,
            "heat_contribution": 0,
            "label": "evidence only",
            "caller_profit_delta": 0,
        }
    cmd = [
        binary,
        "--model-checker-engine",
        engine,
        "--model-checker-targets",
        "assert",
        "--model-checker-timeout",
        "2000",
        "--base-path",
        str(project),
        str(sol),
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(project),
            capture_output=True,
            text=True,
            timeout=max(2, int(timeout_s)),
            check=False,
        )
        text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        return {
            "engine": engine,
            "status": "skipped",
            "note": "SMTChecker %s timed out" % engine.upper(),
            "version": version,
            "heat_contribution": 0,
            "label": "evidence only",
            "caller_profit_delta": 0,
        }
    except OSError as exc:
        return {
            "engine": engine,
            "status": "skipped",
            "note": "SMTChecker %s failed: %s" % (engine.upper(), str(exc)[:140]),
            "version": version,
            "heat_contribution": 0,
            "label": "evidence only",
            "caller_profit_delta": 0,
        }
    if is_setup_or_compile_failure(text) or "Error" in text[:400] and "Warning" not in text[:80]:
        # Compile failure is a skip. A model-checker warning is not a profit proof.
        if "Compiler error" in text or "Error: Source" in text or "ParserError" in text or is_setup_or_compile_failure(text):
            return {
                "engine": engine,
                "status": "skipped",
                "note": "SMTChecker %s compile skipped" % engine.upper(),
                "version": version,
                "heat_contribution": 0,
                "label": "evidence only",
                "caller_profit_delta": 0,
            }
    match = _DELTA_RX.search(text)
    delta = int(match.group(1)) if match else 0
    counterexample = "counterexample" in text.lower() or "assertion violation" in text.lower()
    return {
        "engine": engine,
        "status": "ok",
        "note": "SMTChecker %s exit=%s" % (engine.upper(), proc.returncode),
        "version": version,
        "heat_contribution": 0,
        "label": "evidence only",
        "counterexample": bool(counterexample),
        "caller_profit_delta": delta if delta > 0 else 0,
        "log_excerpt": text[-400:].replace("\n", " "),
    }


def run_smtchecker(project: Optional[Path], *, live: bool = False, timeout_s: int = 6) -> dict[str, Any]:
    """CHC then BMC. Both are evidence. Neither raises heat by itself."""
    version = pin_version("smtchecker")
    if not live or project is None:
        return {
            "status": "skipped",
            "note": "SMTChecker not invoked without verified source",
            "version": version,
            "heat_contribution": 0,
            "label": "evidence only",
            "chc": {"status": "skipped", "heat_contribution": 0, "label": "evidence only", "caller_profit_delta": 0},
            "bmc": {"status": "skipped", "heat_contribution": 0, "label": "evidence only", "caller_profit_delta": 0},
            "caller_profit_delta": 0,
            "findings": [],
        }
    limit = max(2, min(8, int(timeout_s or 6)))
    try:
        chc = _one("chc", project, limit)
    except Exception as exc:  # noqa: BLE001
        chc = {"engine": "chc", "status": "skipped", "note": str(exc)[:140], "heat_contribution": 0, "label": "evidence only", "caller_profit_delta": 0}
    try:
        bmc = _one("bmc", project, limit)
    except Exception as exc:  # noqa: BLE001
        bmc = {"engine": "bmc", "status": "skipped", "note": str(exc)[:140], "heat_contribution": 0, "label": "evidence only", "caller_profit_delta": 0}
    delta = max(int(chc.get("caller_profit_delta") or 0), int(bmc.get("caller_profit_delta") or 0))
    findings = []
    if chc.get("counterexample") or bmc.get("counterexample") or delta > 0:
        findings.append({
            "engine": "smtchecker",
            "rule": "no_caller_profit",
            "family": "caller-profit" if delta > 0 else "solvency",
            "title": "SMTChecker counterexample",
            "heat_contribution": 0,
            "label": "evidence only",
            "caller_profit_delta": delta if delta > 0 else 0,
        })
    status = "ok" if chc.get("status") == "ok" or bmc.get("status") == "ok" else "skipped"
    return {
        "status": status,
        "note": "CHC %s; BMC %s" % (chc.get("status"), bmc.get("status")),
        "version": version,
        "heat_contribution": 0,
        "label": "evidence only",
        "chc": chc,
        "bmc": bmc,
        "caller_profit_delta": delta if delta > 0 else 0,
        "findings": findings,
    }
