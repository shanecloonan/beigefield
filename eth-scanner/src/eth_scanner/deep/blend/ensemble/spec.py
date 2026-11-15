"""Spec and property instrumentation seeded by the facts layer.

Scribble compiles value-conservation into inline asserts when its CLI is
installed. crytic/properties packs are chosen from the target shape
(ERC-20, ERC-4626, vault). The selected properties are what the fuzzers
already exercise. A missing tool is a skip. Heat stays 0.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Optional

from eth_scanner.deep.blend.ensemble.versions import pin_version

# Property ids aligned with crytic/properties packs. The facts layer decides
# which of these get instrumented.
_PACKS: dict[str, list[str]] = {
    "erc4626": [
        "no-unprivileged-caller-profit",
        "erc4626-share-price",
        "erc4626-assets-cover-shares",
    ],
    "erc20": [
        "no-unprivileged-caller-profit",
        "erc20-transfer-conservation",
        "erc20-supply-constant",
    ],
    "vault": [
        "no-unprivileged-caller-profit",
        "erc4626-share-price",
        "erc4626-assets-cover-shares",
    ],
    "generic": [
        "no-unprivileged-caller-profit",
    ],
}


def select_properties(facts: dict[str, Any]) -> list[str]:
    """Facts seed the pack. Candidate invariants are added on top of the shape pack."""
    shape = str(facts.get("shape") or "generic")
    selected: list[str] = []
    for prop in _PACKS.get(shape) or _PACKS["generic"]:
        if prop not in selected:
            selected.append(prop)
    for inv in facts.get("candidate_invariants") or []:
        prop = str(inv.get("id") or "")
        if prop and prop not in selected:
            selected.append(prop)
    return selected


def _crytic_root() -> Optional[Path]:
    raw = (os.environ.get("ETH_SCANNER_CRYTIC_PROPERTIES") or "").strip()
    if raw:
        path = Path(raw)
        return path if path.is_dir() else None
    default = Path.home() / ".local" / "share" / "eth-scanner" / "crytic-properties"
    return default if default.is_dir() else None


def _scribble_bin() -> Optional[str]:
    override = (os.environ.get("ETH_SCANNER_SCRIBBLE_BIN") or "").strip()
    if override:
        return override
    return shutil.which("scribble")


def crytic_block(facts: dict[str, Any], selected: list[str]) -> dict[str, Any]:
    root = _crytic_root()
    shape = str(facts.get("shape") or "generic")
    pack = "ERC4626" if shape in {"erc4626", "vault"} else ("ERC20" if shape == "erc20" else "generic")
    files: list[str] = []
    if root is not None:
        folder = root / "contracts" / pack if pack != "generic" else None
        if folder is not None and folder.is_dir():
            files = sorted(str(path.relative_to(root)) for path in folder.rglob("*.sol"))[:40]
    status = "ok" if root is not None else "skipped"
    note = "crytic/properties checkout %s" % root if root is not None else (
        "crytic/properties checkout not installed — selected ids are still instrumented in the harness"
    )
    return {
        "status": status,
        "note": note,
        "version": pin_version("crytic-properties"),
        "pack": pack,
        "properties": list(selected),
        "upstream_files": files,
        "heat_contribution": 0,
        "label": "evidence only",
    }


def scribble_annotations(selected: list[str]) -> str:
    """Annotation block Scribble compiles to asserts. Also the spec the harness mirrors."""
    lines = [
        "/// #define callerProfit(before) uint256 = address(0xBEEF).balance - before;",
    ]
    for prop in selected:
        if "profit" in prop or "conservation" in prop:
            lines.append(
                "/// #if_succeeds {:msg \"property %s caller_profit_delta=0\"} "
                "address(0xBEEF).balance <= old(address(0xBEEF).balance);" % prop
            )
        elif "share" in prop or "assets" in prop or "supply" in prop or "bound" in prop:
            lines.append(
                "/// #if_succeeds {:msg \"property %s\"} address(0xBEEF).balance <= old(address(0xBEEF).balance);"
                % prop
            )
    return "\n".join(lines)


def try_scribble(project: Path, *, timeout_s: int = 8) -> dict[str, Any]:
    """Compile annotations if the Scribble CLI is installed. Failure skips."""
    import subprocess

    binary = _scribble_bin()
    version = pin_version("scribble")
    if not binary:
        return {
            "status": "skipped",
            "note": "scribble not on PATH — harness already contains the equivalent asserts",
            "version": version,
            "heat_contribution": 0,
            "label": "evidence only",
        }
    target = project / "src" / "ConservationHarness.sol"
    if not target.is_file():
        return {
            "status": "skipped",
            "note": "harness missing — scribble skipped",
            "version": version,
            "heat_contribution": 0,
            "label": "evidence only",
        }
    out = project / "src" / "ConservationHarness.sol.instrumented"
    try:
        proc = subprocess.run(
            [
                binary,
                str(target),
                "--output-mode",
                "files",
                "--utils-output-path",
                str(project / "src"),
            ],
            cwd=str(project),
            capture_output=True,
            text=True,
            timeout=max(2, int(timeout_s)),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "skipped",
            "note": "scribble timed out",
            "version": version,
            "heat_contribution": 0,
            "label": "evidence only",
        }
    except OSError as exc:
        return {
            "status": "skipped",
            "note": "scribble failed: %s" % str(exc)[:140],
            "version": version,
            "heat_contribution": 0,
            "label": "evidence only",
        }
    blob = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if proc.returncode != 0 or not out.is_file():
        return {
            "status": "skipped",
            "note": "scribble compile skipped: %s" % blob.replace("\n", " ")[:180],
            "version": version,
            "heat_contribution": 0,
            "label": "evidence only",
        }
    return {
        "status": "ok",
        "note": "scribble instrumented ConservationHarness",
        "version": version,
        "output": str(out.name),
        "heat_contribution": 0,
        "label": "evidence only",
    }


def build_spec(facts: dict[str, Any]) -> dict[str, Any]:
    selected = select_properties(facts or {})
    seeded = []
    for inv in (facts or {}).get("candidate_invariants") or []:
        for src in inv.get("seeded_by") or []:
            if src not in seeded:
                seeded.append(src)
    return {
        "status": "ok",
        "note": "properties seeded by facts",
        "heat_contribution": 0,
        "label": "evidence only",
        "shape": (facts or {}).get("shape") or "generic",
        "selected": selected,
        "seeded_by": seeded,
        "annotations": scribble_annotations(selected),
        "scribble": {
            "status": "pending",
            "note": "runs after the harness is written",
            "version": pin_version("scribble"),
            "heat_contribution": 0,
            "label": "evidence only",
        },
        "crytic_properties": crytic_block(facts or {}, selected),
        "findings": [
            {
                "engine": "spec",
                "rule": prop,
                "family": "caller-profit" if "profit" in prop else "solvency",
                "title": "instrumented property %s" % prop,
                "heat_contribution": 0,
                "label": "evidence only",
                "caller_profit_delta": 0,
            }
            for prop in selected
        ],
    }
