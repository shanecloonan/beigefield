"""Time-boxed Medusa / Foundry fuzz against a local anvil fork.

Strictly defensive: property failures are proof artifacts, never exploits.
Hard wall-clock timeout; compile failures skip without blocking the queue.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from eth_scanner.engines.fuzz_harness import properties_for_class, write_live_fuzz_project
from eth_scanner.research.fuzz import parse_forge_output

_FORGE_SEQ = re.compile(
    r"(?:Sequence|Call sequence|Traces?):(.{0,800})",
    re.I | re.S,
)
_MEDUSA_FAIL = re.compile(
    r"(?:falsified|failed|property\s+fail|test fail)[^\n]{0,200}",
    re.I,
)


@dataclass
class FuzzFailure:
    property_id: str
    tool: str
    reproduction: str
    evidence: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FuzzReport:
    ran: bool = False
    skipped: bool = True
    tool: str = "none"  # medusa | forge | none
    status: str = "skipped"  # ok | failed | error | skipped | timeout | compile-skip
    properties_checked: int = 0
    property_ids: list[str] = field(default_factory=list)
    failures: list[FuzzFailure] = field(default_factory=list)
    fork_block: Optional[int] = None
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
            "tool": self.tool,
            "status": self.status,
            "properties_checked": self.properties_checked,
            "property_ids": list(self.property_ids),
            "failures": [f.to_dict() for f in self.failures],
            "fork_block": self.fork_block,
            "duration_ms": self.duration_ms,
            "notes": list(self.notes),
            "artifact": dict(self.artifact),
        }


def medusa_bin() -> Optional[str]:
    override = (os.environ.get("ETH_SCANNER_MEDUSA_BIN") or "").strip()
    if override and Path(override).exists():
        return override
    return shutil.which("medusa")


def forge_bin() -> Optional[str]:
    return shutil.which("forge")


def anvil_bin() -> Optional[str]:
    override = (os.environ.get("ETH_SCANNER_ANVIL_BIN") or "").strip()
    if override and Path(override).exists():
        return override
    return shutil.which("anvil")


def run_lead_fuzz(
    *,
    address: str,
    contract_class: str,
    contract_name: Optional[str] = None,
    rpc_url: str,
    work_dir: Optional[Path] = None,
    timeout_s: int = 60,
    source: str = "",
    compiler: Optional[str] = None,
    runtime_bytecode: str = "",
    source_dir: Optional[Path] = None,
) -> FuzzReport:
    """Fuzz only when caller already gated on leads + funds. Hard timeout."""
    report = FuzzReport()
    t0 = time.monotonic()
    budget = max(15, min(int(timeout_s or 60), 90))
    props = list(properties_for_class(contract_class))
    report.property_ids = props
    report.properties_checked = len(props)

    if not (rpc_url or "").strip():
        report.notes.append("fuzz skipped — no ETH_RPC_URL for anvil fork")
        report.duration_ms = int((time.monotonic() - t0) * 1000)
        return report
    from eth_scanner.ingest.rpc_client import probe_rpc
    ok_rpc, probe_reason = probe_rpc(rpc_url)
    if not ok_rpc:
        report.notes.append("fuzz skipped — %s" % (probe_reason or "ETH_RPC_URL unusable"))
        report.duration_ms = int((time.monotonic() - t0) * 1000)
        return report

    base = Path(work_dir) if work_dir else Path(tempfile.gettempdir())
    dest = base / "engine-fuzz" / (address.lower()[-16:] or "target")
    try:
        from eth_scanner.engines.fuzz_harness import harness_solc_version
        surface = None
        if (runtime_bytecode or "").strip():
            from eth_scanner.logic.bytecode_surface import recover_surface
            use_whatsabi = os.environ.get("ETH_SCANNER_WHATSABI", "1") != "0"
            surface = recover_surface(runtime_bytecode, use_whatsabi=use_whatsabi)
            if surface.get("functions") or surface.get("proxy_kind"):
                report.notes.append(
                    "bytecode surface selectors=%d proxy=%s"
                    % (len(surface.get("functions") or []), surface.get("proxy_kind") or "none")
                )
        project, props = write_live_fuzz_project(
            dest,
            address=address,
            contract_class=contract_class,
            contract_name=contract_name,
            solc_version=harness_solc_version(source=source, compiler=compiler),
            compiler=compiler,
            source=source,
            runtime_bytecode=runtime_bytecode,
            source_dir=source_dir,
            include_target_sources=False,
            surface=surface,
        )
        report.property_ids = props
        report.properties_checked = len(props)
    except Exception as exc:  # noqa: BLE001
        report.status = "error"
        report.notes.append("fuzz harness write failed: %s" % str(exc)[:160])
        report.duration_ms = int((time.monotonic() - t0) * 1000)
        return report

    # Compile first with a slice of the budget; skip fuzz if compile fails/times out.
    # Leave headroom for solc download when version is pinned per-contract.
    compile_budget = min(35, max(12, budget // 3))
    compiled, compile_note = _forge_build(project, timeout_s=compile_budget)
    report.notes.append(compile_note)
    if not compiled:
        report.status = "compile-skip"
        report.notes.append("fuzz skipped — could not compile harness in time")
        report.duration_ms = int((time.monotonic() - t0) * 1000)
        return report

    remaining = budget - int(time.monotonic() - t0)
    if remaining < 8:
        report.status = "timeout"
        report.notes.append("fuzz skipped — budget exhausted after compile")
        report.duration_ms = int((time.monotonic() - t0) * 1000)
        return report

    anvil_proc: Optional[subprocess.Popen[str]] = None
    fork_rpc = rpc_url
    parent_rpc = rpc_url
    try:
        anvil_proc, fork_rpc, block = _start_anvil_fork(rpc_url, remaining=remaining)
        if block is not None:
            report.fork_block = block
        if anvil_proc is None:
            report.notes.append("anvil unavailable — forge/medusa will use ETH_RPC_URL directly")
            fork_rpc = parent_rpc
        remaining = budget - int(time.monotonic() - t0)

        med = medusa_bin()
        if med and remaining >= 10:
            report.tool = "medusa"
            report.ran = True
            report.skipped = False
            active_rpc = _alive_fork_rpc(anvil_proc, fork_rpc, parent_rpc, report)
            _run_medusa(med, project, active_rpc, remaining, report)
        elif forge_bin() and remaining >= 8:
            report.tool = "forge"
            report.ran = True
            report.skipped = False
            active_rpc = _alive_fork_rpc(anvil_proc, fork_rpc, parent_rpc, report)
            _run_forge(project, active_rpc, remaining, report)
            # Parallel workers can kill local anvil mid-run; retry once on parent RPC.
            if (
                report.status == "error"
                and active_rpc != parent_rpc
                and _looks_like_fork_rpc_death(report.notes)
            ):
                report.notes.append("anvil died mid-run — retrying forge against ETH_RPC_URL")
                report.failures.clear()
                retry_budget = max(8, budget - int(time.monotonic() - t0))
                if retry_budget >= 8:
                    _run_forge(project, parent_rpc, retry_budget, report)
        else:
            report.status = "skipped"
            report.notes.append("fuzz skipped — medusa and forge not on PATH")
    finally:
        _stop_anvil(anvil_proc)

    report.duration_ms = int((time.monotonic() - t0) * 1000)
    report.artifact = {
        "kind": "fuzz",
        "label": "proof of a bug, not an attack",
        "tool": report.tool,
        "status": report.status,
        "address": address.lower(),
        "contract_class": contract_class,
        "contract_name": contract_name,
        "fork_block": report.fork_block,
        "properties_checked": report.properties_checked,
        "property_ids": list(report.property_ids),
        "failures": [f.to_dict() for f in report.failures],
        "duration_ms": report.duration_ms,
        "notes": list(report.notes)[:12],
    }
    return report


def _fuzz_harness_noise(property_id: str) -> bool:
    name = (property_id or "").lower().replace("()", "")
    return name in {"setup", "test_setup", "constructor", "deploy"} or name.endswith("setup")


def fuzz_failures_as_invariants(report: FuzzReport) -> list[dict[str, Any]]:
    """Map property failures into invariant rows.

    Harness setup failures stay as evidence (status unknown) and do not heat.
    Real property failures are still recorded, but heat ignores source=fuzz
    until a live eth_call rule fails.
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for fail in report.failures:
        key = str(fail.property_id or "")
        if key in seen:
            continue
        seen.add(key)
        noise = _fuzz_harness_noise(key)
        out.append({
            "id": "fuzz-%s" % key,
            "name": key,
            "status": "unknown" if noise else "failed",
            "evidence": fail.evidence[:400],
            "reproduction": "" if noise else fail.reproduction[:800],
            "tool": fail.tool,
            "source": "fuzz",
            "label": "harness setup did not run" if noise else "proof of a bug, not an attack",
        })
    return out


def fuzz_failures_as_confirmed(report: FuzzReport) -> list[dict[str, Any]]:
    """Confirmed evidence rows for /test 'confirmed by' UI."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for fail in report.failures:
        key = str(fail.property_id or "")
        if key in seen:
            continue
        seen.add(key)
        noise = _fuzz_harness_noise(key)
        out.append({
            "lead_id": "fuzz-%s" % key,
            "confirmed": not noise,
            "live_confirmed": False,
            "method": "fuzz",
            "evidence": (
                "proof of a bug, not an attack | %s | %s"
                % (fail.evidence, fail.reproduction)
            )[:500],
            "fork_block": report.fork_block,
            "extras": {
                "tool": fail.tool,
                "property": fail.property_id,
                "reproduction": fail.reproduction[:600],
            },
        })
    return out


# --- internals --------------------------------------------------------------


def _forge_build(project: Path, *, timeout_s: int) -> tuple[bool, str]:
    forge = forge_bin()
    if not forge:
        # Without forge we cannot pre-compile Foundry harnesses. Allow Medusa
        # to attempt crytic-compile, but do NOT mark compiled=True (caller still
        # proceeds when medusa is present via soft path below).
        if medusa_bin():
            return True, "forge missing — soft-allow medusa attempt (compile failures skip, never heat)"
        return False, "forge not on PATH — cannot compile fuzz harness"
    try:
        proc = subprocess.run(
            [forge, "build", "--silent"],
            cwd=str(project),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            env=_scrub_env(),
        )
    except subprocess.TimeoutExpired:
        return False, "forge build timed out after %ss" % timeout_s
    except OSError as exc:
        return False, "forge build failed to start: %s" % exc
    if proc.returncode != 0:
        tail = ((proc.stderr or "") + (proc.stdout or ""))[-240:].replace("\n", " ")
        return False, "forge build exit=%s — %s" % (proc.returncode, tail)
    return True, "forge build ok"


def _run_medusa(
    med: str,
    project: Path,
    fork_rpc: str,
    budget_s: int,
    report: FuzzReport,
) -> None:
    # Prefer workers = CPU count (0 in medusa.json means auto on some versions;
    # pass explicit flag when supported).
    workers = max(1, (os.cpu_count() or 2))
    cmd = [
        med, "fuzz",
        "--config", "medusa.json",
        "--timeout", str(max(5, budget_s - 2)),
    ]
    # Newer medusa accepts --workers; ignore if unknown via soft failure.
    env = _scrub_env()
    env["ETH_RPC_URL"] = fork_rpc
    try:
        proc = subprocess.run(
            cmd + ["--workers", str(workers)],
            cwd=str(project),
            capture_output=True,
            text=True,
            timeout=budget_s,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        blob = ((exc.stdout or "") if isinstance(exc.stdout, str) else "") + \
               ((exc.stderr or "") if isinstance(exc.stderr, str) else "")
        _ingest_medusa_output(blob or "medusa timed out", report)
        report.status = "timeout" if not report.failures else "failed"
        report.notes.append("medusa timed out after %ss" % budget_s)
        return
    except OSError:
        # Retry without --workers
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(project),
                capture_output=True,
                text=True,
                timeout=budget_s,
                check=False,
                env=env,
            )
        except (subprocess.TimeoutExpired, OSError) as exc2:
            report.status = "error"
            report.notes.append("medusa failed: %s" % str(exc2)[:160])
            # Fall through to forge if possible.
            if forge_bin():
                report.notes.append("falling back to forge after medusa error")
                report.tool = "forge"
                _run_forge(project, fork_rpc, max(8, budget_s // 2), report)
            return

    blob = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    _ingest_medusa_output(blob, report)
    if report.failures:
        report.status = "failed"
    elif "compil" in blob.lower() or "crytic-compile" in blob.lower():
        report.notes.append("medusa could not compile — trying forge fallback")
        if forge_bin():
            report.tool = "forge"
            _run_forge(project, fork_rpc, max(8, budget_s // 2), report)
        else:
            report.status = "compile-skip"
            report.ran = False
            report.skipped = True
            report.notes.append("fuzz compile-skip — medusa compile failed and forge missing")
    elif proc.returncode not in (0, None) and "not found" in blob.lower():
        report.notes.append("medusa unavailable — falling back to forge")
        if forge_bin():
            report.tool = "forge"
            _run_forge(project, fork_rpc, max(8, budget_s // 2), report)
        else:
            report.status = "error"
    elif proc.returncode != 0 and not report.failures:
        # Non-zero without parsed failures — treat as error/skip, try forge.
        report.notes.append("medusa exit=%s — trying forge fallback" % proc.returncode)
        if forge_bin():
            report.tool = "forge"
            _run_forge(project, fork_rpc, max(8, budget_s // 2), report)
        else:
            report.status = "error"
    else:
        report.status = "ok"
    report.notes.append(
        "medusa workers~%s exit=%s failures=%d"
        % (workers, getattr(proc, "returncode", "?"), report.failure_count)
    )


def _ingest_medusa_output(blob: str, report: FuzzReport) -> None:
    text = blob or ""
    low_all = text.lower()
    # Compile / infra errors are skips — never property failures / heat.
    if any(tok in low_all for tok in (
        "failed to compile",
        "compilation failed",
        "could not compile",
        "solc error",
        "crytic-compile",
        "no such file",
        "command not found",
    )) and "falsified" not in low_all and "property fail" not in low_all:
        report.notes.append("medusa compile/infra failure — treating as compile-skip")
        return
    hits = _MEDUSA_FAIL.findall(text)
    for hit in hits[:8]:
        low = hit.lower()
        if "compil" in low or "crytic" in low:
            continue
        prop = "medusa_property"
        for pid in report.property_ids:
            if pid.replace("_", "").lower() in low.replace("_", "").replace(" ", ""):
                prop = pid
                break
        report.failures.append(FuzzFailure(
            property_id=prop,
            tool="medusa",
            reproduction=_extract_sequence(hit) or hit[:400],
            evidence=hit[:300],
        ))


def _run_forge(
    project: Path,
    fork_rpc: str,
    budget_s: int,
    report: FuzzReport,
) -> None:
    forge = forge_bin()
    if not forge:
        report.status = "skipped"
        report.notes.append("forge not on PATH")
        return
    # Foundry 1.9 dropped --invariant-runs; fuzz runs come from CLI / foundry.toml.
    # Harness is unit/fuzz tests only (no invariant_* handlers) so campaigns stay
    # on the live TARGET via --fork-url.
    cmd = [
        forge, "test",
        "--fork-url", fork_rpc,
        "--fuzz-runs", "24",
        "--match-contract", "LiveProperties",
        "-vv",
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(project),
            capture_output=True,
            text=True,
            timeout=max(8, budget_s),
            check=False,
            env=_scrub_env(),
        )
    except subprocess.TimeoutExpired as exc:
        out = ""
        if isinstance(exc.stdout, str):
            out += exc.stdout
        if isinstance(exc.stderr, str):
            out += "\n" + exc.stderr
        parsed = parse_forge_output(out)
        _ingest_forge_parsed(parsed, out, report)
        report.status = "timeout" if not report.failures else "failed"
        report.notes.append("forge test timed out after %ss" % budget_s)
        return
    except OSError as exc:
        report.status = "error"
        report.notes.append("forge test failed to start: %s" % exc)
        return

    blob = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    parsed = parse_forge_output(blob)
    _ingest_forge_parsed(parsed, blob, report)
    if report.failures:
        report.status = "failed"
    elif proc.returncode != 0:
        report.status = "error"
        tail = blob[-240:].replace("\n", " ").strip()
        report.notes.append(
            "forge test exit=%s with no parsed failures — %s"
            % (proc.returncode, tail[:200])
        )
    else:
        report.status = "ok"
    report.notes.append(
        "forge test exit=%s passed=%s failed=%s"
        % (proc.returncode, parsed.get("passed_n"), parsed.get("failed_n"))
    )


def _ingest_forge_parsed(parsed: dict[str, Any], blob: str, report: FuzzReport) -> None:
    failed = list(parsed.get("failed") or [])
    for name in failed[:12]:
        prop = str(name)
        for pid in report.property_ids:
            if pid.lower() in prop.lower().replace("test_", "").replace("testfuzz_", ""):
                prop = pid
                break
        # Strip forge prefixes
        clean = re.sub(r"^(testFuzz_|test_|invariant_)", "", str(name))
        if clean in report.property_ids:
            prop = clean
        seq = _extract_sequence(blob) or ("forge fail: %s" % name)
        report.failures.append(FuzzFailure(
            property_id=prop,
            tool="forge",
            reproduction=seq[:800],
            evidence=("property failed: %s" % name)[:300],
        ))


def _extract_sequence(blob: str) -> str:
    m = _FORGE_SEQ.search(blob or "")
    if m:
        return re.sub(r"\s+", " ", m.group(0))[:800]
    return ""


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _alive_fork_rpc(
    anvil_proc: Optional[subprocess.Popen[str]],
    fork_rpc: str,
    parent_rpc: str,
    report: FuzzReport,
) -> str:
    """Prefer local anvil when still serving; otherwise fall back to parent RPC."""
    if anvil_proc is None or fork_rpc == parent_rpc:
        return parent_rpc
    if anvil_proc.poll() is not None:
        report.notes.append("anvil exited early — using ETH_RPC_URL")
        return parent_rpc
    if _eth_block_number(fork_rpc) is None:
        report.notes.append("anvil not answering eth_blockNumber — using ETH_RPC_URL")
        return parent_rpc
    return fork_rpc


def _looks_like_fork_rpc_death(notes: list[str]) -> bool:
    blob = " ".join(notes).lower()
    return any(
        tok in blob
        for tok in (
            "fork endpoint",
            "tcp connect",
            "connection refused",
            "error sending request",
            "could not instantiate",
            "failed to get chain id",
            "ieve chain id",  # truncated "retrieve chain ID"
        )
    )


def _start_anvil_fork(
    rpc_url: str,
    *,
    remaining: float,
) -> tuple[Optional[subprocess.Popen[str]], str, Optional[int]]:
    anvil = anvil_bin()
    if not anvil or remaining < 5:
        return None, rpc_url, None
    port = _free_port()
    try:
        proc = subprocess.Popen(
            [
                anvil,
                "--fork-url", rpc_url,
                "--port", str(port),
                "--silent",
                "--accounts", "0",
                "--no-mining",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            env=_scrub_env(),
        )
    except OSError:
        return None, rpc_url, None

    fork_rpc = "http://127.0.0.1:%d" % port
    # Wait briefly for boot.
    deadline = time.monotonic() + min(8.0, max(2.0, remaining / 4))
    block: Optional[int] = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return None, rpc_url, None
        block = _eth_block_number(fork_rpc)
        if block is not None:
            return proc, fork_rpc, block
        time.sleep(0.15)
    # Boot slow — still return proc if alive.
    if proc.poll() is None:
        return proc, fork_rpc, _eth_block_number(fork_rpc)
    return None, rpc_url, None


def _eth_block_number(rpc: str) -> Optional[int]:
    try:
        import urllib.request
        req = urllib.request.Request(
            rpc,
            data=json.dumps({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_blockNumber",
                "params": [],
            }).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode())
        raw = data.get("result")
        if isinstance(raw, str):
            return int(raw, 16)
    except Exception:  # noqa: BLE001
        return None
    return None


def _stop_anvil(proc: Optional[subprocess.Popen[str]]) -> None:
    if proc is None:
        return
    try:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
    except Exception:  # noqa: BLE001
        pass


def _scrub_env() -> dict[str, str]:
    env = dict(os.environ)
    # Never pass signing keys into fuzz children (API keys stay).
    drop = {
        "ETH_PRIVATE_KEY", "PRIVATE_KEY", "MNEMONIC", "WALLET_PRIVATE_KEY",
        "DEPLOYER_PRIVATE_KEY", "ANVIL_PRIVATE_KEY",
    }
    for k in list(env):
        if k in drop or "PRIVATE_KEY" in k or k.endswith("_MNEMONIC"):
            env.pop(k, None)
    return env
