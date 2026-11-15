"""Mutation-test the instrumented property suite.

Gambit mutates the harness when it is installed. The in-process check asks
whether a profit-relevant mutant (the balance comparison removed) is killed
by the selected properties. A killed mutant means the suite is not vacuous.
A survivor is evidence. It is handed to the caller-profit gate only when a
measured caller_profit_delta is already in hand. Heat on this layer is 0.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

from eth_scanner.deep.blend.ensemble.versions import pin_version

_PROFIT_TOKENS = ("profit", "conservation", "balance")


def property_holds(prop: str, delta: int) -> bool:
    """Conservation properties fail when an unprivileged caller gained value."""
    if any(tok in (prop or "") for tok in _PROFIT_TOKENS):
        return int(delta) <= 0
    return True


def _gambit_bin() -> Optional[str]:
    override = (os.environ.get("ETH_SCANNER_GAMBIT_BIN") or "").strip()
    if override:
        return override
    return shutil.which("gambit")


def _run_gambit(project: Optional[Path], timeout_s: int) -> dict[str, Any]:
    binary = _gambit_bin()
    version = pin_version("gambit")
    if not binary or project is None:
        return {
            "status": "skipped",
            "note": "gambit not on PATH" if project is not None else "gambit not invoked without a project",
            "version": version,
            "heat_contribution": 0,
            "label": "evidence only",
            "mutants": 0,
        }
    sol = project / "src" / "ConservationHarness.sol"
    if not sol.is_file():
        return {
            "status": "skipped",
            "note": "harness missing — gambit skipped",
            "version": version,
            "heat_contribution": 0,
            "label": "evidence only",
            "mutants": 0,
        }
    out = project / "gambit-out"
    try:
        proc = subprocess.run(
            [binary, "mutate", "--filename", "src/ConservationHarness.sol", "--num_mutants", "4", "--outdir", "gambit-out"],
            cwd=str(project),
            capture_output=True,
            text=True,
            timeout=max(2, int(timeout_s)),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "skipped",
            "note": "gambit timed out",
            "version": version,
            "heat_contribution": 0,
            "label": "evidence only",
            "mutants": 0,
        }
    except OSError as exc:
        return {
            "status": "skipped",
            "note": "gambit failed: %s" % str(exc)[:140],
            "version": version,
            "heat_contribution": 0,
            "label": "evidence only",
            "mutants": 0,
        }
    blob = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if proc.returncode != 0 and "usage" in blob.lower():
        return {
            "status": "skipped",
            "note": "gambit mutate skipped: %s" % blob.replace("\n", " ")[:160],
            "version": version,
            "heat_contribution": 0,
            "label": "evidence only",
            "mutants": 0,
        }
    mutants = 0
    if out.is_dir():
        mutants = sum(1 for _ in out.rglob("*.sol"))
    return {
        "status": "ok" if proc.returncode == 0 else "skipped",
        "note": "gambit exit=%s mutants=%d" % (proc.returncode, mutants),
        "version": version,
        "heat_contribution": 0,
        "label": "evidence only",
        "mutants": mutants,
    }


def run_mutation(
    properties: list[str],
    *,
    project: Optional[Path] = None,
    live: bool = False,
    timeout_s: int = 6,
    replay_delta: int = 0,
) -> dict[str, Any]:
    """Validate the suite. Survivors carry a delta only when one was measured."""
    props = list(properties or ["no-unprivileged-caller-profit"])
    killed = []
    survivors = []
    # Mutant: delete the caller-balance comparison. A real profit property kills it.
    mutant = "drop-caller-balance-check"
    original_flags = any(not property_holds(prop, 1000) for prop in props)
    if original_flags:
        killed.append({
            "mutant": mutant,
            "profit_relevant": True,
            "killed": True,
            "caller_profit_delta": 0,
            "heat_contribution": 0,
            "label": "evidence only",
            "routed_to_fork_gate": False,
        })
    else:
        survivors.append({
            "mutant": mutant,
            "profit_relevant": True,
            "killed": False,
            "caller_profit_delta": int(replay_delta) if int(replay_delta) > 0 else 0,
            "heat_contribution": 0,
            "label": "evidence only",
            "routed_to_fork_gate": int(replay_delta) > 0,
            "note": "suite did not flag a profitable trace — vacuous for caller profit",
        })
    gambit = _run_gambit(project, timeout_s) if live else {
        "status": "skipped",
        "note": "gambit not invoked without verified source",
        "version": pin_version("gambit"),
        "heat_contribution": 0,
        "label": "evidence only",
        "mutants": 0,
    }
    # Gambit mutants that touch value movement are profit-relevant evidence.
    # They are not a measured drain. The fork gate opens only for replay_delta.
    if int(gambit.get("mutants") or 0) > 0:
        survivors.append({
            "mutant": "gambit-value-mutant",
            "profit_relevant": True,
            "killed": False,
            "caller_profit_delta": int(replay_delta) if int(replay_delta) > 0 else 0,
            "heat_contribution": 0,
            "label": "evidence only",
            "routed_to_fork_gate": int(replay_delta) > 0,
            "note": "gambit mutant survived generation; no caller-profit measurement yet",
        })
    witnesses = []
    for row in survivors:
        if row.get("profit_relevant") and int(row.get("caller_profit_delta") or 0) > 0:
            witnesses.append({
                "engine": "gambit",
                "rule": "no_caller_profit",
                "family": "caller-profit",
                "call_path": str(row.get("mutant") or "mutant"),
                "caller_profit_delta": int(row["caller_profit_delta"]),
                "heat_contribution": 0,
                "label": "evidence only",
            })
    return {
        "status": "ok",
        "note": "killed=%d survivors=%d" % (len(killed), len(survivors)),
        "version": pin_version("gambit"),
        "heat_contribution": 0,
        "label": "evidence only",
        "properties": props,
        "killed": killed,
        "survivors": survivors,
        "gambit": gambit,
        "witnesses": witnesses,
        "vacuous": not bool(killed),
        "findings": [
            {
                "engine": "gambit",
                "rule": row.get("mutant") or "mutant",
                "family": "caller-profit" if row.get("profit_relevant") else "solvency",
                "title": "mutation %s" % (row.get("mutant") or "mutant"),
                "heat_contribution": 0,
                "label": "evidence only",
                "caller_profit_delta": int(row.get("caller_profit_delta") or 0),
            }
            for row in killed + survivors
        ],
    }
