"""Local-fork value-conservation properties.

A local anvil fork (or a local anvil with no upstream, for fixtures) runs
four Foundry property fuzz tests. Nothing is broadcast. The only stored
result for each property is its name, pass or fail, the measured value
delta, and a hash of those three fields.

Forge's own counterexample text is discarded. A failing property whose
value delta is above HIGH_CONFIDENCE_DELTA is high-confidence evidence.
This stage does not change heat.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from eth_scanner.engines.fuzz_runner import _scrub_env, _stop_anvil
from eth_scanner.engines.fork_verify import _start_anvil_fork_safe, _start_anvil_local


# Raw token units. A larger excess is high-confidence evidence.
HIGH_CONFIDENCE_DELTA = 1000
MAX_CONTRACTS = 5
DEFAULT_LIMIT = 3
DEFAULT_TIMEOUT_S = 60
DEFAULT_FUZZ_RUNS = 8

INVARIANTS = (
    "deposit-redeem",
    "unprivileged-value",
    "donation-price",
    "reentrant-accounting",
)
_LEAD_NAMES = ("share-balance", "spot-price", "reentrancy")
_LINE = re.compile(
    r"^(deposit-redeem|unprivileged-value|donation-price|reentrant-accounting) (pass|fail) (-?\d+)$"
)
_ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")
_FIXTURES = {"fair": 1, "overpay": 2, "donation": 3, "reenter": 4}


def evidence_hash(invariant: str, status: str, value_delta: int) -> str:
    blob = "%s|%s|%s" % (invariant, status, int(value_delta))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def make_record(invariant: str, status: str, value_delta: int) -> dict[str, Any]:
    """The only fields this stage keeps."""
    name = str(invariant)
    flag = "fail" if str(status) == "fail" else "pass"
    delta = int(value_delta)
    return {
        "invariant": name,
        "status": flag,
        "value_delta": delta,
        "evidence_hash": evidence_hash(name, flag, delta),
    }


def high_confidence(records: list[dict[str, Any]]) -> list[str]:
    """Failed properties whose measured delta exceeds the threshold."""
    names: list[str] = []
    for row in records or []:
        if str(row.get("status")) != "fail":
            continue
        try:
            delta = int(row.get("value_delta") or 0)
        except (TypeError, ValueError):
            continue
        if delta > HIGH_CONFIDENCE_DELTA:
            name = str(row.get("invariant") or "")
            if name and name not in names:
                names.append(name)
    return names


def collapse_lines(text: str) -> list[dict[str, Any]]:
    """Keep matching measurement lines. Every other line is dropped."""
    best: dict[str, tuple[str, int]] = {}
    for raw in str(text or "").splitlines():
        match = _LINE.match(raw.strip())
        if not match:
            continue
        name, status, delta_s = match.group(1), match.group(2), int(match.group(3))
        prev = best.get(name)
        if prev is None or (status == "fail" and prev[0] != "fail") or (
            status == prev[0] and delta_s > prev[1]
        ):
            best[name] = (status, delta_s)
    return [make_record(name, best[name][0], best[name][1]) for name in INVARIANTS if name in best]


def lead_names_on_row(row: dict[str, Any]) -> list[str]:
    """Lead names already attached to a stored row. Does not read source heat."""
    found: list[str] = []
    blobs: list[str] = []
    for key in ("leads", "lead_ids", "findings"):
        val = row.get(key)
        if isinstance(val, list):
            blobs.extend(str(item) for item in val)
        elif isinstance(val, str):
            blobs.append(val)
    breakdown = row.get("heat_breakdown")
    if isinstance(breakdown, dict):
        blobs.append(str(breakdown.get("leads") or ""))
    text = " ".join(blobs).lower()
    source = row.get("source")
    if isinstance(source, str) and source.strip():
        from eth_scanner.benchmark.leads import benchmark_lead_names
        for name in benchmark_lead_names(source):
            if name not in found:
                found.append(name)
    for name in _LEAD_NAMES:
        if name in text and name not in found:
            found.append(name)
    return found


def select_targets(rows: list[dict[str, Any]], limit: int = DEFAULT_LIMIT) -> list[dict[str, Any]]:
    """Top rows by heat, then by lead count. Hard cap MAX_CONTRACTS."""
    cap = max(0, min(int(limit), MAX_CONTRACTS))
    ranked: list[tuple[int, int, str, dict[str, Any]]] = []
    for row in rows or []:
        addr = str(row.get("address") or "").lower()
        if not _ADDR.match(addr):
            continue
        heat = int(row.get("heat") or row.get("blend_heat") or 0)
        leads = lead_names_on_row(row)
        if heat <= 0 and not leads:
            continue
        ranked.append((heat, len(leads), addr, row))
    ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _heat, _leads, addr, row in ranked:
        if addr in seen:
            continue
        seen.add(addr)
        out.append(row)
        if len(out) >= cap:
            break
    return out


def apply_conservation(row: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    """Attach the measurement. Heat is left as it was."""
    patched = dict(row)
    breakdown = dict(patched.get("heat_breakdown") or {})
    breakdown["conservation"] = [make_record(r["invariant"], r["status"], int(r["value_delta"])) for r in records]
    patched["heat_breakdown"] = breakdown
    return patched


def _bin(name: str) -> Optional[str]:
    found = shutil.which(name)
    if found:
        return found
    cand = Path.home() / ".foundry" / "bin" / name
    if cand.is_file():
        return str(cand)
    return None


def _timeout(requested: Optional[int]) -> int:
    raw = DEFAULT_TIMEOUT_S if requested is None else int(requested)
    return max(15, min(raw, 90))


def _loopback(url: str) -> bool:
    host = str(url or "").split("://", 1)[-1].split("/", 1)[0].split(":")[0].lower()
    return host in {"127.0.0.1", "localhost"}


def _public_summary(
    *,
    address: str,
    fixture: str,
    ran: bool,
    skipped: bool,
    records: list[dict[str, Any]],
    note: str,
) -> dict[str, Any]:
    return {
        "address": address,
        "fixture": fixture,
        "ran": ran,
        "skipped": skipped,
        "records": records,
        "high_confidence": high_confidence(records),
        "note": note,
    }


def run_conservation(
    *,
    address: str = "",
    rpc_url: str = "",
    fixture: str = "",
    timeout_s: Optional[int] = None,
    work_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """Run the four properties. Never broadcasts, and never calls forge against a public URL."""
    kind = (fixture or "").strip().lower()
    budget = _timeout(timeout_s)
    if kind and kind not in _FIXTURES:
        return _public_summary(
            address="", fixture=kind, ran=False, skipped=True, records=[], note="unknown fixture",
        )
    target = (address or "").strip().lower()
    if not kind and not _ADDR.match(target):
        return _public_summary(
            address=target, fixture="", ran=False, skipped=True, records=[], note="address required",
        )
    if not _bin("forge") or not _bin("anvil"):
        return _public_summary(
            address=target, fixture=kind, ran=False, skipped=True, records=[], note="forge or anvil is not installed",
        )
    if not kind and not (rpc_url or "").strip():
        return _public_summary(
            address=target, fixture="", ran=False, skipped=True, records=[], note="no RPC URL for the local fork",
        )

    base = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="conservation-"))
    base.mkdir(parents=True, exist_ok=True)
    anvil_proc = None
    t0 = time.monotonic()
    try:
        if kind:
            anvil_proc, fork_rpc = _start_anvil_local()
            if anvil_proc is None or not _loopback(fork_rpc):
                return _public_summary(
                    address="", fixture=kind, ran=False, skipped=True, records=[], note="local anvil did not boot",
                )
            harness_target = "0x" + "00" * 20
        else:
            remaining = budget - (time.monotonic() - t0)
            anvil_proc, fork_rpc, _block = _start_anvil_fork_safe(rpc_url, remaining=remaining)
            if anvil_proc is None or not _loopback(fork_rpc):
                return _public_summary(
                    address=target,
                    fixture="",
                    ran=False,
                    skipped=True,
                    records=[],
                    note="local anvil fork did not boot",
                )
            harness_target = target
        project = base / "harness"
        out_file = project / "conservation.out"
        _write_project(project, out_file, harness_target, _FIXTURES.get(kind, 0))
        remaining = budget - (time.monotonic() - t0)
        if remaining < 8:
            return _public_summary(
                address=harness_target if not kind else "",
                fixture=kind,
                ran=False,
                skipped=True,
                records=[],
                note="budget exhausted before the property tests",
            )
        ran, records, note = _run_forge(project, out_file, fork_rpc, int(remaining))
        return _public_summary(
            address=harness_target if kind else target,
            fixture=kind,
            ran=ran,
            skipped=not ran,
            records=records,
            note=note,
        )
    finally:
        _stop_anvil(anvil_proc)


def _run_forge(project: Path, out_file: Path, fork_rpc: str, timeout_s: int) -> tuple[bool, list[dict[str, Any]], str]:
    if not _loopback(fork_rpc):
        return False, [], "refusing a non-local fork URL"
    forge = _bin("forge")
    if not forge:
        return False, [], "forge or anvil is not installed"
    env = _scrub_env()
    env.pop("ETH_RPC_URL", None)
    foundry_bin = str(Path(forge).parent)
    env["PATH"] = foundry_bin + os.pathsep + env.get("PATH", "")
    cmd = [
        forge, "test",
        "--match-contract", "ConservationProperties",
        "--fuzz-runs", str(DEFAULT_FUZZ_RUNS),
        "--fork-url", fork_rpc,
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(project),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return False, [], "property tests timed out"
    except OSError:
        return False, [], "property tests did not start"
    text = out_file.read_text(encoding="utf-8", errors="replace") if out_file.is_file() else ""
    records = collapse_lines(text)
    # proc.stdout and proc.stderr are intentionally discarded.
    del proc.stdout, proc.stderr
    if records:
        return True, records, ""
    if proc.returncode != 0:
        return False, [], "property harness did not finish"
    return True, [], "no measurable deposit or redeem surface"


def _write_project(project: Path, out_file: Path, target: str, fixture: int) -> None:
    if project.exists():
        shutil.rmtree(project)
    (project / "src").mkdir(parents=True)
    (project / "test").mkdir(parents=True)
    (project / "lib" / "forge-std" / "src").mkdir(parents=True)
    _write_std(project / "lib" / "forge-std" / "src")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text("", encoding="utf-8")
    (project / "foundry.toml").write_text(
        "\n".join([
            "[profile.default]",
            'src = "src"',
            'test = "test"',
            'out = "out"',
            'libs = ["lib"]',
            'solc = "0.8.20"',
            "optimizer = false",
            "ffi = false",
            'fs_permissions = [{ access = "read-write", path = "%s" }]' % project.as_posix(),
            "auto_detect_solc = true",
            "",
            "[profile.default.fuzz]",
            "runs = %d" % DEFAULT_FUZZ_RUNS,
            "",
        ]),
        encoding="utf-8",
    )
    (project / "test" / "Conservation.t.sol").write_text(
        _harness(target, fixture, out_file.as_posix()),
        encoding="utf-8",
    )


def _write_std(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "Vm.sol").write_text(
        "\n".join([
            "// SPDX-License-Identifier: MIT",
            "pragma solidity >=0.6.2 <0.9.0;",
            "interface Vm {",
            "    function deal(address account, uint256 newBalance) external;",
            "    function load(address account, bytes32 slot) external view returns (bytes32);",
            "    function store(address account, bytes32 slot, bytes32 value) external;",
            "    function writeLine(string calldata path, string calldata data) external;",
            "}",
            "",
        ]),
        encoding="utf-8",
    )
    (dest / "Test.sol").write_text(
        "\n".join([
            "// SPDX-License-Identifier: MIT",
            "pragma solidity >=0.6.2 <0.9.0;",
            'import {Vm} from "./Vm.sol";',
            "abstract contract Test {",
            '    Vm internal constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));',
            "    function bound(uint256 x, uint256 minV, uint256 maxV) internal pure returns (uint256) {",
            "        if (minV > maxV) { (minV, maxV) = (maxV, minV); }",
            "        if (maxV == minV) return minV;",
            "        return minV + (x % (maxV - minV + 1));",
            "    }",
            "}",
            "",
        ]),
        encoding="utf-8",
    )


def _harness(target: str, fixture: int, out_path: str) -> str:
    addr = target.lower().replace("0x", "")
    if len(addr) != 40:
        addr = "00" * 20
    # The property fixtures are local stand-ins so the measurements have a
    # pass case and a fail case. They are not live contracts.
    return r'''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test} from "forge-std/Test.sol";

contract AccountingObserver {
    uint256 public beforeAssets;
    uint256 public beforeSupply;
    uint256 public seenAssets;
    uint256 public seenSupply;
    bool public seen;
    int256 public delta;

    function arm(address target) external {
        beforeAssets = _view(target, "totalAssets()");
        beforeSupply = _view(target, "totalSupply()");
        seen = false;
        delta = 0;
    }

    function perform(address to, bytes calldata data, uint256 value) external returns (bool) {
        (bool ok,) = to.call{value: value}(data);
        return ok;
    }

    receive() external payable {
        seen = true;
        uint256 assets = _view(msg.sender, "totalAssets()");
        uint256 supply = _view(msg.sender, "totalSupply()");
        seenAssets = assets;
        seenSupply = supply;
        if (assets >= beforeAssets) delta = int256(assets - beforeAssets);
        else delta = -int256(beforeAssets - assets);
    }

    function _view(address to, string memory sig) internal view returns (uint256) {
        (bool ok, bytes memory data) = to.staticcall(abi.encodeWithSignature(sig));
        if (!ok || data.length < 32) return 0;
        return abi.decode(data, (uint256));
    }
}

contract FairVault {
    mapping(address => uint256) public balanceOf;
    uint256 public totalSupply;
    receive() external payable {}
    function deposit() external payable {
        balanceOf[msg.sender] += msg.value;
        totalSupply += msg.value;
    }
    function convertToAssets(uint256 shares) external pure returns (uint256) { return shares; }
    function totalAssets() external view returns (uint256) { return address(this).balance; }
    function redeem(uint256 shares, address receiver, address owner) external returns (uint256) {
        require(balanceOf[owner] >= shares, "shares");
        balanceOf[owner] -= shares;
        totalSupply -= shares;
        (bool ok,) = receiver.call{value: shares}("");
        require(ok, "pay");
        return shares;
    }
}

contract OverpayVault {
    mapping(address => uint256) public balanceOf;
    uint256 public totalSupply;
    receive() external payable {}
    function deposit() external payable {
        balanceOf[msg.sender] += msg.value;
        totalSupply += msg.value;
    }
    function convertToAssets(uint256 shares) external pure returns (uint256) { return shares; }
    function totalAssets() external view returns (uint256) { return address(this).balance; }
    function redeem(uint256 shares, address receiver, address owner) external returns (uint256) {
        require(balanceOf[owner] >= shares, "shares");
        balanceOf[owner] -= shares;
        totalSupply -= shares;
        uint256 pay = shares + 1 ether;
        (bool ok,) = receiver.call{value: pay}("");
        require(ok, "pay");
        return pay;
    }
}

contract DonationVault {
    mapping(address => uint256) public balanceOf;
    uint256 public totalSupply;
    receive() external payable {}
    function deposit() external payable {
        balanceOf[msg.sender] += msg.value;
        totalSupply += msg.value;
    }
    function totalAssets() external view returns (uint256) { return address(this).balance; }
    function convertToAssets(uint256 shares) external view returns (uint256) {
        if (totalSupply == 0) return shares;
        return shares * address(this).balance / totalSupply;
    }
    function redeem(uint256 shares, address receiver, address owner) external returns (uint256) {
        require(balanceOf[owner] >= shares, "shares");
        balanceOf[owner] -= shares;
        totalSupply -= shares;
        (bool ok,) = receiver.call{value: shares}("");
        require(ok, "pay");
        return shares;
    }
}

contract ReenterVault {
    mapping(address => uint256) public balanceOf;
    uint256 public totalSupply;
    receive() external payable {}
    function deposit() external payable {
        balanceOf[msg.sender] += msg.value;
        totalSupply += msg.value;
    }
    function convertToAssets(uint256 shares) external pure returns (uint256) { return shares; }
    function totalAssets() external view returns (uint256) { return address(this).balance; }
    function redeem(uint256 shares, address receiver, address owner) external returns (uint256) {
        require(balanceOf[owner] >= shares, "shares");
        (bool ok,) = receiver.call{value: shares}("");
        require(ok, "pay");
        balanceOf[owner] -= shares;
        totalSupply -= shares;
        return shares;
    }
}

contract ConservationProperties is Test {
    address constant TARGET = address(bytes20(hex"%s"));
    uint256 constant FIXTURE = %d;
    string constant OUT = "%s";

    AccountingObserver internal actor;
    address internal target;

    function setUp() public {
        actor = new AccountingObserver();
        if (FIXTURE == 1) target = address(new FairVault());
        else if (FIXTURE == 2) {
            target = address(new OverpayVault());
            vm.deal(target, 10 ether);
        } else if (FIXTURE == 3) target = address(new DonationVault());
        else if (FIXTURE == 4) target = address(new ReenterVault());
        else target = TARGET;
    }

    function testFuzz_deposit_redeem(uint256 raw) public {
        (bool ok, int256 delta, bool failed) = _roundTrip(_boundAmount(raw));
        if (ok) _write("deposit-redeem", failed, delta);
    }

    function testFuzz_unprivileged_value(uint256 raw) public {
        (bool ok, int256 delta, bool failed) = _unprivileged(_boundAmount(raw));
        if (ok) _write("unprivileged-value", failed, delta);
    }

    function testFuzz_donation_price(uint256 raw) public {
        (bool ok, int256 delta, bool failed) = _donation(_boundAmount(raw));
        if (ok) _write("donation-price", failed, delta);
    }

    function testFuzz_reentrant_accounting(uint256 raw) public {
        (bool ok, int256 delta, bool failed) = _reenter(_boundAmount(raw));
        if (ok) _write("reentrant-accounting", failed, delta);
    }

    function _boundAmount(uint256 raw) internal view returns (uint256) {
        uint256 cap = 1 ether;
        (bool ok, uint256 assets) = _staticUint(target, "totalAssets()");
        if (ok && assets > 1000) {
            uint256 slice = assets / 100;
            if (slice < cap && slice > 0) cap = slice;
        }
        if (cap < 1000) return bound(raw, 1, cap < 1 ? 1 : cap);
        return bound(raw, 1000, cap);
    }

    function _round(uint256 amount) internal pure returns (uint256) {
        uint256 rel = amount / 1000;
        return rel > 1 ? rel : 1;
    }

    function _roundTrip(uint256 amount) internal returns (bool, int256, bool) {
        if (!_fund(amount)) return (false, 0, false);
        uint256 beforeBal = _actorAssets();
        if (!_deposit(amount)) return (false, 0, false);
        if (!_redeemAll()) return (false, 0, false);
        int256 delta = int256(_actorAssets()) - int256(beforeBal);
        return (true, delta, delta > int256(_round(amount)));
    }

    function _unprivileged(uint256 amount) internal returns (bool, int256, bool) {
        if (!_fund(amount)) return (false, 0, false);
        uint256 beforeBal = _actorAssets();
        uint256 vaultBefore = _vaultAssets();
        if (!_deposit(amount)) return (false, 0, false);
        if (!_redeemAll()) return (false, 0, false);
        int256 gain = int256(_actorAssets()) - int256(beforeBal);
        uint256 vaultAfter = _vaultAssets();
        uint256 loss = vaultBefore > vaultAfter ? vaultBefore - vaultAfter : 0;
        uint256 allowance = _round(amount);
        bool failed = gain > int256(allowance) && loss > allowance;
        return (true, gain, failed);
    }

    function _donation(uint256 amount) internal returns (bool, int256, bool) {
        if (!_fund(amount)) return (false, 0, false);
        if (!_deposit(amount)) return (false, 0, false);
        uint256 price0 = _price();
        if (price0 == 0) return (false, 0, false);
        if (!_donate(amount)) return (false, 0, false);
        uint256 price1 = _price();
        int256 delta = int256(price1) - int256(price0);
        uint256 allowance = price0 / 1000;
        if (allowance < 1) allowance = 1;
        return (true, delta, delta > int256(allowance));
    }

    function _reenter(uint256 amount) internal returns (bool, int256, bool) {
        if (!_fund(amount)) return (false, 0, false);
        if (!_deposit(amount)) return (false, 0, false);
        actor.arm(target);
        uint256 beforeAssets = actor.beforeAssets();
        uint256 beforeSupply = actor.beforeSupply();
        if (!_redeemAll()) return (false, 0, false);
        if (!actor.seen()) return (true, 0, false);
        (bool okA, uint256 afterAssets) = _staticUint(target, "totalAssets()");
        (bool okS, uint256 afterSupply) = _staticUint(target, "totalSupply()");
        if (!okA || !okS) return (true, 0, false);
        bool matchBefore = actor.seenAssets() == beforeAssets && actor.seenSupply() == beforeSupply;
        bool matchAfter = actor.seenAssets() == afterAssets && actor.seenSupply() == afterSupply;
        if (matchBefore || matchAfter) return (true, 0, false);
        int256 gap = actor.delta();
        if (gap < 0) gap = -gap;
        return (true, gap, gap > int256(_round(amount)));
    }

    function _asset() internal view returns (address) {
        address found = _staticAddr(target, "asset()");
        if (found != address(0)) return found;
        found = _staticAddr(target, "token()");
        if (found != address(0)) return found;
        return _staticAddr(target, "underlying()");
    }

    function _fund(uint256 amount) internal returns (bool) {
        address asset = _asset();
        if (asset == address(0)) {
            vm.deal(address(actor), amount + 1 ether);
            return true;
        }
        return _dealToken(asset, address(actor), amount);
    }

    function _dealToken(address token, address to, uint256 give) internal returns (bool) {
        for (uint256 slot = 0; slot < 32; slot++) {
            bytes32 key = keccak256(abi.encode(to, slot));
            bytes32 raw = vm.load(token, key);
            uint256 current = uint256(raw);
            uint256 bal = _balanceOf(token, to);
            if (current != bal) continue;
            vm.store(token, key, bytes32(give));
            if (_balanceOf(token, to) == give) return true;
            vm.store(token, key, raw);
        }
        return false;
    }

    function _actorAssets() internal view returns (uint256) {
        address asset = _asset();
        if (asset == address(0)) return address(actor).balance;
        return _balanceOf(asset, address(actor));
    }

    function _vaultAssets() internal view returns (uint256) {
        address asset = _asset();
        if (asset == address(0)) return target.balance;
        return _balanceOf(asset, target);
    }

    function _deposit(uint256 amount) internal returns (bool) {
        address asset = _asset();
        if (asset != address(0)) {
            if (!actor.perform(asset, abi.encodeWithSignature("approve(address,uint256)", target, amount), 0)) {
                return false;
            }
            if (actor.perform(target, abi.encodeWithSignature("deposit(uint256,address)", amount, address(actor)), 0)) {
                return true;
            }
            return actor.perform(target, abi.encodeWithSignature("deposit(uint256)", amount), 0);
        }
        if (actor.perform(target, abi.encodeWithSignature("deposit()"), amount)) return true;
        return actor.perform(target, abi.encodeWithSignature("deposit(uint256)", amount), amount);
    }

    function _redeemAll() internal returns (bool) {
        uint256 shares = _balanceOf(target, address(actor));
        if (shares == 0) return false;
        if (actor.perform(target, abi.encodeWithSignature("redeem(uint256,address,address)", shares, address(actor), address(actor)), 0)) {
            return true;
        }
        if (actor.perform(target, abi.encodeWithSignature("withdraw(uint256)", shares), 0)) return true;
        return actor.perform(target, abi.encodeWithSignature("redeem()"), 0);
    }

    function _donate(uint256 amount) internal returns (bool) {
        Donor fresh = new Donor();
        address asset = _asset();
        if (asset == address(0)) {
            vm.deal(address(fresh), amount);
            return fresh.giveEth(target, amount);
        }
        if (!_dealToken(asset, address(fresh), amount)) return false;
        return fresh.giveToken(asset, target, amount);
    }

    function _price() internal view returns (uint256) {
        (bool ok, uint256 supply) = _staticUint(target, "totalSupply()");
        if (!ok || supply == 0) return 0;
        (bool okC, bytes memory data) = target.staticcall(abi.encodeWithSignature("convertToAssets(uint256)", uint256(1e18)));
        if (okC && data.length >= 32) return abi.decode(data, (uint256));
        (bool okA, uint256 assets) = _staticUint(target, "totalAssets()");
        if (!okA || assets == 0) return 0;
        return assets * 1e18 / supply;
    }

    function _balanceOf(address token, address account) internal view returns (uint256) {
        (bool ok, bytes memory data) = token.staticcall(abi.encodeWithSignature("balanceOf(address)", account));
        if (!ok || data.length < 32) return 0;
        return abi.decode(data, (uint256));
    }

    function _staticUint(address to, string memory sig) internal view returns (bool, uint256) {
        (bool ok, bytes memory data) = to.staticcall(abi.encodeWithSignature(sig));
        if (!ok || data.length < 32) return (false, 0);
        return (true, abi.decode(data, (uint256)));
    }

    function _staticAddr(address to, string memory sig) internal view returns (address) {
        (bool ok, bytes memory data) = to.staticcall(abi.encodeWithSignature(sig));
        if (!ok || data.length < 32) return address(0);
        return abi.decode(data, (address));
    }

    function _write(string memory name, bool failed, int256 delta) internal {
        string memory status = failed ? "fail" : "pass";
        vm.writeLine(OUT, string.concat(name, " ", status, " ", _i(delta)));
    }

    function _i(int256 v) internal pure returns (string memory) {
        if (v < 0) return string.concat("-", _u(uint256(-v)));
        return _u(uint256(v));
    }

    function _u(uint256 v) internal pure returns (string memory) {
        if (v == 0) return "0";
        bytes memory buf = new bytes(78);
        uint256 i = 78;
        while (v > 0) {
            i--;
            buf[i] = bytes1(uint8(48 + (v %% 10)));
            v /= 10;
        }
        bytes memory out = new bytes(78 - i);
        for (uint256 j = 0; j < out.length; j++) out[j] = buf[i + j];
        return string(out);
    }
}

contract Donor {
    function giveEth(address target, uint256 amount) external returns (bool) {
        (bool ok,) = target.call{value: amount}("");
        return ok;
    }

    function giveToken(address token, address target, uint256 amount) external returns (bool) {
        (bool ok,) = token.call(abi.encodeWithSignature("transfer(address,uint256)", target, amount));
        return ok;
    }
}
''' % (addr, int(fixture), out_path)
