"""Echidna property fuzzing for the deep lane.

Same conservation harness and the same heat rule as Medusa: a failed
property is evidence, and heat moves only when the log shows
caller_profit_delta greater than zero. Compile and setUp failures are skips.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from eth_scanner.deep.findings import EngineFinding, make_finding, sanitize_evidence
from eth_scanner.deep.runners import EngineRunResult, echidna_bin

_NOISE = (
    "setup()",
    "setup failed",
    "failed to compile",
    "compilation failed",
    "could not compile",
    "constructor",
)
_PROFIT_PROPS = (
    "no_caller_profit",
    "no_third_party_balance_drop",
    "profit-free-value",
    "profit_free_value",
)
_FAIL_RX = re.compile(r"([A-Za-z0-9_]+):\s*failed!?", re.I)
_DELTA_RX = re.compile(r"caller_profit_delta[=:](\d+)")


def parse_echidna_output(text: str) -> list[dict[str, Any]]:
    blob = text or ""
    low = blob.lower()
    if any(tok in low for tok in _NOISE) and "caller_profit_delta" not in low:
        return []
    delta_match = _DELTA_RX.search(blob)
    delta = int(delta_match.group(1)) if delta_match else 0
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name in _FAIL_RX.findall(blob):
        prop = name.strip()
        key = prop.lower()
        if not prop or key in seen or any(tok in key for tok in ("setup", "constructor", "compil")):
            continue
        seen.add(key)
        profit = delta > 0 and any(p in key for p in _PROFIT_PROPS)
        rows.append({
            "rule": prop,
            "caller_profit": profit,
            "attacker_delta": delta if profit else 0,
            "evidence": sanitize_evidence(
                "property %s; caller_profit_delta=%s" % (prop, delta if profit else 0)
            ),
        })
    return rows


def findings_from_echidna(text: str) -> list[EngineFinding]:
    out: list[EngineFinding] = []
    for row in parse_echidna_output(text):
        finding = make_finding(
            engine="echidna",
            rule=str(row["rule"]),
            title=(
                "Fork conservation counterexample: caller balance rose"
                if row["caller_profit"]
                else "Echidna property failure (evidence only)"
            ),
            severity="high" if row["caller_profit"] else "info",
            confidence="high" if row["caller_profit"] else "low",
            evidence=row["evidence"],
            class_hint="invariant-violation",
        )
        finding.generic = not row["caller_profit"]
        out.append(finding)
    return out


def run_echidna(*, suite_dir, timeout_s: int = 90) -> EngineRunResult:
    root = Path(suite_dir)
    bin_path = echidna_bin()
    if not bin_path:
        return EngineRunResult("echidna", "skipped", note="echidna not on PATH")
    config = root / "echidna.yaml"
    if not config.is_file():
        return EngineRunResult("echidna", "skipped", note="echidna.yaml missing")
    contract = root / "echidna" / "VaultProperties.sol"
    target = str(contract if contract.is_file() else root)
    t0 = time.time()
    import subprocess
    try:
        proc = subprocess.run(
            [bin_path, target, "--config", str(config)],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return EngineRunResult("echidna", "error", note="timed out after %ss" % timeout_s)
    except OSError as exc:
        return EngineRunResult("echidna", "error", note=str(exc)[:160])
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    low = text.lower()
    if any(tok in low for tok in ("failed to compile", "compilation failed", "could not compile")):
        return EngineRunResult(
            "echidna", "skipped",
            note="compile skipped — not a property failure",
            duration_ms=int((time.time() - t0) * 1000),
        )
    findings = findings_from_echidna(text)
    return EngineRunResult(
        "echidna", "ok", findings=findings,
        note="exit=%s properties=%d" % (proc.returncode, len(findings)),
        duration_ms=int((time.time() - t0) * 1000),
    )
