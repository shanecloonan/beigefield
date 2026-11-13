"""Time-boxed Halmos symbolic checks on lead contracts.

Reuses the same LiveProperties harness as Medusa/Foundry (check_* entrypoints).
Counterexamples → failed_invariant + eth_scan_artifacts kind=symbolic.
Hard timeout; missing binary / compile failure → skip (never blocks queue).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from eth_scanner.engines.fuzz_harness import properties_for_class, write_live_fuzz_project
from eth_scanner.engines.fuzz_runner import forge_bin, _forge_build, _scrub_env

_FAIL_RX = re.compile(
    r"\[FAIL[^\]]*\]\s*(check_\w+)|Counterexample[^\n]{0,200}|AssertionError[^\n]{0,120}",
    re.I,
)


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
    status: str = "skipped"  # ok | failed | error | skipped | timeout | compile-skip
    properties_checked: int = 0
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
            "status": self.status,
            "properties_checked": self.properties_checked,
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

    base = Path(work_dir) if work_dir else Path(tempfile.gettempdir())
    dest = base / "engine-halmos" / (address.lower()[-16:] or "target")
    try:
        project, props = write_live_fuzz_project(
            dest,
            address=address,
            contract_class=contract_class,
            contract_name=contract_name,
        )
        report.property_ids = props
        report.properties_checked = len(props)
    except Exception as exc:  # noqa: BLE001
        report.status = "error"
        report.notes.append("halmos harness write failed: %s" % str(exc)[:160])
        report.duration_ms = int((time.monotonic() - t0) * 1000)
        return report

    compile_budget = min(25, max(10, budget // 4))
    compiled, compile_note = _forge_build(project, timeout_s=compile_budget)
    report.notes.append(compile_note)
    if not compiled:
        report.status = "compile-skip"
        report.notes.append("halmos skipped — harness compile failed")
        report.duration_ms = int((time.monotonic() - t0) * 1000)
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
        # Halmos/forge fork via foundry.toml rpc_endpoints when set.
        try:
            toml = (project / "foundry.toml").read_text(encoding="utf-8")
            if "[rpc_endpoints]" not in toml:
                with (project / "foundry.toml").open("a", encoding="utf-8") as fh:
                    fh.write('\n[rpc_endpoints]\nmainnet = "%s"\n' % rpc_url.replace('"', ""))
        except OSError:
            pass

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
    if report.failures:
        report.status = "failed"
    elif proc.returncode not in (0, None):
        low = blob.lower()
        if "compil" in low or "error:" in low[:400]:
            report.status = "compile-skip"
            report.notes.append("halmos compile/infra failure — no heat")
        else:
            report.status = "error"
            report.notes.append("halmos exit=%s with no parsed counterexamples" % proc.returncode)
    else:
        report.status = "ok"
    report.notes.append(
        "halmos exit=%s props=%d failures=%d"
        % (proc.returncode, report.properties_checked, report.failure_count)
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
    low = text.lower()
    if any(tok in low for tok in ("failed to compile", "compilation failed", "solc error")):
        report.notes.append("halmos compile noise — ignoring as property failure")
        return
    for m in _FAIL_RX.finditer(text):
        prop = m.group(1) or "halmos_property"
        if prop.startswith("check_"):
            prop = prop[len("check_"):]
        for pid in report.property_ids:
            if pid.lower() in prop.lower().replace("-", "_"):
                prop = pid
                break
        snippet = re.sub(r"\s+", " ", m.group(0))[:400]
        report.failures.append(SymbolicFailure(
            property_id=prop,
            reproduction=snippet,
            evidence="halmos counterexample: %s" % snippet[:280],
        ))
        if len(report.failures) >= 8:
            break


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
        "address": address.lower(),
        "contract_class": contract_class,
        "contract_name": contract_name,
        "properties_checked": report.properties_checked,
        "property_ids": list(report.property_ids),
        "failures": [f.to_dict() for f in report.failures],
        "duration_ms": report.duration_ms,
        "notes": list(report.notes)[:12],
    }
