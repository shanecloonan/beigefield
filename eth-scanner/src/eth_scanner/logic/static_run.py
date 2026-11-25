"""Run Slither, Aderyn, Semgrep, Wake, and Pyrometer on one verified source tree.

Each engine has its own timeout. A missing binary is a skip, not a failure.
Semgrep uses the local rules file unless ETH_SCANNER_SEMGREP_RULES is set.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Optional

from eth_scanner.logic.static_norm import score_static

EngineFn = Callable[[str, int], list[Any]]


def builtin_rules_path() -> str:
    override = (os.environ.get("ETH_SCANNER_SEMGREP_RULES") or "").strip()
    if override:
        return override
    return str(Path(__file__).resolve().parents[3] / "research" / "semgrep" / "solidity.yml")


def local_semgrep_argv(bin_path: str, project_dir: str, rules_path: str) -> list[str]:
    """Offline rules only. No registry download and no autofix."""
    return [
        bin_path,
        "--metrics=off",
        "--disable-version-check",
        "--quiet",
        "--json",
        "--error",
        "--config",
        rules_path,
        project_dir,
    ]


def _engine_view(result: Any) -> dict[str, Any]:
    return {
        "engine": str(getattr(result, "engine", "") or ""),
        "status": str(getattr(result, "status", "") or ""),
        "note": str(getattr(result, "note", "") or "")[:240],
        "findings": len(getattr(result, "findings", []) or []),
        "duration_ms": int(getattr(result, "duration_ms", 0) or 0),
    }


def default_engines(source: str, timeout_s: int) -> list[Any]:
    """Real binaries. Skips whatever is not installed."""
    from eth_scanner.deep.runners import (
        _parse_semgrep,
        _write_source_tree,
        run_aderyn,
        run_slither,
        semgrep_bin,
    )
    from eth_scanner.deep.runners import EngineRunResult

    from eth_scanner.deep.added_engines import _wake_findings
    from eth_scanner.engines.pyrometer_runner import as_static_findings, run_pyrometer
    from eth_scanner.engines.wake_runner import run_wake
    import json as _json

    wake = run_wake(source, timeout_s=min(25, timeout_s))
    wake_findings = []
    if wake.get("status") == "ok":
        wake_findings = _wake_findings(_json.dumps({"detections": wake.get("detections") or []}))
    runs = [
        run_slither(source, timeout_s=timeout_s),
        run_aderyn(source, timeout_s=timeout_s),
        EngineRunResult(
            "wake",
            str(wake.get("status") or "skipped"),
            findings=wake_findings,
            note=str(wake.get("note") or "")[:240],
        ),
    ]
    pyro = run_pyrometer(source, timeout_s=min(20, timeout_s))
    runs.append(EngineRunResult(
        "pyrometer",
        str(pyro.get("status") or "skipped"),
        findings=as_static_findings(pyro),
        note=str(pyro.get("note") or "")[:240],
    ))
    rules = builtin_rules_path()
    bin_path = semgrep_bin()
    if not bin_path:
        runs.append(EngineRunResult("semgrep", "skipped", note="semgrep not on PATH"))
        return runs
    if not Path(rules).is_file():
        runs.append(EngineRunResult("semgrep", "skipped", note="semgrep rules file missing"))
        return runs
    import time
    started = time.time()
    try:
        with _write_source_tree(source) as tmp:
            proc = subprocess.run(
                local_semgrep_argv(bin_path, tmp, rules),
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
    except subprocess.TimeoutExpired:
        runs.append(EngineRunResult("semgrep", "error", note="timed out after %ss" % timeout_s))
        return runs
    except OSError as exc:
        runs.append(EngineRunResult("semgrep", "error", note=str(exc)[:200]))
        return runs
    findings = _parse_semgrep((proc.stdout or "") or (proc.stderr or ""))
    runs.append(EngineRunResult(
        "semgrep",
        "ok",
        findings=findings,
        note="exit=%s findings=%d" % (proc.returncode, len(findings)),
        duration_ms=int((time.time() - started) * 1000),
    ))
    return runs


def analyze_source(
    source: str,
    *,
    timeout_s: int = 60,
    engines_fn: Optional[EngineFn] = None,
) -> dict[str, Any]:
    """Normalize one contract. `engines_fn` is a test seam."""
    timeout = max(5, min(180, int(timeout_s)))
    text = source or ""
    if not text.strip():
        return {
            "engines": [],
            "findings": [],
            "static_evidence": 0,
            "note": "no source",
        }
    runner = engines_fn or default_engines
    try:
        runs = list(runner(text, timeout))
    except Exception as exc:  # noqa: BLE001 — one engine crash must not kill the scan
        return {
            "engines": [{"engine": "static", "status": "error", "note": type(exc).__name__, "findings": 0}],
            "findings": [],
            "static_evidence": 0,
            "note": "static engines failed (%s)" % type(exc).__name__,
        }
    raw: list[Any] = []
    engines = []
    for run in runs:
        engines.append(_engine_view(run))
        raw.extend(list(getattr(run, "findings", []) or []))
    scored = score_static(raw)
    return {
        "engines": engines,
        "findings": scored["rows"],
        "static_evidence": scored["points"],
        "static_high": scored["high"],
        "static_medium": scored["medium"],
        "static_ignored": scored["ignored"],
        "note": "",
    }


def _etherscan_getter() -> Optional[Callable[[str], Any]]:
    """Bound get_source when keys are configured. The key stays inside the client."""
    from eth_scanner.config import load_settings
    from eth_scanner.ingest.etherscan import EtherscanClient

    keys = list(getattr(load_settings(), "etherscan_api_keys", None) or [])
    if not keys:
        return None
    return EtherscanClient(keys).get_source


def run_static_command(
    *,
    address: str = "",
    source: str = "",
    timeout_s: int = 60,
    cache_dir: Optional[Path] = None,
    store: Any = None,
    engines_fn: Optional[EngineFn] = None,
    etherscan_get: Optional[Callable[[str], Any]] = None,
    fetch_json: Optional[Callable[[str], Any]] = None,
) -> dict[str, Any]:
    """Fetch (unless source is local), analyze, and store. No chain writes."""
    from eth_scanner.heat import evidence_heat
    from eth_scanner.logic.source_fetch import fetch_verified_source

    text = source or ""
    fetched: dict[str, Any] = {}
    if not text.strip() and address:
        fetched = fetch_verified_source(
            address,
            cache_dir=cache_dir,
            fetch_json=fetch_json,
            etherscan_get=etherscan_get if etherscan_get is not None else _etherscan_getter(),
        )
        text = str(fetched.get("source") or "")
    report = analyze_source(text, timeout_s=timeout_s, engines_fn=engines_fn)
    report["address"] = address
    report["source_via"] = fetched.get("via") or ("local" if source.strip() else "")
    report["verified"] = bool(text.strip())
    report["cached"] = bool(fetched.get("cached"))
    report["fetch_note"] = fetched.get("note") or ""
    report["metadata"] = fetched.get("metadata") or {}
    report["storage_layout"] = list(fetched.get("storage_layout") or [])
    wake_ran = any(
        row.get("engine") == "wake" and row.get("status") == "ok"
        for row in report["engines"]
    )
    pyrometer_ran = any(
        row.get("engine") == "pyrometer" and row.get("status") == "ok"
        for row in report["engines"]
    )
    heat, breakdown = evidence_heat(
        funds_usd=None,
        invariant_results=[],
        static_findings=report["findings"],
        source_record=fetched or None,
        wake={"ran": True} if wake_ran else None,
        pyrometer={"ran": True} if pyrometer_ran else None,
    )
    report["heat"] = heat
    report["heat_breakdown"] = {
        "static_evidence": breakdown.get("static_evidence", 0),
        "wake": breakdown.get("wake", False),
        "pyrometer": breakdown.get("pyrometer", False),
        "storage_layout": breakdown.get("storage_layout", False),
        "storage_slots": breakdown.get("storage_slots", 0),
        "source_metadata": breakdown.get("source_metadata", False),
        "compiler": breakdown.get("compiler") or "",
        "total": breakdown.get("total", 0),
    }
    if breakdown.get("static_findings"):
        report["heat_breakdown"]["static_findings"] = breakdown["static_findings"]
    save = getattr(store, "save_static_findings", None) if store is not None else None
    if address and callable(save):
        report["store"] = save(address, report["findings"])
    else:
        report["store"] = {"persisted": False, "saved": 0, "degraded": False}
    return report


def clamp_timeout(raw: Optional[int], default: int = 60) -> int:
    try:
        value = int(raw if raw is not None else default)
    except (TypeError, ValueError):
        value = default
    return max(5, min(180, value))
