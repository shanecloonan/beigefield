"""Heimdall, Panoramix, and Wake inside the deep scan.

Detector names and decompile notes are evidence. They are marked generic so
they do not add heat. A missing binary is a skipped engine, not a failed scan.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

from eth_scanner.deep.findings import EngineFinding, make_finding
from eth_scanner.deep.runners import EngineRunResult
from eth_scanner.decompile.heimdall import decompile_unverified_funded
from eth_scanner.engines.wake_runner import parse_wake, wake_rule


def wake_bin() -> Optional[str]:
    override = (os.environ.get("ETH_SCANNER_WAKE_BIN") or "").strip()
    if override and Path(override).is_file():
        return override
    return shutil.which("wake")


def heimdall_bin() -> Optional[str]:
    override = (os.environ.get("ETH_SCANNER_HEIMDALL_BIN") or "").strip()
    if override and Path(override).is_file():
        return override
    return shutil.which("heimdall")


def panoramix_bin() -> Optional[str]:
    override = (os.environ.get("ETH_SCANNER_PANORAMIX_BIN") or "").strip()
    if override and Path(override).is_file():
        return override
    return shutil.which("panoramix")


def run_wake_project(project: str, *, timeout_s: int = 40) -> EngineRunResult:
    exe = wake_bin()
    if not exe:
        return EngineRunResult("wake", "skipped", note="wake not on PATH")
    try:
        proc = subprocess.run(
            [exe, "detect", "--export", "json", "--ignore-errors", "all", project],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return EngineRunResult("wake", "error", note="timed out after %ss" % timeout_s)
    except OSError as exc:
        return EngineRunResult("wake", "error", note=str(exc)[:200])
    raw = _wake_export(project, proc.stdout or "")
    findings = _wake_findings(raw)
    return EngineRunResult(
        "wake",
        "ok",
        findings=findings,
        note="exit=%s detections=%d" % (proc.returncode, len(findings)),
    )


def _wake_export(project: str, stdout: str) -> str:
    path = Path(project) / ".wake" / "detections.json"
    if path.is_file():
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            pass
    return stdout


def run_unverified_decompile(
    address: str,
    bytecode: str,
    funds_usd: Optional[float],
    *,
    verified: bool = False,
) -> EngineRunResult:
    """Run Heimdall, then Panoramix, for an unverified funded contract."""
    if verified:
        return EngineRunResult("decompile", "skipped", note="verified source is kept")
    if not heimdall_bin() and not panoramix_bin():
        return EngineRunResult("decompile", "skipped", note="heimdall and panoramix are not installed")
    report = decompile_unverified_funded(
        address,
        funds_usd=funds_usd,
        verified=False,
        bytecode=bytecode or "",
    )
    if report.get("skipped") == "unfunded":
        return EngineRunResult("decompile", "skipped", note=str(report.get("note") or "below the funds floor"))
    if report.get("tool") in {None, "none"}:
        return EngineRunResult("decompile", "error", note=str(report.get("note") or "decompile produced nothing"))
    finding = make_finding(
        engine="decompile",
        rule=str(report["tool"]),
        title="decompiled with %s" % report["tool"],
        severity="info",
        confidence="low",
        evidence="src_confidence=low chars=%d" % len(report.get("content") or ""),
    )
    finding.generic = True
    return EngineRunResult(
        "decompile",
        "ok",
        findings=[finding],
        note=str(report.get("note") or ""),
    )


def _wake_findings(raw: str) -> list[EngineFinding]:
    findings: list[EngineFinding] = []
    for row in parse_wake(raw):
        rule = wake_rule(row["detector"], row["impact"])
        finding = make_finding(
            engine="wake",
            rule=rule,
            title=rule,
            severity=row["impact"],
            confidence=row["confidence"],
            evidence="impact=%s confidence=%s" % (row["impact"], row["confidence"]),
        )
        finding.generic = True
        findings.append(finding)
    return findings


def added_availability() -> dict[str, bool]:
    return {
        "wake": bool(wake_bin()),
        "heimdall": bool(heimdall_bin()),
        "panoramix": bool(panoramix_bin()),
    }


def engine_run_row(result: EngineRunResult) -> dict[str, Any]:
    return {
        "engine": result.engine,
        "status": result.status,
        "note": result.note,
        "duration_ms": result.duration_ms,
        "finding_count": len(result.findings),
    }
