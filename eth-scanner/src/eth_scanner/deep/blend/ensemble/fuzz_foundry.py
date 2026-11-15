"""Foundry invariant fuzz against the instrumented harness.

Ityfuzz, Medusa, and Echidna stay on their existing lane. This is the fourth
fuzzer. Compile or setUp failure skips. A positive caller_profit_delta is a
witness for the existing gate. This layer's own heat_contribution is 0.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Optional

from eth_scanner.deep.blend.ensemble.versions import pin_version
from eth_scanner.deep.blend.parse import _DELTA_RX, is_setup_or_compile_failure
from eth_scanner.deep.runners import forge_bin


def run_foundry_invariant(
    project: Optional[Path],
    *,
    live: bool = False,
    timeout_s: int = 8,
) -> dict[str, Any]:
    version = pin_version("foundry")
    if not live or project is None:
        return {
            "status": "skipped",
            "note": "foundry invariant not invoked without verified source",
            "version": version,
            "heat_contribution": 0,
            "label": "evidence only",
            "caller_profit_delta": 0,
            "findings": [],
        }
    binary = forge_bin()
    if not binary:
        return {
            "status": "skipped",
            "note": "forge not on PATH",
            "version": version,
            "heat_contribution": 0,
            "label": "evidence only",
            "caller_profit_delta": 0,
            "findings": [],
        }
    cmd = [
        binary,
        "test",
        "--match-contract",
        "ConservationHarness",
        "--fuzz-runs",
        "8",
    ]
    blob = " ".join(cmd).lower()
    if "broadcast" in blob or "flashloan" in blob:
        return {
            "status": "skipped",
            "note": "refused unsafe forge argv",
            "version": version,
            "heat_contribution": 0,
            "label": "evidence only",
            "caller_profit_delta": 0,
            "findings": [],
        }
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
            "status": "skipped",
            "note": "foundry invariant timed out",
            "version": version,
            "heat_contribution": 0,
            "label": "evidence only",
            "caller_profit_delta": 0,
            "findings": [],
        }
    except OSError as exc:
        return {
            "status": "skipped",
            "note": "foundry invariant failed: %s" % str(exc)[:140],
            "version": version,
            "heat_contribution": 0,
            "label": "evidence only",
            "caller_profit_delta": 0,
            "findings": [],
        }
    if is_setup_or_compile_failure(text) or "Compiler run failed" in text or "Error (" in text:
        return {
            "status": "skipped",
            "note": "foundry invariant compile or setUp skipped",
            "version": version,
            "heat_contribution": 0,
            "label": "evidence only",
            "caller_profit_delta": 0,
            "findings": [],
        }
    match = _DELTA_RX.search(text)
    delta = int(match.group(1)) if match else 0
    finding = None
    if "FAIL" in text or delta > 0:
        finding = {
            "engine": "foundry",
            "rule": "invariant_no_caller_profit",
            "family": "caller-profit" if delta > 0 else "solvency",
            "title": "foundry invariant",
            "heat_contribution": 0,
            "label": "evidence only",
            "caller_profit_delta": delta if delta > 0 else 0,
        }
    return {
        "status": "ok",
        "note": "forge test exit=%s" % proc.returncode,
        "version": version,
        "heat_contribution": 0,
        "label": "evidence only",
        "caller_profit_delta": delta if delta > 0 else 0,
        "findings": [finding] if finding else [],
    }
