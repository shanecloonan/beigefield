"""Certora Prover as an external CLI.

The prover is GPL-3.0. This module does not import it, vendor it, or link
it. It writes a config that points at our own CVL specs and, when
``certoraRun`` is on PATH, runs that unmodified binary. A missing binary
is a skip. A violated rule is heat. The counterexample is the rule name,
with long hex removed.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Optional

PIN = {
    "url": "https://github.com/Certora/CertoraProver",
    "license": "GPL-3.0",
    "link": False,
}
DEFAULT_TIMEOUT_S = 120
_KINDS = {"erc20": "ERC20.spec", "erc4626": "ERC4626.spec"}
_VIOLATED = re.compile(
    r"(?:rule\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*(?:-|:)\s*violated\b",
    re.IGNORECASE,
)
_HEX = re.compile(r"0x[0-9a-fA-F]{8,}")
Runner = Callable[[list[str], Path, int], tuple[int, str]]


def spec_path(kind: str) -> Optional[Path]:
    name = _KINDS.get((kind or "").strip().lower())
    if not name:
        return None
    path = Path(__file__).resolve().parent / "specs" / name
    return path if path.is_file() else None


def certora_bin() -> Optional[str]:
    override = (os.environ.get("ETH_SCANNER_CERTORA_BIN") or "").strip()
    if override and Path(override).is_file():
        return override
    return shutil.which("certoraRun")


def parse_violations(text: str) -> list[dict[str, str]]:
    """Rule names only. Drop calldata and other long hex."""
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in _VIOLATED.finditer(text or ""):
        name = match.group(1)[:80]
        if name.lower() in {"rule", "the"} or name in seen:
            continue
        seen.add(name)
        rows.append({
            "id": name,
            "status": "violated",
            "summary": "rule %s violated" % name,
        })
        if len(rows) >= 8:
            break
    return rows


def _clamp(timeout_s: int) -> int:
    try:
        value = int(timeout_s)
    except (TypeError, ValueError):
        value = DEFAULT_TIMEOUT_S
    return max(30, min(180, value))


def _address(value: str) -> str:
    raw = (value or "").strip().lower()
    if raw.startswith("0x"):
        raw = raw[2:]
    if len(raw) != 40 or any(ch not in "0123456789abcdef" for ch in raw):
        raise ValueError("address")
    return "0x" + raw


def _default_runner(argv: list[str], cwd: Path, timeout: int) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    return proc.returncode, _HEX.sub("0x…", text)[:4000]


def run_certora(
    *,
    address: str,
    source: str = "",
    kind: str = "",
    on_shortlist: bool = False,
    verified: bool = False,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    dest: Optional[Path] = None,
    output: Optional[str] = None,
    runner: Optional[Runner] = None,
) -> dict[str, Any]:
    """Run the external prover on one verified shortlist contract."""
    from eth_scanner.heat import evidence_heat

    report: dict[str, Any] = {
        "status": "skipped",
        "address": "",
        "kind": (kind or "").strip().lower(),
        "ran": False,
        "violated": [],
        "heat": 0,
        "heat_contribution": 0,
        "pin": dict(PIN),
        "note": "",
    }
    try:
        report["address"] = _address(address)
    except ValueError:
        report["status"] = "invalid"
        report["note"] = "Address is not 20 bytes of hex."
        return report
    if not on_shortlist:
        report["note"] = "Certora runs only for a shortlist contract."
        return report
    if not verified:
        report["note"] = "Certora runs only on verified source."
        return report
    spec = spec_path(report["kind"])
    if spec is None:
        report["note"] = "Kind must be erc20 or erc4626."
        return report
    if not (source or "").strip():
        report["note"] = "Verified source is required."
        return report

    budget = _clamp(timeout_s)
    text = output
    if text is None:
        binary = certora_bin()
        if binary is None and runner is None:
            report["note"] = "certoraRun is not installed. The check was not run."
            return report
        work = Path(dest) if dest is not None else Path(os.environ.get("TMPDIR") or "/tmp") / "certora-check"
        work.mkdir(parents=True, exist_ok=True)
        src = work / "Target.sol"
        src.write_text(source, encoding="utf-8")
        conf = {
            "files": [str(src.resolve())],
            "verify": "Target:%s" % spec.resolve(),
            "wait_for_results": "all",
            "rule_sanity": "basic",
        }
        (work / "run.conf").write_text(json.dumps(conf, indent=2) + "\n", encoding="utf-8")
        code, text = (runner or _default_runner)(
            [binary or "certoraRun", str(work / "run.conf")],
            work,
            budget,
        )
        report["exit_code"] = code
    violations = parse_violations(text or "")
    report["ran"] = True
    report["violated"] = violations
    report["status"] = "violated" if violations else "held"
    report["note"] = (
        "A violated rule is heat. The summary is the rule name."
        if violations
        else "The Certora rules held."
    )
    heat, breakdown = evidence_heat(
        funds_usd=None,
        invariant_results=[],
        certora=report,
    )
    report["heat"] = heat
    report["heat_breakdown"] = {
        "certora": breakdown.get("certora"),
        "certora_evidence": breakdown.get("certora_evidence"),
        "total": breakdown.get("total"),
    }
    return report
