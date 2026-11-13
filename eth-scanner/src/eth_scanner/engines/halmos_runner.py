"""Time-boxed Halmos symbolic checks on lead contracts.

Uses the LiveProperties harness with vm.etch (Halmos does not support
createSelectFork). Counterexamples ([FAIL]) → failed_invariant + artifact
kind=symbolic. [ERROR] all-paths-reverted is a property skip, not heat.
Hard timeout; missing binary / true compile failure → campaign skipped.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from eth_scanner.engines.fuzz_harness import (
    detect_solc_version,
    properties_for_class,
    write_live_fuzz_project,
)
from eth_scanner.engines.fuzz_runner import forge_bin, _forge_build, _scrub_env

_PASS_RX = re.compile(r"\[PASS\]\s*(check_\w+)", re.I)
_FAIL_RX = re.compile(r"\[FAIL[^\]]*\]\s*(check_\w+)", re.I)
_ERROR_RX = re.compile(r"\[ERROR\]\s*(check_\w+)", re.I)
_COUNTER_RX = re.compile(r"Counterexample[^\n]{0,240}", re.I)


@dataclass
class SymbolicFailure:
    property_id: str
    reproduction: str
    evidence: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HalmosReport:
    ran: bool = False
    skipped: bool = True
    executed: bool = False  # at least one check_* executed
    status: str = "skipped"  # ok | failed | error | skipped | timeout | compile-skip
    properties_checked: int = 0
    properties_executed: int = 0
    properties_skipped: int = 0
    property_ids: list[str] = field(default_factory=list)
    failures: list[SymbolicFailure] = field(default_factory=list)
    duration_ms: int = 0
    notes: list[str] = field(default_factory=list)
    artifact: dict[str, Any] = field(default_factory=dict)

    @property
    def failure_count(self) -> int:
        return len(self.failures)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ran": self.ran,
            "skipped": self.skipped,
            "executed": self.executed,
            "status": self.status,
            "properties_checked": self.properties_checked,
            "properties_executed": self.properties_executed,
            "properties_skipped": self.properties_skipped,
            "property_ids": list(self.property_ids),
            "failures": [f.to_dict() for f in self.failures],
            "duration_ms": self.duration_ms,
            "notes": list(self.notes),
            "artifact": dict(self.artifact),
        }


def halmos_bin() -> Optional[str]:
    override = (os.environ.get("ETH_SCANNER_HALMOS_BIN") or "").strip()
    if override and Path(override).exists():
        return override
    return shutil.which("halmos")


def run_lead_halmos(
    *,
    address: str,
    contract_class: str,
    contract_name: Optional[str] = None,
    rpc_url: str = "",
    work_dir: Optional[Path] = None,
    timeout_s: int = 90,
    source: str = "",
    compiler: Optional[str] = None,
    runtime_bytecode: str = "",
    source_dir: Optional[Path] = None,
) -> HalmosReport:
    """Symbolic property campaign on leads. Hard wall-clock budget 60–120s."""
    report = HalmosReport()
    t0 = time.monotonic()
    budget = max(60, min(int(timeout_s or 90), 120))
    props = list(properties_for_class(contract_class))
    report.property_ids = props
    report.properties_checked = len(props)

    bin_path = halmos_bin()
    if not bin_path:
        report.notes.append("halmos skipped — not on PATH")
        report.duration_ms = int((time.monotonic() - t0) * 1000)
        return report
    if not forge_bin():
        report.notes.append("halmos skipped — forge required to compile harness")
        report.duration_ms = int((time.monotonic() - t0) * 1000)
        return report

    code = runtime_bytecode or ""
    if not code and rpc_url:
        code = _eth_get_code(rpc_url, address) or ""
        if code:
            report.notes.append("halmos fetched runtime bytecode (%d bytes)" % max(0, (len(code) - 2) // 2))

    solc = detect_solc_version(source=source, compiler=compiler)
    report.notes.append("halmos solc=%s" % solc)

    base = Path(work_dir) if work_dir else Path(tempfile.gettempdir())
    dest = base / "engine-halmos" / (address.lower()[-16:] or "target")
    try:
        project, props = write_live_fuzz_project(
            dest,
            address=address,
            contract_class=contract_class,
            contract_name=contract_name,
            solc_version=solc,
            compiler=compiler,
            source=source,
            runtime_bytecode=code,
            source_dir=source_dir,
            allow_mock_etch=True,  # Halmos cannot new/deployCode
        )
        report.property_ids = props
        report.properties_checked = len(props)
    except Exception as exc:  # noqa: BLE001
        report.status = "error"
        report.notes.append("halmos harness write failed: %s" % str(exc)[:160])
        report.duration_ms = int((time.monotonic() - t0) * 1000)
        return report

    # Ensure solc is available via foundry (auto-download) — give compile room.
    compile_budget = min(35, max(12, budget // 3))
    compiled, compile_note = _forge_build(project, timeout_s=compile_budget)
    report.notes.append(compile_note)
    if not compiled:
        report.status = "compile-skip"
        report.notes.append("halmos skipped — harness compile failed")
        report.duration_ms = int((time.monotonic() - t0) * 1000)
        _finalize_artifact(report, address, contract_class, contract_name, t0)
        return report

    remaining = budget - int(time.monotonic() - t0)
    if remaining < 15:
        report.status = "timeout"
        report.notes.append("halmos skipped — budget exhausted after compile")
        report.duration_ms = int((time.monotonic() - t0) * 1000)
        return report

    report.ran = True
    report.skipped = False
    env = _scrub_env()
    if rpc_url:
        env["ETH_RPC_URL"] = rpc_url

    cmd = [
        bin_path,
        "--function", "check_",
        "--solver-timeout-assertion", "2000",
        "--solver-timeout-branching", "2000",
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(project),
            capture_output=True,
            text=True,
            timeout=remaining,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        blob = ""
        if isinstance(exc.stdout, str):
            blob += exc.stdout
        if isinstance(exc.stderr, str):
            blob += "\n" + exc.stderr
        _ingest(blob, report)
        report.status = "timeout" if not report.failures else "failed"
        report.notes.append("halmos timed out after %ss" % remaining)
        _finalize_artifact(report, address, contract_class, contract_name, t0)
        return report
    except OSError as exc:
        report.status = "error"
        report.notes.append("halmos failed to start: %s" % exc)
        report.duration_ms = int((time.monotonic() - t0) * 1000)
        return report

    blob = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    _ingest(blob, report)

    true_compile = _looks_like_true_compile_failure(blob) and report.properties_executed == 0
    if true_compile:
        report.status = "compile-skip"
        report.executed = False
        report.ran = False
        report.skipped = True
        report.notes.append("halmos true compile/infra failure — no heat")
    elif report.failures:
        report.status = "failed"
    elif report.properties_executed > 0:
        report.status = "ok"
    elif proc.returncode not in (0, None):
        report.status = "error"
        report.notes.append(
            "halmos exit=%s with no executed checks — %s"
            % (proc.returncode, blob[-180:].replace("\n", " ")[:160])
        )
    else:
        report.status = "ok"

    report.notes.append(
        "halmos exit=%s executed=%d skipped_props=%d failures=%d"
        % (
            proc.returncode,
            report.properties_executed,
            report.properties_skipped,
            report.failure_count,
        )
    )
    _finalize_artifact(report, address, contract_class, contract_name, t0)
    return report


def symbolic_failures_as_invariants(report: HalmosReport) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for fail in report.failures:
        out.append({
            "id": "symbolic-%s" % fail.property_id,
            "name": fail.property_id,
            "status": "failed",
            "evidence": fail.evidence[:400],
            "reproduction": fail.reproduction[:800],
            "tool": "halmos",
            "source": "symbolic",
            "label": "proof of a bug, not an attack",
        })
    return out


def symbolic_failures_as_confirmed(report: HalmosReport) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for fail in report.failures:
        out.append({
            "lead_id": "symbolic-%s" % fail.property_id,
            "confirmed": True,
            "method": "symbolic",
            "evidence": (
                "proof of a bug, not an attack | %s | %s"
                % (fail.evidence, fail.reproduction)
            )[:500],
            "extras": {
                "tool": "halmos",
                "property": fail.property_id,
                "reproduction": fail.reproduction[:600],
            },
        })
    return out


def _ingest(blob: str, report: HalmosReport) -> None:
    text = blob or ""
    if not text.strip():
        return

    passed = {_clean_prop(m.group(1), report) for m in _PASS_RX.finditer(text)}
    failed_names = []
    for m in _FAIL_RX.finditer(text):
        prop = _clean_prop(m.group(1), report)
        failed_names.append(prop)
        # Prefer nearby counterexample
        window = text[m.start():m.start() + 500]
        cm = _COUNTER_RX.search(window) or _COUNTER_RX.search(text)
        repro = re.sub(r"\s+", " ", (cm.group(0) if cm else m.group(0)))[:400]
        report.failures.append(SymbolicFailure(
            property_id=prop,
            reproduction=repro,
            evidence="halmos counterexample: %s" % repro[:280],
        ))

    errored = set()
    for m in _ERROR_RX.finditer(text):
        prop = _clean_prop(m.group(1), report)
        errored.add(prop)
        # All-paths-reverted etc. — property skip, not a confirmed bug.
        report.notes.append("halmos property skip: %s (ERROR/restrictive paths)" % prop)

    executed = passed | set(failed_names) | errored
    report.properties_executed = len(executed)
    report.properties_skipped = max(0, report.properties_checked - report.properties_executed)
    report.executed = report.properties_executed > 0
    if len(report.failures) > 8:
        report.failures = report.failures[:8]


def _clean_prop(name: str, report: HalmosReport) -> str:
    prop = (name or "halmos_property").strip()
    if prop.startswith("check_"):
        prop = prop[len("check_"):]
    for pid in report.property_ids:
        if pid.lower() in prop.lower().replace("-", "_"):
            return pid
    return prop


def _looks_like_true_compile_failure(blob: str) -> bool:
    low = (blob or "").lower()
    # Halmos prints [ERROR] for restrictive paths — that is NOT a compile failure.
    if "[pass]" in low or ("[fail" in low and "setup() failed" not in low):
        return False
    markers = (
        "build failed",
        "compiler run failed",
        "failed to compile",
        "compilation failed",
        "solc error",
        "error (9582)",
        "error (1629)",
        "setup() failed",
        "no successful path found in setup",
        "unsupported cheat code",
    )
    return any(m in low for m in markers)


def _eth_get_code(rpc_url: str, address: str, timeout_s: float = 12.0) -> Optional[str]:
    try:
        payload = json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "method": "eth_getCode",
            "params": [address, "latest"],
        }).encode()
        req = urllib.request.Request(
            rpc_url, data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "eth-scanner-halmos/0.2"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
        raw = body.get("result")
        if isinstance(raw, str) and raw not in {"0x", "0x0"} and len(raw) > 4:
            return raw
    except Exception:  # noqa: BLE001
        return None
    return None


def _finalize_artifact(
    report: HalmosReport,
    address: str,
    contract_class: str,
    contract_name: Optional[str],
    t0: float,
) -> None:
    report.duration_ms = int((time.monotonic() - t0) * 1000)
    report.artifact = {
        "kind": "symbolic",
        "label": "proof of a bug, not an attack",
        "tool": "halmos",
        "status": report.status,
        "executed": report.executed,
        "address": address.lower(),
        "contract_class": contract_class,
        "contract_name": contract_name,
        "properties_checked": report.properties_checked,
        "properties_executed": report.properties_executed,
        "properties_skipped": report.properties_skipped,
        "property_ids": list(report.property_ids),
        "failures": [f.to_dict() for f in report.failures],
        "duration_ms": report.duration_ms,
        "notes": list(report.notes)[:12],
    }
