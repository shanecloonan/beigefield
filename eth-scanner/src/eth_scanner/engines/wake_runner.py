"""Ackee Wake detectors. Names only, and they add no heat.

``wake detect all --export json`` runs when the binary is already installed.
Source snippets from the JSON, and any non-JSON output, are dropped. A missing
binary, a timeout, or a crash leaves an empty lead list.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional

_IMPACT = {"info", "warning", "low", "medium", "high"}
_CONFIDENCE = {"low", "medium", "high"}


def run_wake(
    source: str,
    *,
    runner: Optional[Callable[[str], str]] = None,
    which: Optional[Callable[[str], Optional[str]]] = None,
    timeout_s: int = 25,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "engine": "wake",
        "evidence_only": True,
        "heat_contribution": 0,
        "status": "skipped",
        "detections": [],
        "note": "wake is not installed. Detectors were not run.",
    }
    located = which("wake") if which is not None else _wake_bin()
    if runner is None and not located:
        return report
    try:
        raw = runner(source) if runner is not None else _run_cli(source, timeout_s=timeout_s)
    except subprocess.TimeoutExpired:
        report["status"] = "error"
        report["note"] = "wake timed out. No detections were kept."
        return report
    except Exception as exc:  # noqa: BLE001 — a detector crash is not a scan failure
        report["status"] = "error"
        report["note"] = "wake failed (%s). No detections were kept." % type(exc).__name__
        return report
    report["detections"] = parse_wake(raw)
    report["status"] = "ok"
    report["note"] = "Wake detector names are leads and add no heat. Source text was not kept."
    return report


def wake_rule(detector: str, impact: str = "info") -> str:
    """Map a Wake detector onto the static allowlist. Unknown names stay as leads."""
    name = (detector or "").strip().lower().replace("_", "-")
    level = (impact or "info").strip().lower()
    if name == "reentrancy":
        return "reentrancy-eth" if level in {"high", "medium"} else "reentrancy-no-eth"
    if name == "unchecked-return-value":
        return "unchecked-transfer"
    if name == "unsafe-delegatecall":
        return "controlled-delegatecall"
    return name[:80]


def parse_wake(raw: str) -> list[dict[str, Any]]:
    """Keep detector, impact, and confidence. Drop every other field."""
    try:
        data = json.loads(raw or "")
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        items = data.get("detections") or data.get("results") or []
    elif isinstance(data, list):
        items = data
    else:
        return []
    kept: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("detector") or item.get("detector_name") or item.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        impact = str(item.get("impact") or "info").lower()
        confidence = str(item.get("confidence") or "low").lower()
        kept.append({
            "detector": name.strip()[:80],
            "impact": impact if impact in _IMPACT else "info",
            "confidence": confidence if confidence in _CONFIDENCE else "low",
            "heat_contribution": 0,
        })
    return kept


def _wake_bin() -> Optional[str]:
    override = (os.environ.get("ETH_SCANNER_WAKE_BIN") or "").strip()
    if override and Path(override).is_file():
        return override
    return shutil.which("wake")


def _run_cli(source: str, *, timeout_s: int) -> str:
    exe = _wake_bin()
    if not exe:
        raise FileNotFoundError("wake")
    with tempfile.TemporaryDirectory(prefix="eth-scanner-wake-") as tmp:
        path = Path(tmp) / "Target.sol"
        path.write_text(source or "", encoding="utf-8")
        proc = subprocess.run(
            [exe, "detect", "--export", "json", "--ignore-errors", "all", str(path)],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        exported = Path(tmp) / ".wake" / "detections.json"
        if exported.is_file():
            return exported.read_text(encoding="utf-8")
    return proc.stdout or ""


def run_wake_fuzz(
    project: str,
    *,
    on_shortlist: bool = False,
    timeout_s: int = 20,
    runner: Optional[Callable[[list[str], int], tuple[int, str]]] = None,
    which: Optional[Callable[[str], Optional[str]]] = None,
) -> dict[str, Any]:
    """Short Wake test run. Only a project that already has tests, and only on the shortlist.

    The output sequence is not stored. Fuzz output adds no heat.
    """
    report: dict[str, Any] = {
        "engine": "wake",
        "status": "skipped",
        "ran": False,
        "heat": 0,
        "heat_contribution": 0,
        "note": "",
    }
    if not on_shortlist:
        report["note"] = "Wake fuzz runs only for a shortlist contract."
        return report
    root = Path(project or "")
    if not root.is_dir():
        report["note"] = "Wake fuzz needs a local project directory."
        return report
    tests = root / "tests"
    if not tests.is_dir() or not any(tests.glob("test_*.py")):
        report["note"] = "No Wake tests in the project. Fuzz was not run."
        return report
    located = which("wake") if which is not None else _wake_bin()
    if runner is None and not located:
        report["note"] = "wake is not installed. Fuzz was not run."
        return report
    budget = max(10, min(30, int(timeout_s or 20)))
    argv = [located or "wake", "test", "--", "-q", "--maxfail=1", "--tb=no"]
    try:
        code, text = (runner or _fuzz_cli)(argv, budget)
    except subprocess.TimeoutExpired:
        report["status"] = "timeout"
        report["ran"] = True
        report["note"] = "Wake fuzz timed out. No heat."
        return report
    except Exception as exc:  # noqa: BLE001
        report["status"] = "error"
        report["note"] = "Wake fuzz failed (%s). No heat." % type(exc).__name__
        return report
    report["ran"] = True
    failed = code != 0 or "failed" in (text or "").lower()
    report["status"] = "failed" if failed else "ok"
    report["note"] = (
        "Wake fuzz reported a failure. The sequence was not stored."
        if failed
        else "Wake fuzz finished. No heat."
    )
    return report


def _fuzz_cli(argv: list[str], timeout_s: int) -> tuple[int, str]:
    proc = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    return proc.returncode, text[:500]
