"""L2 — Slither integration with a funds-safety detector allowlist.

Runs when the `slither` CLI and Solidity source are present. Findings are
parsed into the research schema. Missing tools → skip, never crash.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

from eth_scanner.research.types import Finding, LayerSkip, _norm_severity

# Curated funds-safety allowlist. No style / naming / pragma noise.
#
# Slither 0.11.6 has no generic integer-overflow detector (checked arithmetic
# is a 0.8+ language feature). Arithmetic coverage is divide-before-multiply,
# incorrect-equality, incorrect-shift, incorrect-exp, and incorrect-unary.
# There is no `incorrect-constructor-name` check; `multiple-constructors` is
# the closest 0.11.6 equivalent (old + new constructor schemes in one contract).
# There is no front-running / transaction-order detector; `tx-origin` stays as
# an access-control check (already allowlisted).
SLITHER_ALLOWLIST = frozenset({
    "reentrancy-eth",
    "reentrancy-no-eth",
    "reentrancy-benign",
    "reentrancy-unlimited-gas",
    "arbitrary-send",
    "arbitrary-send-eth",
    "arbitrary-send-erc20",
    "arbitrary-send-erc20-permit",
    "controlled-delegatecall",
    "uncontrolled-delegatecall",
    "uninitialized-storage",
    "uninitialized-state",
    "suicidal",
    "tx-origin",
    "unprotected-upgrade",
    "protected-vars",
    "multiple-constructors",
    "unchecked-transfer",
    "unchecked-lowlevel",
    "unchecked-send",
    "locked-ether",
    "delegatecall-loop",
    "calls-loop",
    "costly-loop",
    "msg-value-loop",
    "weak-prng",
    "timestamp",
    "encode-packed-collision",
    "incorrect-equality",
    "incorrect-shift",
    "incorrect-exp",
    "incorrect-unary",
    "unused-return",
    "mapping-deletion",
    "divide-before-multiply",
    "return-leave",
    "storage-array",
    "array-by-reference",
    "write-after-write",
})

# Noisy checks still flow through as findings, but are capped so they cannot
# inflate drain / triage scores on their own.
SLITHER_SEVERITY_OVERRIDE = {
    "timestamp": "info",
    "costly-loop": "info",
}

_IMPACT_TO_SEV = {
    "informational": "info",
    "low": "low",
    "medium": "med",
    "high": "high",
    "critical": "crit",
}


def slither_available() -> bool:
    return bool(shutil.which("slither"))


def _severity_from_impact(impact: str) -> str:
    return _IMPACT_TO_SEV.get((impact or "").strip().lower(), "info")


def slither_severity(check: str, impact: str = "") -> str:
    """Map a Slither check + impact onto the research severity scale.

    Allowlisted noisy detectors (timestamp, costly-loop) are forced to
    informational regardless of the tool's own impact label.
    """
    check = (check or "").strip()
    if check in SLITHER_SEVERITY_OVERRIDE:
        return SLITHER_SEVERITY_OVERRIDE[check]  # type: ignore[return-value]
    return _norm_severity(_severity_from_impact(impact))


def parse_slither_json(payload: Any, *, address: str) -> list[Finding]:
    """Map a Slither `--json` document onto Finding rows (allowlisted only)."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return []
    if not isinstance(payload, dict):
        return []
    results = payload.get("results") or {}
    detectors = results.get("detectors") if isinstance(results, dict) else None
    if detectors is None and isinstance(payload.get("detectors"), list):
        detectors = payload["detectors"]
    if not isinstance(detectors, list):
        return []
    findings: list[Finding] = []
    counts: dict[str, int] = {}
    for row in detectors:
        if not isinstance(row, dict):
            continue
        check = str(row.get("check") or row.get("detector") or "")
        if check not in SLITHER_ALLOWLIST:
            continue
        counts[check] = counts.get(check, 0) + 1
        desc = str(row.get("description") or row.get("markdown") or check)
        impact = str(row.get("impact") or "")
        elements = row.get("elements") or []
        locus = ""
        if isinstance(elements, list) and elements:
            el0 = elements[0] if isinstance(elements[0], dict) else {}
            src = (el0.get("source_mapping") or {}) if isinstance(el0, dict) else {}
            fname = src.get("filename_short") or src.get("filename_relative") or ""
            lines = src.get("lines") or []
            if fname or lines:
                locus = " @ %s:%s" % (fname, lines[0] if lines else "?")
        findings.append(Finding(
            id="L2-slither-%s-%d" % (check, counts[check]),
            severity=slither_severity(check, impact),
            layer="L2",
            title="Slither %s" % check,
            evidence=(desc.strip() + locus)[:2000],
            address=address,
            detector="slither:%s" % check,
        ))
    return findings


def run_slither(
    *,
    address: str,
    source: str,
    source_dir: Optional[Path] = None,
    timeout_s: int = 90,
) -> tuple[list[Finding], Optional[LayerSkip], list[str]]:
    notes: list[str] = []
    if not slither_available():
        return [], LayerSkip(layer="L2", reason="slither CLI not on PATH"), notes
    if not (source or "").strip() and not (source_dir and source_dir.exists()):
        return [], LayerSkip(layer="L2", reason="no Solidity source for Slither"), notes

    def _invoke(target: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["slither", target, "--json", "-", "--disable-color"],
            capture_output=True, text=True, timeout=timeout_s, check=False,
        )

    try:
        if source_dir and source_dir.exists():
            proc = _invoke(str(source_dir))
        else:
            with tempfile.TemporaryDirectory(prefix="eth-scanner-research-slither-") as tmp:
                p = Path(tmp) / "Contract.sol"
                p.write_text(source, encoding="utf-8")
                proc = _invoke(str(p))
    except subprocess.TimeoutExpired:
        return [], LayerSkip(layer="L2", reason="slither timed out after %ss" % timeout_s), notes
    except OSError as exc:
        return [], LayerSkip(layer="L2", reason="slither failed to start: %s" % exc), notes

    raw = (proc.stdout or "").strip() or (proc.stderr or "").strip()
    payload: Any = None
    if raw:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            # Slither sometimes prints logs then JSON — take the last object.
            start = raw.rfind("{")
            if start >= 0:
                try:
                    payload = json.loads(raw[start:])
                except json.JSONDecodeError:
                    payload = None
    if payload is None:
        notes.append("slither exited %s without parseable JSON" % proc.returncode)
        return [], LayerSkip(layer="L2", reason="slither produced no JSON (solc missing or compile failed)"), notes
    findings = parse_slither_json(payload, address=address)
    notes.append("slither ran; %d allowlisted detector row(s)" % len(findings))
    return findings, None, notes
