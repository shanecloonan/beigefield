"""Spawn static/symbolic engines. Skip if missing. Never send txs.

Binaries expected from owner forks (or PATH overrides via ETH_SCANNER_*_BIN).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from eth_scanner.deep.findings import EngineFinding, apply_agreement, dedupe_findings
from eth_scanner.deep.parsers import parse_aderyn, parse_halmos, parse_mythril, parse_slither


@dataclass
class EngineRunResult:
    engine: str
    status: str  # ok | skipped | error
    findings: list[EngineFinding] = field(default_factory=list)
    note: str = ""
    duration_ms: int = 0


def _which(env_key: str, names: list[str]) -> Optional[str]:
    override = (os.environ.get(env_key) or "").strip()
    if override and Path(override).exists():
        return override
    for name in names:
        hit = shutil.which(name)
        if hit:
            return hit
    return None


def slither_bin() -> Optional[str]:
    return _which("ETH_SCANNER_SLITHER_BIN", ["slither"])


def aderyn_bin() -> Optional[str]:
    return _which("ETH_SCANNER_ADERYN_BIN", ["aderyn"])


def mythril_bin() -> Optional[str]:
    return _which("ETH_SCANNER_MYTHRIL_BIN", ["myth", "mythril"])


def halmos_bin() -> Optional[str]:
    return _which("ETH_SCANNER_HALMOS_BIN", ["halmos"])


def engine_availability() -> dict[str, bool]:
    return {
        "slither": bool(slither_bin()),
        "aderyn": bool(aderyn_bin()),
        "mythril": bool(mythril_bin()),
        "halmos": bool(halmos_bin()),
    }


def _write_source_tree(source: str, contract_name: str = "Target") -> tempfile.TemporaryDirectory[str]:
    tmp = tempfile.TemporaryDirectory(prefix="eth-scanner-deep-")
    root = Path(tmp.name)
    # Minimal foundry-ish layout so Aderyn can walk it.
    (root / "src").mkdir(parents=True, exist_ok=True)
    sol = root / "src" / ("%s.sol" % (contract_name or "Target"))
    text = source if "pragma solidity" in source else (
        "// SPDX-License-Identifier: UNLICENSED\npragma solidity ^0.8.20;\n" + source
    )
    sol.write_text(text, encoding="utf-8")
    (root / "foundry.toml").write_text(
        '[profile.default]\nsrc = "src"\nout = "out"\nlibs = []\n',
        encoding="utf-8",
    )
    return tmp


def run_slither(source: str, *, timeout_s: int = 90) -> EngineRunResult:
    import time
    bin_path = slither_bin()
    if not bin_path:
        return EngineRunResult("slither", "skipped", note="slither not on PATH")
    t0 = time.time()
    with _write_source_tree(source) as tmp:
        target = str(Path(tmp) / "src")
        try:
            proc = subprocess.run(
                [bin_path, target, "--json", "-", "--disable-color"],
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
                env=_scrub_env(),
            )
        except subprocess.TimeoutExpired:
            return EngineRunResult("slither", "error", note="timed out after %ss" % timeout_s)
        except OSError as exc:
            return EngineRunResult("slither", "error", note=str(exc)[:200])
    raw = (proc.stdout or "") or (proc.stderr or "")
    findings = parse_slither(raw)
    return EngineRunResult(
        "slither",
        "ok",
        findings=findings,
        note="exit=%s findings=%d" % (proc.returncode, len(findings)),
        duration_ms=int((time.time() - t0) * 1000),
    )


def run_aderyn(source: str, *, timeout_s: int = 90) -> EngineRunResult:
    import time
    bin_path = aderyn_bin()
    if not bin_path:
        return EngineRunResult("aderyn", "skipped", note="aderyn not on PATH")
    t0 = time.time()
    with _write_source_tree(source) as tmp:
        out_json = Path(tmp) / "aderyn-report.json"
        try:
            proc = subprocess.run(
                [bin_path, tmp, "--output", str(out_json)],
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
                env=_scrub_env(),
            )
        except subprocess.TimeoutExpired:
            return EngineRunResult("aderyn", "error", note="timed out after %ss" % timeout_s)
        except OSError as exc:
            return EngineRunResult("aderyn", "error", note=str(exc)[:200])
        raw = out_json.read_text(encoding="utf-8") if out_json.exists() else (proc.stdout or "")
    findings = parse_aderyn(raw)
    return EngineRunResult(
        "aderyn",
        "ok",
        findings=findings,
        note="exit=%s findings=%d" % (proc.returncode, len(findings)),
        duration_ms=int((time.time() - t0) * 1000),
    )


def run_mythril(source: str, *, timeout_s: int = 120) -> EngineRunResult:
    import time
    bin_path = mythril_bin()
    if not bin_path:
        return EngineRunResult("mythril", "skipped", note="mythril not on PATH")
    t0 = time.time()
    with _write_source_tree(source) as tmp:
        sol = next((Path(tmp) / "src").glob("*.sol"), None)
        if sol is None:
            return EngineRunResult("mythril", "error", note="no .sol to analyze")
        try:
            proc = subprocess.run(
                [bin_path, "analyze", str(sol), "-o", "json", "--execution-timeout", str(min(60, timeout_s))],
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
                env=_scrub_env(),
            )
        except subprocess.TimeoutExpired:
            return EngineRunResult("mythril", "error", note="timed out after %ss" % timeout_s)
        except OSError as exc:
            return EngineRunResult("mythril", "error", note=str(exc)[:200])
    raw = (proc.stdout or "") or (proc.stderr or "")
    findings = parse_mythril(raw)
    return EngineRunResult(
        "mythril",
        "ok",
        findings=findings,
        note="exit=%s findings=%d" % (proc.returncode, len(findings)),
        duration_ms=int((time.time() - t0) * 1000),
    )


def run_halmos(*, harness_dir: Optional[Path] = None, timeout_s: int = 120) -> EngineRunResult:
    """Halmos needs a Foundry check_* harness — skip unless ETH_SCANNER_HALMOS_HARNESS is set."""
    import time
    bin_path = halmos_bin()
    if not bin_path:
        return EngineRunResult("halmos", "skipped", note="halmos not on PATH")
    root = harness_dir or Path(os.environ.get("ETH_SCANNER_HALMOS_HARNESS") or "")
    if not root or not root.exists():
        return EngineRunResult(
            "halmos",
            "skipped",
            note="no Foundry check_* harness configured (set ETH_SCANNER_HALMOS_HARNESS)",
        )
    t0 = time.time()
    try:
        proc = subprocess.run(
            [bin_path, "test", "--root", str(root)],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            env=_scrub_env(),
            cwd=str(root),
        )
    except subprocess.TimeoutExpired:
        return EngineRunResult("halmos", "error", note="timed out after %ss" % timeout_s)
    except OSError as exc:
        return EngineRunResult("halmos", "error", note=str(exc)[:200])
    raw = (proc.stdout or "") + "\n" + (proc.stderr or "")
    findings = parse_halmos(raw)
    return EngineRunResult(
        "halmos",
        "ok",
        findings=findings,
        note="exit=%s findings=%d" % (proc.returncode, len(findings)),
        duration_ms=int((time.time() - t0) * 1000),
    )


def run_all_engines(
    source: str,
    *,
    engines: Optional[list[str]] = None,
    timeout_s: int = 90,
) -> tuple[list[EngineFinding], list[EngineRunResult]]:
    """Run selected engines; return deduped+agreement findings and per-engine status."""
    wanted = [e.lower() for e in (engines or ["slither", "aderyn", "mythril", "halmos"])]
    results: list[EngineRunResult] = []
    if "slither" in wanted:
        results.append(run_slither(source, timeout_s=timeout_s))
    if "aderyn" in wanted:
        results.append(run_aderyn(source, timeout_s=timeout_s))
    if "mythril" in wanted:
        results.append(run_mythril(source, timeout_s=timeout_s))
    if "halmos" in wanted:
        results.append(run_halmos(timeout_s=timeout_s))

    merged: list[EngineFinding] = []
    for r in results:
        merged.extend(r.findings)
    merged = apply_agreement(dedupe_findings(merged))
    return merged, results


def _scrub_env() -> dict[str, str]:
    """Drop secrets from child env — engines only need PATH/HOME/TMP."""
    keep = {
        "PATH", "HOME", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL", "TERM",
        "USER", "LOGNAME", "SHELL", "XDG_CACHE_HOME", "LOCALAPPDATA",
        "ETH_SCANNER_SLITHER_BIN", "ETH_SCANNER_ADERYN_BIN",
        "ETH_SCANNER_MYTHRIL_BIN", "ETH_SCANNER_HALMOS_BIN",
        "ETH_SCANNER_HALMOS_HARNESS",
    }
    out = {k: v for k, v in os.environ.items() if k in keep}
    out.setdefault("PATH", os.environ.get("PATH", ""))
    return out
