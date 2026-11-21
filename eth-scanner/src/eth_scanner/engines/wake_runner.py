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
