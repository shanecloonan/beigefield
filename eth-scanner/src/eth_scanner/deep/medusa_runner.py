"""Medusa invariant fuzzing for the deep lane.

Medusa only calls the public functions of the existing conservation harness.
A compile error or a setUp crash is a skip. A property failure is evidence.
Heat moves only when the log shows the caller’s balance rose
(caller_profit_delta). Nothing is broadcast, and calldata is not stored.
"""

from __future__ import annotations

import re
import time
from typing import Any

from eth_scanner.deep.findings import EngineFinding, make_finding, sanitize_evidence
from eth_scanner.deep.runners import EngineRunResult, medusa_bin

_NOISE = (
    "setup()",
    "setup failed",
    "failed to compile",
    "compilation failed",
    "could not compile",
    "constructor",
    "crytic-compile",
)
_PROFIT_PROPS = (
    "no_third_party_balance_drop",
    "profit-free-value",
    "profit_free_value",
)
_FAIL_RX = re.compile(
    r"(?:\[FAIL[^\]]*\]|property failed:|Assertion (?:Failed|failed):?)\s*([A-Za-z0-9_]+)",
    re.I,
)
_DELTA_RX = re.compile(r"caller_profit_delta[=:](\d+)")


def parse_medusa_output(text: str) -> list[dict[str, Any]]:
    """Turn Medusa stdout into evidence rows. Noise is dropped."""
    blob = text or ""
    low = blob.lower()
    if any(tok in low for tok in _NOISE) and "caller_profit_delta" not in low:
        return []
    rows: list[dict[str, Any]] = []
    names = _FAIL_RX.findall(blob) or []
    delta_match = _DELTA_RX.search(blob)
    delta = int(delta_match.group(1)) if delta_match else 0
    if not names and delta > 0:
        names = ["no_third_party_balance_drop"]
    seen: set[str] = set()
    for name in names:
        prop = name.strip()
        key = prop.lower()
        if not prop or key in seen:
            continue
        if any(tok in key for tok in ("setup", "constructor", "compil")):
            continue
        seen.add(key)
        profit = delta > 0 and any(p in key or key in p for p in _PROFIT_PROPS)
        rows.append({
            "rule": prop,
            "caller_profit": profit,
            "attacker_delta": delta if profit else 0,
            "evidence": sanitize_evidence(
                "property %s; caller_profit_delta=%s" % (prop, delta if profit else 0)
            ),
        })
    return rows


def findings_from_medusa(text: str) -> list[EngineFinding]:
    out: list[EngineFinding] = []
    for row in parse_medusa_output(text):
        finding = make_finding(
            engine="medusa",
            rule=str(row["rule"]),
            title=(
                "Fork conservation counterexample: caller balance rose"
                if row["caller_profit"]
                else "Medusa property failure (evidence only)"
            ),
            severity="high" if row["caller_profit"] else "info",
            confidence="high" if row["caller_profit"] else "low",
            evidence=row["evidence"],
            class_hint="invariant-violation",
        )
        finding.generic = not row["caller_profit"]
        out.append(finding)
    return out


def fork_profit_results(findings: list[Any]) -> list[dict[str, Any]]:
    """Invariant rows for a proven caller-profit counterexample. Nothing else."""
    rows: list[dict[str, Any]] = []
    for finding in findings:
        data = finding.to_dict() if hasattr(finding, "to_dict") else dict(finding)
        if str(data.get("engine") or "").lower() != "medusa":
            continue
        evidence = str(data.get("evidence") or "")
        match = _DELTA_RX.search(evidence)
        if not match or int(match.group(1)) <= 0:
            continue
        rule = str(data.get("rule") or "")
        if not any(p in rule.lower() for p in _PROFIT_PROPS):
            continue
        rows.append({
            "id": "profit-free-value",
            "status": "failed",
            "source": "fork-simulation",
            "attacker_delta": int(match.group(1)),
            "evidence": "caller balance rose on a fork conservation check (%s)" % rule,
        })
    return rows


def run_medusa(
    *,
    suite_dir,
    timeout_s: int = 90,
) -> EngineRunResult:
    """Run `medusa fuzz` when the binary and medusa.json are present."""
    from pathlib import Path
    import subprocess
    root = Path(suite_dir)
    bin_path = medusa_bin()
    if not bin_path:
        return EngineRunResult("medusa", "skipped", note="medusa not on PATH")
    if not (root / "medusa.json").is_file():
        return EngineRunResult("medusa", "skipped", note="medusa.json missing")
    t0 = time.time()
    try:
        proc = subprocess.run(
            [bin_path, "fuzz"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return EngineRunResult("medusa", "error", note="timed out after %ss" % timeout_s)
    except OSError as exc:
        return EngineRunResult("medusa", "error", note=str(exc)[:160])
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    low = text.lower()
    if any(tok in low for tok in ("failed to compile", "compilation failed", "could not compile")):
        return EngineRunResult(
            "medusa", "skipped",
            note="compile skipped — not a property failure",
            duration_ms=int((time.time() - t0) * 1000),
        )
    findings = findings_from_medusa(text)
    return EngineRunResult(
        "medusa", "ok", findings=findings,
        note="exit=%s properties=%d" % (proc.returncode, len(findings)),
        duration_ms=int((time.time() - t0) * 1000),
    )
