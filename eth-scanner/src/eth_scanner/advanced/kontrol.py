"""Time-boxed Kontrol. A missing binary is a skip and adds no heat.

Kontrol is not installed by the scanner. When the binary is absent the
deep pass records a skip. A run that does start is capped and its output
stays a generic lead.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

from eth_scanner.deep.findings import make_finding
from eth_scanner.deep.runners import EngineRunResult


def kontrol_bin() -> Optional[str]:
    override = (os.environ.get("ETH_SCANNER_KONTROL_BIN") or "").strip()
    if override and Path(override).is_file():
        return override
    return shutil.which("kontrol")


def run_kontrol(project: str, *, timeout_s: int = 30) -> EngineRunResult:
    exe = kontrol_bin()
    if not exe:
        return EngineRunResult("kontrol", "skipped", note="kontrol not on PATH")
    root = Path(project)
    if not (root / "foundry.toml").is_file():
        return EngineRunResult("kontrol", "skipped", note="no foundry.toml for kontrol")
    t0 = time.time()
    try:
        proc = subprocess.run(
            [exe, "prove", "--max-depth", "1"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return EngineRunResult(
            "kontrol",
            "error",
            note="timed out after %ss" % timeout_s,
            duration_ms=int((time.time() - t0) * 1000),
        )
    except OSError as exc:
        return EngineRunResult("kontrol", "error", note=str(exc)[:200])
    raw = ((proc.stdout or "") + "\n" + (proc.stderr or "")).lower()
    findings = []
    if "failed" in raw and "prov" in raw:
        finding = make_finding(
            engine="kontrol",
            rule="prove",
            title="kontrol reported a local proof failure",
            severity="info",
            confidence="low",
            evidence="kontrol local failure; no caller profit",
        )
        finding.generic = True
        findings.append(finding)
    return EngineRunResult(
        "kontrol",
        "ok",
        findings=findings,
        note="exit=%s" % proc.returncode,
        duration_ms=int((time.time() - t0) * 1000),
    )
