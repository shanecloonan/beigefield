"""Static and abstract-interpretation facts. Typed facts, never heat.

Slither and Aderyn stay. Pyrometer adds numeric bounds on share price and
amounts when its binary is installed. A missing binary or a compile failure
is a skip for that tool. The source-shape pass still runs.
"""

from __future__ import annotations

import re
import shutil
from typing import Any, Optional

from eth_scanner.deep.blend.ensemble.versions import pin_version
from eth_scanner.deep.blend.harness import public_functions

_ERC4626 = ("deposit", "mint", "withdraw", "redeem", "converttoshares", "converttoassets", "totalassets")
_ERC20 = ("transfer", "approve", "transferfrom", "balanceof", "totalsupply")
_VAULT = ("skim", "harvest", "poke", "strategy")
_BOUND_RX = re.compile(
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?:∈|in|:)\s*\[(?P<lo>-?\d+)\s*,\s*(?P<hi>-?\d+)\]"
    r"|(?P<name2>[A-Za-z_][A-Za-z0-9_]*)\s*(?:<=|≥|>=)\s*(?P<n>\d+)",
)


def _cold(status: str, note: str = "") -> dict[str, Any]:
    return {
        "status": status,
        "note": note,
        "version": "",
        "heat_contribution": 0,
        "label": "evidence only",
    }


def shape_of(source: str, contract_name: str = "") -> str:
    """Vault / token shape from verified source and the contract name."""
    names = {n.lower() for n in public_functions(source or "")}
    blob = (contract_name or "").lower()
    if sum(1 for n in _ERC4626 if n in names) >= 3 or "erc4626" in blob or "vault" in blob:
        if sum(1 for n in _ERC4626 if n in names) >= 2 or "erc4626" in blob:
            return "erc4626"
        if "vault" in blob or names & set(_VAULT):
            return "vault"
    if sum(1 for n in _ERC20 if n in names) >= 3 or blob in {"erc20", "token"}:
        return "erc20"
    if names & set(_VAULT) or "strategy" in blob:
        return "vault"
    return "generic"


def bug_classes_for(shape: str, facts: list[dict[str, Any]]) -> list[str]:
    classes: list[str] = []
    if shape == "erc4626":
        classes.append("erc4626-share-accounting")
    elif shape == "erc20":
        classes.append("erc20-supply-conservation")
    elif shape == "vault":
        classes.append("vault-value-conservation")
    else:
        classes.append("value-conservation")
    kinds = {str(row.get("kind") or "") for row in facts}
    if "detector" in kinds:
        classes.append("static-detector")
    if "abstract-bound" in kinds:
        classes.append("numeric-bound")
    if "share-price" in kinds:
        classes.append("share-price-bound")
    return classes


def _candidate_invariants(shape: str, functions: list[str]) -> list[dict[str, Any]]:
    """Invariants the spec layer should instrument. Not findings and not heat."""
    rows = [{
        "id": "no-unprivileged-caller-profit",
        "family": "caller-profit",
        "seeded_by": ["shape:%s" % shape],
        "heat_contribution": 0,
    }]
    lowered = {name.lower() for name in functions}
    if shape in {"erc4626", "vault"} or "converttoassets" in lowered or "totalassets" in lowered:
        rows.append({
            "id": "erc4626-share-price",
            "family": "solvency",
            "seeded_by": ["function:convertToAssets" if "converttoassets" in lowered else "shape:%s" % shape],
            "heat_contribution": 0,
        })
        rows.append({
            "id": "erc4626-assets-cover-shares",
            "family": "solvency",
            "seeded_by": ["shape:%s" % shape],
            "heat_contribution": 0,
        })
    if shape == "erc20" or "transfer" in lowered:
        rows.append({
            "id": "erc20-transfer-conservation",
            "family": "solvency",
            "seeded_by": ["function:transfer"] if "transfer" in lowered else ["shape:erc20"],
            "heat_contribution": 0,
        })
        rows.append({
            "id": "erc20-supply-constant",
            "family": "solvency",
            "seeded_by": ["shape:erc20"],
            "heat_contribution": 0,
        })
    return rows


def analyze_source(source: str, contract_name: str = "") -> dict[str, Any]:
    """Pure source facts. No subprocess. heat_contribution is 0."""
    functions = public_functions(source or "")
    shape = shape_of(source or "", contract_name)
    facts: list[dict[str, Any]] = [{
        "kind": "shape",
        "id": "shape:%s" % shape,
        "detail": "target shape %s from %d public functions" % (shape, len(functions)),
        "source": "source",
        "heat_contribution": 0,
        "label": "evidence only",
    }]
    for name in functions:
        low = name.lower()
        if low in {"converttoshares", "converttoassets", "totalassets", "pricepershare"}:
            facts.append({
                "kind": "share-price",
                "id": "function:%s" % name,
                "detail": "share-price surface %s" % name,
                "source": "source",
                "heat_contribution": 0,
                "label": "evidence only",
            })
        elif low in {"deposit", "withdraw", "mint", "redeem", "skim", "harvest", "transfer"}:
            facts.append({
                "kind": "value-moving",
                "id": "function:%s" % name,
                "detail": "value-moving surface %s" % name,
                "source": "source",
                "heat_contribution": 0,
                "label": "evidence only",
            })
    invariants = _candidate_invariants(shape, functions)
    return {
        "status": "ok",
        "note": "source shape",
        "heat_contribution": 0,
        "label": "evidence only",
        "shape": shape,
        "functions": functions,
        "facts": facts,
        "candidate_invariants": invariants,
        "bug_classes": bug_classes_for(shape, facts),
        "tools": {},
    }


def _slither_facts(source: str, timeout_s: int) -> dict[str, Any]:
    from eth_scanner.deep.runners import run_slither, slither_bin

    if not slither_bin():
        row = _cold("skipped", "slither not on PATH")
        row["version"] = pin_version("slither")
        return row
    try:
        result = run_slither(source, timeout_s=timeout_s)
    except Exception as exc:  # noqa: BLE001 — tool failure is a skip
        row = _cold("skipped", "slither failed: %s" % str(exc)[:160])
        row["version"] = pin_version("slither")
        return row
    facts = []
    for finding in result.findings or []:
        facts.append({
            "kind": "detector",
            "id": "slither:%s" % (getattr(finding, "rule", None) or "detector"),
            "detail": str(getattr(finding, "title", None) or getattr(finding, "rule", None) or "")[:180],
            "source": "slither",
            "function": getattr(finding, "function", None) or "",
            "heat_contribution": 0,
            "label": "evidence only",
        })
    return {
        "status": "skipped" if result.status == "skipped" else "ok",
        "note": result.note or "",
        "version": pin_version("slither"),
        "heat_contribution": 0,
        "label": "evidence only",
        "facts": facts,
    }


def _aderyn_facts(source: str, timeout_s: int) -> dict[str, Any]:
    from eth_scanner.deep.runners import aderyn_bin, run_aderyn

    if not aderyn_bin():
        row = _cold("skipped", "aderyn not on PATH")
        row["version"] = pin_version("aderyn")
        return row
    try:
        result = run_aderyn(source, timeout_s=timeout_s)
    except Exception as exc:  # noqa: BLE001
        row = _cold("skipped", "aderyn failed: %s" % str(exc)[:160])
        row["version"] = pin_version("aderyn")
        return row
    facts = []
    for finding in result.findings or []:
        facts.append({
            "kind": "detector",
            "id": "aderyn:%s" % (getattr(finding, "rule", None) or "detector"),
            "detail": str(getattr(finding, "title", None) or "")[:180],
            "source": "aderyn",
            "function": getattr(finding, "function", None) or "",
            "heat_contribution": 0,
            "label": "evidence only",
        })
    return {
        "status": "skipped" if result.status == "skipped" else "ok",
        "note": result.note or "",
        "version": pin_version("aderyn"),
        "heat_contribution": 0,
        "label": "evidence only",
        "facts": facts,
    }


def _pyrometer_bin() -> Optional[str]:
    import os
    override = (os.environ.get("ETH_SCANNER_PYROMETER_BIN") or "").strip()
    if override:
        return override
    return shutil.which("pyrometer")


def _pyrometer_facts(source: str, timeout_s: int) -> dict[str, Any]:
    """Numeric abstract interpretation. Bounds become facts, not heat."""
    import os
    import subprocess
    import tempfile
    from pathlib import Path

    binary = _pyrometer_bin()
    version = pin_version("pyrometer")
    if not binary:
        row = _cold("skipped", "pyrometer not on PATH")
        row["version"] = version
        return row
    text = source if "pragma solidity" in (source or "") else (
        "// SPDX-License-Identifier: MIT\npragma solidity ^0.8.20;\n" + (source or "")
    )
    try:
        with tempfile.TemporaryDirectory(prefix="pyrometer-") as tmp:
            path = Path(tmp) / "Target.sol"
            path.write_text(text, encoding="utf-8")
            proc = subprocess.run(
                [binary, str(path)],
                capture_output=True,
                text=True,
                timeout=max(2, int(timeout_s)),
                check=False,
                env=os.environ.copy(),
            )
            blob = (proc.stdout or "") + "\n" + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        row = _cold("skipped", "pyrometer timed out")
        row["version"] = version
        return row
    except OSError as exc:
        row = _cold("skipped", "pyrometer failed: %s" % str(exc)[:140])
        row["version"] = version
        return row
    if "error" in blob.lower() and "pragma" in blob.lower() and not _BOUND_RX.search(blob):
        row = _cold("skipped", "pyrometer compile or setUp skipped")
        row["version"] = version
        return row
    facts = []
    for match in _BOUND_RX.finditer(blob):
        name = match.group("name") or match.group("name2") or "amount"
        if match.group("lo") is not None:
            detail = "%s in [%s, %s]" % (name, match.group("lo"), match.group("hi"))
        else:
            detail = "%s bound %s" % (name, match.group("n"))
        facts.append({
            "kind": "abstract-bound",
            "id": "pyrometer:%s" % name,
            "detail": detail,
            "source": "pyrometer",
            "heat_contribution": 0,
            "label": "evidence only",
        })
    return {
        "status": "ok",
        "note": "pyrometer exit=%s bounds=%d" % (proc.returncode, len(facts)),
        "version": version,
        "heat_contribution": 0,
        "label": "evidence only",
        "facts": facts,
    }


def collect_facts(
    source: str,
    contract_name: str = "",
    *,
    live: bool = False,
    timeout_s: int = 6,
) -> dict[str, Any]:
    """Facts layer. Live tools run only on verified source. Failures skip."""
    report = analyze_source(source or "", contract_name)
    tools = {
        "slither": _cold("skipped", "fixture replay — slither not invoked"),
        "aderyn": _cold("skipped", "fixture replay — aderyn not invoked"),
        "pyrometer": _cold("skipped", "fixture replay — pyrometer not invoked"),
    }
    for row in tools.values():
        row["heat_contribution"] = 0
    if live and (source or "").strip():
        limit = max(2, min(8, int(timeout_s or 6)))
        try:
            tools["slither"] = _slither_facts(source, limit)
        except Exception as exc:  # noqa: BLE001
            tools["slither"] = _cold("skipped", "slither failed: %s" % str(exc)[:140])
        try:
            tools["aderyn"] = _aderyn_facts(source, limit)
        except Exception as exc:  # noqa: BLE001
            tools["aderyn"] = _cold("skipped", "aderyn failed: %s" % str(exc)[:140])
        try:
            tools["pyrometer"] = _pyrometer_facts(source, limit)
        except Exception as exc:  # noqa: BLE001
            tools["pyrometer"] = _cold("skipped", "pyrometer failed: %s" % str(exc)[:140])
        for tool in tools.values():
            for fact in tool.get("facts") or []:
                report["facts"].append(fact)
            # A numeric bound seeds a tighter invariant for the spec layer.
            for fact in tool.get("facts") or []:
                if fact.get("kind") == "abstract-bound":
                    report["candidate_invariants"].append({
                        "id": "amount-within-abstract-bound",
                        "family": "solvency",
                        "seeded_by": [fact.get("id") or "pyrometer"],
                        "heat_contribution": 0,
                    })
        report["bug_classes"] = bug_classes_for(report["shape"], report["facts"])
    elif not (source or "").strip():
        for row in tools.values():
            row["note"] = "no verified source — tool not invoked"
    for row in tools.values():
        row["heat_contribution"] = 0
        row["label"] = "evidence only"
    report["tools"] = tools
    report["heat_contribution"] = 0
    report["label"] = "evidence only"
    report["findings"] = [
        {
            "engine": fact.get("source") or "facts",
            "rule": fact.get("id") or "fact",
            "family": "solvency",
            "title": fact.get("detail") or fact.get("id") or "fact",
            "heat_contribution": 0,
            "label": "evidence only",
            "caller_profit_delta": 0,
        }
        for fact in report["facts"]
    ]
    return report
