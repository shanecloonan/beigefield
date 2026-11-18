"""Post-heat fork verification — Foundry invariant tests on a local fork.

For contracts already at or above ETH_SCANNER_FUZZ_MIN_HEAT, this stage
spins a Foundry campaign on a local anvil (optionally forked from
ETH_RPC_URL) and checks a conservation property:

    an unprivileged caller cannot increase its ETH balance while the
    target's ETH balance decreases.

A broken invariant is recorded as heat_breakdown.exploit_poc with
drainable=true and a sanitized failing sequence. Nothing is broadcast
to mainnet. No signed transactions, no packaged attack scripts.

If ETH_RPC_URL is unset or unusable (quota/auth/repeated 5xx), live
targets skip. Fixture mode (--fixture leaky|safe) plants a local
contract on anvil and needs no RPC.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from eth_scanner.engines.fuzz_harness import _hex40
from eth_scanner.engines.fuzz_runner import (
    anvil_bin,
    forge_bin,
    _extract_sequence,
    _eth_block_number,
    _scrub_env,
    _stop_anvil,
)
from eth_scanner.research.fuzz import parse_forge_output
from eth_scanner.research.keccak import selector4
from eth_scanner.types import FunnelResult, MAX_HEAT, StageTrace


DEFAULT_MIN_HEAT = 8
DEFAULT_TIMEOUT_S = 90
DEFAULT_FUZZ_RUNS = 16
DEFAULT_INVARIANT_DEPTH = 6
DEFAULT_EXPLOIT_POC_HEAT = 6
DEFAULT_FROM_STORE_LIMIT = 1
PLANT_ADDRESS = "0x1111111111111111111111111111111111111111"
ATTACKER_ADDRESS = "0x00000000000000000000000000000000000a11ce"
PLANT_WEI = 100 * 10**18
ATTACKER_WEI = 10 * 10**18

# Always tried in addition to selectors parsed from verified source.
# These are conservation-property probes, not an exploit catalog.
_COMMON_SIGS = (
    "poke()",
    "drain()",
    "withdraw()",
    "withdraw(uint256)",
    "withdrawAll()",
    "skim()",
    "skim(address)",
    "collect()",
    "sweep(address)",
    "rescue(address)",
    "harvest()",
    "claim()",
    "claimRewards()",
    "emergencyWithdraw()",
    "execute(address,bytes)",
    "deposit()",
)

_FN_RX = re.compile(
    r"function\s+([A-Za-z_]\w*)\s*\(([^)]*)\)\s*(public|external)",
    re.M,
)


def fuzz_min_heat() -> int:
    return _env_int("ETH_SCANNER_FUZZ_MIN_HEAT", DEFAULT_MIN_HEAT)


def fuzz_timeout_s() -> int:
    return max(15, _env_int("ETH_SCANNER_FUZZ_TIMEOUT_S", DEFAULT_TIMEOUT_S))


def fuzz_runs() -> int:
    return max(1, _env_int("ETH_SCANNER_FUZZ_RUNS", DEFAULT_FUZZ_RUNS))


def exploit_poc_heat() -> int:
    return max(0, _env_int("ETH_SCANNER_HEAT_EXPLOIT_POC", DEFAULT_EXPLOIT_POC_HEAT))


def fork_verify_enabled() -> bool:
    """Lane A / strong-deep opt-in. CLI and --fixture always run the stage."""
    raw = os.environ.get("ETH_SCANNER_FORK_VERIFY")
    if raw is None or not str(raw).strip():
        return False
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(float(raw))
    except ValueError:
        return default


def _leaky_sol() -> str:
    for cand in (
        Path(__file__).with_name("fork_verify_fixtures.sol"),
        Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "leaky_vault.sol",
    ):
        if cand.is_file():
            return cand.read_text(encoding="utf-8")
    raise FileNotFoundError("fork-verify fixture source missing")


@dataclass
class ForkVerifyFailure:
    property_id: str
    tool: str
    reproduction: str
    evidence: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ForkVerifyReport:
    ran: bool = False
    skipped: bool = True
    status: str = "skipped"  # ok | broken | skipped | timeout | error | compile-skip
    drainable: bool = False
    tool: str = "none"
    heat_in: int = 0
    address: str = ""
    fixture: str = ""
    property_ids: list[str] = field(default_factory=list)
    failures: list[ForkVerifyFailure] = field(default_factory=list)
    sequence: str = ""
    fork_block: Optional[int] = None
    duration_ms: int = 0
    notes: list[str] = field(default_factory=list)
    artifact: dict[str, Any] = field(default_factory=dict)
    skip_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ran": self.ran,
            "skipped": self.skipped,
            "status": self.status,
            "drainable": self.drainable,
            "tool": self.tool,
            "heat_in": self.heat_in,
            "address": self.address,
            "fixture": self.fixture,
            "property_ids": list(self.property_ids),
            "failures": [f.to_dict() for f in self.failures],
            "sequence": self.sequence,
            "fork_block": self.fork_block,
            "duration_ms": self.duration_ms,
            "notes": list(self.notes),
            "skip_reason": self.skip_reason,
            "exploit_poc": self.exploit_poc_dict(),
            "artifact": dict(self.artifact),
        }

    def exploit_poc_dict(self) -> dict[str, Any]:
        return {
            "drainable": bool(self.drainable),
            "status": self.status,
            "tool": self.tool,
            "property": (
                self.failures[0].property_id
                if self.failures
                else "attacker_cannot_extract_target_value"
            ),
            "sequence": self.sequence[:800],
            "fork_block": self.fork_block,
            "duration_ms": self.duration_ms,
            "label": (
                "unprivileged caller extracted value on a local fork — not a live transaction"
                if self.drainable
                else "conservation invariant held (or stage skipped)"
            ),
            "bucket_hint": "proven-drainable" if self.drainable else "",
        }

    def as_invariant_row(self) -> dict[str, Any]:
        fail = self.failures[0] if self.failures else None
        return {
            "id": "profit-attacker-balance",
            "name": "attacker_cannot_extract_target_value",
            "status": "failed" if self.drainable else "held",
            "source": "fork-verify",
            "attacker_delta": 1 if self.drainable else 0,
            "evidence": (fail.evidence if fail else self.sequence or self.status)[:400],
            "reproduction": (self.sequence or (fail.reproduction if fail else ""))[:800],
            "tool": self.tool or "forge",
            "label": "unprivileged caller extracted value on a local fork — not a live transaction",
        }


def should_run_fork_verify(
    *,
    heat: int = 0,
    rpc_url: str = "",
    fixture: str = "",
    enabled: Optional[bool] = None,
    min_heat: Optional[int] = None,
    force: bool = False,
) -> tuple[bool, str]:
    """Return (ok, reason). Fixture/force bypass the heat + enabled gates."""
    if (fixture or "").strip():
        kind = (fixture or "").strip().lower()
        if kind not in {"leaky", "safe"}:
            return False, "unknown fixture %s (want leaky|safe)" % kind
        return True, "fixture"
    if force:
        if not (rpc_url or "").strip():
            return False, "no ETH_RPC_URL"
        from eth_scanner.ingest.rpc_client import is_rpc_usable, rpc_unusable_reason
        if not is_rpc_usable(rpc_url):
            return False, rpc_unusable_reason(rpc_url) or "ETH_RPC_URL unusable"
        return True, "forced"
    if enabled is None:
        enabled = fork_verify_enabled()
    if not enabled:
        return False, "fork-verify disabled (set ETH_SCANNER_FORK_VERIFY=1)"
    bar = fuzz_min_heat() if min_heat is None else int(min_heat)
    if int(heat or 0) < bar:
        return False, "heat %s below ETH_SCANNER_FUZZ_MIN_HEAT=%s" % (heat, bar)
    if not (rpc_url or "").strip():
        return False, "no ETH_RPC_URL"
    from eth_scanner.ingest.rpc_client import is_rpc_usable, rpc_unusable_reason
    if not is_rpc_usable(rpc_url):
        return False, rpc_unusable_reason(rpc_url) or "ETH_RPC_URL unusable"
    return True, "ok"


def selectors_from_source(source: str = "") -> list[str]:
    """4-byte selectors from public/external functions + the common probe set."""
    sigs: list[str] = list(_COMMON_SIGS)
    for name, raw_args, _vis in _FN_RX.findall(source or ""):
        args = ",".join(_type_of(part) for part in raw_args.split(",") if part.strip())
        sigs.append("%s(%s)" % (name, args))
    out: list[str] = []
    seen: set[str] = set()
    for sig in sigs:
        try:
            sel = selector4(sig)
        except Exception:  # noqa: BLE001
            continue
        if sel in seen:
            continue
        seen.add(sel)
        out.append(sel)
        if len(out) >= 24:
            break
    return out


def _type_of(part: str) -> str:
    toks = part.strip().split()
    return toks[0] if toks else "uint256"


def write_fork_verify_project(
    dest: Path,
    *,
    address: str,
    selectors: Optional[list[str]] = None,
    source: str = "",
) -> tuple[Path, list[str]]:
    """Materialize a Foundry project with conservation invariants + selector probes."""
    root = Path(dest)
    if root.exists():
        shutil.rmtree(root)
    (root / "src").mkdir(parents=True)
    (root / "test").mkdir(parents=True)
    (root / "lib" / "forge-std" / "src").mkdir(parents=True)
    _write_fork_verify_std(root / "lib" / "forge-std" / "src")
    (root / "remappings.txt").write_text(
        "forge-std/=lib/forge-std/src/\n",
        encoding="utf-8",
    )
    (root / "foundry.toml").write_text(
        "\n".join([
            "[profile.default]",
            'src = "src"',
            'test = "test"',
            'out = "out"',
            'libs = ["lib"]',
            'solc = "0.8.20"',
            "optimizer = true",
            "optimizer_runs = 200",
            "ffi = false",
            "fs_permissions = []",
            "isolate = false",
            'evm_version = "shanghai"',
            "auto_detect_solc = false",
            'remappings = ["forge-std/=lib/forge-std/src/"]',
            "",
            "[profile.default.fuzz]",
            "runs = %d" % fuzz_runs(),
            "",
            "[profile.default.invariant]",
            "runs = %d" % fuzz_runs(),
            "depth = %d" % DEFAULT_INVARIANT_DEPTH,
            "fail_on_revert = false",
            "",
        ]),
        encoding="utf-8",
    )
    sels = list(selectors or selectors_from_source(source))
    if not sels:
        sels = [selector4(s) for s in _COMMON_SIGS]
    props = [
        "unprivileged_known_selectors_cannot_extract",
        "unprivileged_sequence_cannot_extract",
    ]
    (root / "test" / "ForkVerifyProperties.t.sol").write_text(
        _fork_verify_sol(_hex40(address), _hex40(ATTACKER_ADDRESS), sels),
        encoding="utf-8",
    )
    return root, props


def run_fork_verify(
    *,
    address: str = "",
    rpc_url: str = "",
    heat: int = 0,
    source: str = "",
    selectors: Optional[list[str]] = None,
    fixture: str = "",
    work_dir: Optional[Path] = None,
    timeout_s: Optional[int] = None,
    enabled: Optional[bool] = None,
    min_heat: Optional[int] = None,
    force: bool = False,
) -> ForkVerifyReport:
    """Run the conservation campaign. Never broadcasts to a public network."""
    report = ForkVerifyReport(heat_in=int(heat or 0), fixture=(fixture or "").strip().lower())
    t0 = time.monotonic()
    budget = max(15, min(int(timeout_s or fuzz_timeout_s()), 180))
    ok, reason = should_run_fork_verify(
        heat=heat,
        rpc_url=rpc_url,
        fixture=report.fixture,
        enabled=enabled,
        min_heat=min_heat,
        force=force,
    )
    # CLI `--address` with an RPC should run even when the Lane A env flag is off,
    # as long as heat meets the bar (or force=True).
    if (
        not ok
        and not report.fixture
        and (rpc_url or "").strip()
        and (
            force
            or int(heat or 0) >= (fuzz_min_heat() if min_heat is None else int(min_heat))
        )
    ):
        ok, reason = True, "cli"
    if not ok:
        report.skip_reason = reason
        report.notes.append("fork-verify skipped — %s" % reason)
        report.duration_ms = int((time.monotonic() - t0) * 1000)
        return report

    if not report.fixture and (rpc_url or "").strip():
        from eth_scanner.ingest.rpc_client import probe_rpc
        ok_rpc, probe_reason = probe_rpc(rpc_url)
        if not ok_rpc:
            report.skip_reason = probe_reason or "ETH_RPC_URL unusable"
            report.notes.append("fork-verify skipped — %s" % report.skip_reason)
            report.duration_ms = int((time.monotonic() - t0) * 1000)
            return report

    if not forge_bin() or not anvil_bin():
        report.status = "skipped"
        report.skip_reason = "forge/anvil not on PATH"
        report.notes.append("fork-verify skipped — forge and anvil must be on PATH")
        report.duration_ms = int((time.monotonic() - t0) * 1000)
        return report

    base = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="fork-verify-"))
    base.mkdir(parents=True, exist_ok=True)
    anvil_proc: Optional[subprocess.Popen[str]] = None
    try:
        if report.fixture:
            anvil_proc, fork_rpc = _start_anvil_local()
            if anvil_proc is None:
                report.status = "error"
                report.notes.append("could not start local anvil for fixture")
                report.duration_ms = int((time.monotonic() - t0) * 1000)
                return report
            report.fork_block = _eth_block_number(fork_rpc)
            target = _plant_fixture(fork_rpc, report.fixture, base / "plant")
            report.address = target
            sels = selectors_from_source(_leaky_sol())
        else:
            target = (address or "").strip()
            if not target:
                report.status = "skipped"
                report.skip_reason = "no address"
                report.notes.append("fork-verify skipped — no address")
                report.duration_ms = int((time.monotonic() - t0) * 1000)
                return report
            report.address = target.lower()
            anvil_proc, fork_rpc, block = _start_anvil_fork_safe(rpc_url, remaining=budget)
            if anvil_proc is None:
                fork_rpc = rpc_url
                report.notes.append("anvil fork unavailable — forge will use ETH_RPC_URL directly")
            report.fork_block = block if anvil_proc is not None else _eth_block_number(fork_rpc)
            sels = list(selectors or selectors_from_source(source))

        project, props = write_fork_verify_project(
            base / "harness",
            address=target,
            selectors=sels,
            source=source,
        )
        report.property_ids = props
        remaining = budget - int(time.monotonic() - t0)
        if remaining < 8:
            report.status = "timeout"
            report.notes.append("fork-verify skipped — budget exhausted before forge test")
            report.duration_ms = int((time.monotonic() - t0) * 1000)
            return report
        _run_forge_verify(project, fork_rpc, remaining, report)
    except Exception as exc:  # noqa: BLE001
        report.status = "error"
        report.notes.append("fork-verify error: %s" % str(exc)[:200])
    finally:
        _stop_anvil(anvil_proc)

    report.duration_ms = int((time.monotonic() - t0) * 1000)
    report.artifact = {
        "kind": "fork-verify",
        "label": "conservation invariant on a local fork — not a live transaction",
        "tool": report.tool,
        "status": report.status,
        "drainable": report.drainable,
        "address": report.address,
        "fixture": report.fixture,
        "fork_block": report.fork_block,
        "sequence": report.sequence[:800],
        "failures": [f.to_dict() for f in report.failures],
        "duration_ms": report.duration_ms,
        "notes": list(report.notes)[:12],
    }
    return report


def apply_fork_verify(result: FunnelResult, report: ForkVerifyReport) -> FunnelResult:
    """Merge a report into a FunnelResult. Promotes cool/lane-b to manual-review when drainable."""
    hb = dict(result.heat_breakdown or {})
    poc = report.exploit_poc_dict()
    hb["exploit_poc"] = poc
    hb["drainable"] = bool(report.drainable)
    result.notes = list(result.notes or [])
    if report.drainable:
        row = report.as_invariant_row()
        result.invariant_results = list(result.invariant_results or []) + [row]
        bonus = exploit_poc_heat()
        hb["exploit_poc_heat"] = bonus
        prev = int(result.heat or 0)
        result.heat = min(MAX_HEAT, prev + bonus)
        hb["total"] = result.heat
        try:
            from eth_scanner.drain import score_drain
            drain = score_drain(
                funds_usd=result.funds_usd,
                invariant_results=list(result.invariant_results or []),
                contract_class=result.contract_class or "",
            )
            hb["drain_probability"] = drain["drain_probability"]
            hb["profit_invariant_broke"] = drain["profit_invariant_broke"]
            hb["drain_band"] = drain["band"]
            hb["drain_reason"] = drain["reason"]
        except Exception:  # noqa: BLE001
            hb["profit_invariant_broke"] = True
        if result.bucket in {None, "lane-a-cool", "lane-b-queue"}:
            result.bucket = "manual-review"
        result.notes.append(
            "fork-verify drainable: unprivileged caller extracted value on a local fork (not broadcast)"
        )
        result.stage_trace = list(result.stage_trace or []) + [
            StageTrace(
                stage="fork-verify",
                decision=str(result.bucket or "manual-review"),
                reason="profit invariant broke on a local fork",
                extras=poc,
            )
        ]
    else:
        result.notes.append(
            "fork-verify %s tool=%s drainable=false (%s)"
            % (report.status, report.tool, report.skip_reason or "held")
        )
        if report.ran:
            result.stage_trace = list(result.stage_trace or []) + [
                StageTrace(
                    stage="fork-verify",
                    decision=str(result.bucket or "held"),
                    reason="conservation invariant held (or no break within budget)",
                    extras=poc,
                )
            ]
    result.heat_breakdown = hb
    return result


def maybe_run_on_result(
    result: FunnelResult,
    *,
    settings: Any,
    address: str,
    source: str = "",
) -> Optional[ForkVerifyReport]:
    """Lane A hook. No-op unless ETH_SCANNER_FORK_VERIFY is on and heat clears the bar."""
    rpc = str(getattr(settings, "eth_rpc_url", "") or "")
    ok, reason = should_run_fork_verify(heat=int(result.heat or 0), rpc_url=rpc)
    if not ok:
        if "disabled" not in reason:
            result.notes = list(result.notes or []) + ["fork-verify skipped — %s" % reason]
        return None
    report = run_fork_verify(
        address=address,
        rpc_url=rpc,
        heat=int(result.heat or 0),
        source=source,
        work_dir=Path(getattr(settings, "work_dir", Path(tempfile.gettempdir()))) / "fork-verify",
        enabled=True,
    )
    apply_fork_verify(result, report)
    return report


def apply_fork_verify_to_row(row: dict[str, Any], report: ForkVerifyReport) -> dict[str, Any]:
    """Patch a stored result/target row (used by --from-store)."""
    hb = dict(row.get("heat_breakdown") or {}) if isinstance(row.get("heat_breakdown"), dict) else {}
    poc = report.exploit_poc_dict()
    hb["exploit_poc"] = poc
    hb["drainable"] = bool(report.drainable)
    out = dict(row)
    if report.drainable:
        bonus = exploit_poc_heat()
        hb["exploit_poc_heat"] = bonus
        prev = int(row.get("heat") or 0)
        out["heat"] = min(MAX_HEAT, prev + bonus)
        hb["total"] = out["heat"]
        inv = list(row.get("invariant_results") or [])
        inv.append(report.as_invariant_row())
        out["invariant_results"] = inv
        try:
            from eth_scanner.drain import score_drain
            drain = score_drain(
                funds_usd=row.get("funds_usd"),
                invariant_results=inv,
                contract_class=str(row.get("contract_class") or ""),
            )
            hb["drain_probability"] = drain["drain_probability"]
            hb["profit_invariant_broke"] = drain["profit_invariant_broke"]
            hb["drain_band"] = drain["band"]
            hb["drain_reason"] = drain["reason"]
        except Exception:  # noqa: BLE001
            hb["profit_invariant_broke"] = True
        if out.get("bucket") in {None, "lane-a-cool", "lane-b-queue"}:
            out["bucket"] = "manual-review"
    out["heat_breakdown"] = hb
    return out


def list_high_heat_rows(store: Any, *, min_heat: int, limit: int) -> list[dict[str, Any]]:
    """Best-effort query of recent high-heat results, unique by address."""
    fn = getattr(store, "list_results_by_heat", None)
    if callable(fn):
        return list(fn(min_heat=min_heat, limit=limit) or [])
    rows = list(getattr(store, "list_results", lambda **_: [])(limit=max(200, limit * 20)) or [])
    rows = [r for r in rows if int(r.get("heat") or 0) >= int(min_heat)]
    rows.sort(key=lambda r: (int(r.get("heat") or 0), str(r.get("created_at") or "")), reverse=True)
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        addr = str(row.get("address") or "").lower()
        if not addr or addr in seen:
            continue
        seen.add(addr)
        out.append(row)
        if len(out) >= limit:
            break
    return out


def persist_fork_verify(store: Any, row: dict[str, Any], patched: dict[str, Any]) -> None:
    """Write heat/bucket/breakdown back to the latest result + target, when the store allows."""
    fn = getattr(store, "patch_fork_verify", None)
    if callable(fn):
        fn(row, patched)
        return
    addr = str(patched.get("address") or row.get("address") or "").lower()
    results = getattr(store, "results", None)
    if isinstance(results, list):
        for existing in reversed(results):
            if str(existing.get("address") or "").lower() == addr:
                existing.update({
                    k: patched[k]
                    for k in ("heat", "bucket", "heat_breakdown", "invariant_results")
                    if k in patched
                })
                break
    targets = getattr(store, "targets", None)
    if isinstance(targets, dict) and addr in targets:
        tgt = targets[addr]
        if "heat" in patched:
            tgt["heat"] = patched["heat"]
        if "bucket" in patched:
            tgt["bucket"] = patched["bucket"]
        if "heat_breakdown" in patched:
            tgt["heat_breakdown"] = patched["heat_breakdown"]
        flush = getattr(store, "_flush", None)
        if callable(flush):
            flush()


def _write_fork_verify_std(dest: Path) -> None:
    """Richer Vm/Test than the Halmos-minimal std (needs prank + deal)."""
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "Vm.sol").write_text(
        "// SPDX-License-Identifier: MIT\n"
        "pragma solidity >=0.6.2 <0.9.0;\n\n"
        "interface Vm {\n"
        "    function deal(address account, uint256 newBalance) external;\n"
        "    function prank(address msgSender) external;\n"
        "}\n",
        encoding="utf-8",
    )
    (dest / "Test.sol").write_text(
        "// SPDX-License-Identifier: MIT\n"
        "pragma solidity >=0.6.2 <0.9.0;\n\n"
        'import {Vm} from "./Vm.sol";\n\n'
        "abstract contract Test {\n"
        "    Vm internal constant vm = Vm(address(uint160(uint256(keccak256(\"hevm cheat code\")))));\n\n"
        "    function bound(uint256 x, uint256 minV, uint256 maxV) internal pure returns (uint256) {\n"
        "        if (minV > maxV) {\n"
        "            (minV, maxV) = (maxV, minV);\n"
        "        }\n"
        "        if (maxV == minV) return minV;\n"
        "        return minV + (x % (maxV - minV + 1));\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )


def _fork_verify_sol(target_hex40: str, attacker_hex40: str, selectors: list[str]) -> str:
    sel_lits = ", ".join('bytes4(hex"%s")' % _sel_hex(s) for s in selectors)
    n = max(1, len(selectors))
    return (
        "// SPDX-License-Identifier: MIT\n"
        "pragma solidity ^0.8.20;\n\n"
        'import {Test} from "forge-std/Test.sol";\n\n'
        "/// Conservation properties for a local-fork campaign.\n"
        "/// A failure is proof that an unprivileged caller extracted value\n"
        "/// on this fork — never an attack script and never broadcast.\n"
        "contract ForkVerifyProperties is Test {\n"
        f'    address constant TARGET = address(bytes20(hex"{target_hex40}"));\n'
        f'    address constant ATTACKER = address(bytes20(hex"{attacker_hex40}"));\n'
        "    uint256 internal attackerStart;\n"
        "    uint256 internal targetStart;\n"
        "    bytes4[] internal sels;\n\n"
        "    function setUp() public {\n"
        "        vm.deal(ATTACKER, 10 ether);\n"
        "        attackerStart = ATTACKER.balance;\n"
        "        targetStart = TARGET.balance;\n"
        f"        bytes4[{n}] memory seed = [{sel_lits}];\n"
        "        for (uint256 i = 0; i < seed.length; i++) {\n"
        "            sels.push(seed[i]);\n"
        "        }\n"
        "    }\n\n"
        "    function _extracted(uint256 a0, uint256 t0) internal view returns (bool) {\n"
        "        return ATTACKER.balance > a0 && TARGET.balance < t0;\n"
        "    }\n\n"
        "    /// Deterministic probe of known function selectors as the outsider.\n"
        "    function test_unprivileged_known_selectors_cannot_extract() public {\n"
        "        for (uint256 i = 0; i < sels.length; i++) {\n"
        "            uint256 a0 = ATTACKER.balance;\n"
        "            uint256 t0 = TARGET.balance;\n"
        "            vm.prank(ATTACKER);\n"
        "            (bool ok,) = TARGET.call(abi.encodePacked(sels[i]));\n"
        "            ok;\n"
        "            if (_extracted(a0, t0)) {\n"
        '                revert("profit-attacker-balance");\n'
        "            }\n"
        "        }\n"
        "        if (_extracted(attackerStart, targetStart)) {\n"
        '            revert("profit-attacker-balance");\n'
        "        }\n"
        "    }\n\n"
        "    /// Random short sequences of selector (+ optional value) calls from the outsider.\n"
        "    function testFuzz_unprivileged_sequence_cannot_extract(uint256 seed, uint8 nRaw) public {\n"
        "        if (sels.length == 0) return;\n"
        "        uint256 steps = bound(uint256(nRaw), 1, 8);\n"
        "        for (uint256 i = 0; i < steps; i++) {\n"
        "            uint256 mix = uint256(keccak256(abi.encode(seed, i)));\n"
        "            bytes4 sel = sels[mix % sels.length];\n"
        "            uint256 pay = 0;\n"
        "            if (mix % 3 == 0 && ATTACKER.balance > 0) {\n"
        "                pay = bound(mix, 0, ATTACKER.balance / 4);\n"
        "            }\n"
        "            uint256 a0 = ATTACKER.balance;\n"
        "            uint256 t0 = TARGET.balance;\n"
        "            vm.prank(ATTACKER);\n"
        "            (bool ok,) = TARGET.call{value: pay}(abi.encodePacked(sel));\n"
        "            ok;\n"
        "            if (_extracted(a0, t0) || _extracted(attackerStart, targetStart)) {\n"
        '                revert("profit-attacker-balance");\n'
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )


def _sel_hex(sel: str) -> str:
    s = (sel or "").strip().lower()
    if s.startswith("0x"):
        s = s[2:]
    s = "".join(c for c in s if c in "0123456789abcdef")
    return (s + "0" * 8)[:8]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _start_anvil_local() -> tuple[Optional[subprocess.Popen[str]], str]:
    anvil = anvil_bin()
    if not anvil:
        return None, ""
    port = _free_port()
    try:
        proc = subprocess.Popen(
            [anvil, "--port", str(port), "--silent", "--accounts", "1"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            env=_scrub_env(),
        )
    except OSError:
        return None, ""
    rpc = "http://127.0.0.1:%d" % port
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return None, ""
        if _eth_block_number(rpc) is not None:
            return proc, rpc
        time.sleep(0.1)
    if proc.poll() is None:
        return proc, rpc
    return None, ""


def _start_anvil_fork_safe(
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
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            env=_scrub_env(),
        )
    except OSError:
        return None, rpc_url, None
    fork_rpc = "http://127.0.0.1:%d" % port
    deadline = time.monotonic() + min(8.0, max(2.0, remaining / 4))
    block: Optional[int] = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return None, rpc_url, None
        block = _eth_block_number(fork_rpc)
        if block is not None:
            return proc, fork_rpc, block
        time.sleep(0.15)
    if proc.poll() is None:
        return proc, fork_rpc, _eth_block_number(fork_rpc)
    return None, rpc_url, None


def _rpc(rpc: str, method: str, params: list[Any], timeout: float = 8.0) -> Any:
    from eth_scanner.ingest.rpc_client import rpc_call
    return rpc_call(rpc, method, params, timeout_s=timeout)

def _plant_fixture(rpc: str, kind: str, work: Path) -> str:
    """Compile the in-tree fixture and etch it onto a fixed anvil address. No broadcast."""
    work.mkdir(parents=True, exist_ok=True)
    (work / "src").mkdir(exist_ok=True)
    (work / "src" / "Vaults.sol").write_text(_leaky_sol(), encoding="utf-8")
    (work / "foundry.toml").write_text(
        "\n".join([
            "[profile.default]",
            'src = "src"',
            'out = "out"',
            'libs = ["lib"]',
            'solc = "0.8.20"',
            "optimizer = true",
            "auto_detect_solc = false",
            "",
        ]),
        encoding="utf-8",
    )
    forge = forge_bin()
    if not forge:
        raise RuntimeError("forge missing")
    proc = subprocess.run(
        [forge, "build", "--silent"],
        cwd=str(work),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=_scrub_env(),
    )
    if proc.returncode != 0:
        raise RuntimeError("fixture compile failed: %s" % ((proc.stderr or proc.stdout or "")[-300:]))
    name = "LeakyVault" if kind == "leaky" else "SafeVault"
    art = work / "out" / "Vaults.sol" / ("%s.json" % name)
    data = json.loads(art.read_text(encoding="utf-8"))
    runtime = (
        (data.get("deployedBytecode") or {}).get("object")
        or data.get("deployedBytecode")
        or ""
    )
    if isinstance(runtime, dict):
        runtime = runtime.get("object") or ""
    runtime = str(runtime)
    if not runtime.startswith("0x"):
        runtime = "0x" + runtime
    if len(runtime) < 10:
        raise RuntimeError("empty runtime bytecode for %s" % name)
    addr = PLANT_ADDRESS
    _rpc(rpc, "anvil_setCode", [addr, runtime])
    _rpc(rpc, "anvil_setBalance", [addr, hex(PLANT_WEI)])
    _rpc(rpc, "anvil_setBalance", [ATTACKER_ADDRESS, hex(ATTACKER_WEI)])
    return addr


def _run_forge_verify(
    project: Path,
    fork_rpc: str,
    budget_s: int,
    report: ForkVerifyReport,
) -> None:
    forge = forge_bin()
    if not forge:
        report.status = "skipped"
        report.notes.append("forge not on PATH")
        return
    report.tool = "forge"
    cmd = [
        forge, "test",
        "--fork-url", fork_rpc,
        "--match-contract", "ForkVerifyProperties",
        "--fuzz-runs", str(fuzz_runs()),
        "-vvv",
    ]
    proc = None
    timed_out = False
    blob = ""
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
        blob = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    except subprocess.TimeoutExpired as exc:
        if isinstance(exc.stdout, str):
            blob += exc.stdout
        if isinstance(exc.stderr, str):
            blob += "\n" + exc.stderr
        timed_out = True
    parsed = parse_forge_output(blob)
    failed = [n for n in (parsed.get("failed") or []) if not _is_harness_setup_failure(str(n), blob)]
    if _is_harness_setup_failure("", blob) and not failed:
        # e.g. "No contracts to fuzz" — not a conservation break.
        report.notes.append("ignoring forge harness/setup failure")
    sequence = _sanitize_sequence(_extract_sequence(blob) or "")
    if not sequence and "profit-attacker-balance" in (blob or ""):
        sequence = "profit-attacker-balance"
    if not sequence and failed:
        sequence = "forge fail: %s" % failed[0]
    for name in failed[:8]:
        prop = str(name)
        for pid in report.property_ids:
            if pid.lower().replace("_", "") in prop.lower().replace("_", ""):
                prop = pid
                break
        report.failures.append(ForkVerifyFailure(
            property_id=prop,
            tool="forge",
            reproduction=sequence[:800],
            evidence=("property failed: %s" % name)[:300],
        ))
    report.sequence = sequence[:800]
    # A profit-invariant break is success of the *stage* (drainable), not a tool crash.
    broke = bool(report.failures) or "profit-attacker-balance" in (blob or "")
    if broke:
        report.ran = True
        report.skipped = False
        report.drainable = True
        report.status = "broken"
        report.notes.append("conservation invariant broke on local fork")
        report.notes.append("sequence: %s" % (report.sequence[:240] or "(see forge fail name)"))
    elif timed_out:
        report.ran = True
        report.skipped = False
        report.status = "timeout"
        report.notes.append("forge test timed out after %ss" % budget_s)
    elif proc is not None and proc.returncode != 0:
        report.ran = True
        report.skipped = False
        low = (blob or "").lower()
        if any(tok in low for tok in ("compilation failed", "compiler error", "could not compile")):
            report.status = "compile-skip"
            report.notes.append("fork-verify compile-skip")
        else:
            report.status = "error"
            tail = (blob or "")[-240:].replace("\n", " ").strip()
            report.notes.append("forge test exit=%s — %s" % (proc.returncode, tail[:200]))
    else:
        report.ran = True
        report.skipped = False
        report.status = "ok"
        report.notes.append(
            "forge test exit=0 passed=%s failed=0"
            % parsed.get("passed_n")
        )


def _is_harness_setup_failure(name: str, blob: str) -> bool:
    text = "%s\n%s" % (name, blob or "")
    low = text.lower()
    return any(
        tok in low
        for tok in (
            "no contracts to fuzz",
            "failed to set up invariant",
            "failed to set up invariant testing environment",
            "setUp failed",
            "setup failed",
            "failed to set up",
        )
    )


def _sanitize_sequence(raw: str) -> str:
    text = re.sub(r"\s+", " ", raw or "").strip()
    text = re.sub(r"(?i)(private[_-]?key|mnemonic|secret)[=:\s]+\S+", r"\1=[redacted]", text)
    for stop in (" Suite result:", " Backtrace:", " Failing tests:", " Encountered a total"):
        if stop in text:
            text = text.split(stop, 1)[0].strip()
    return text[:800]
