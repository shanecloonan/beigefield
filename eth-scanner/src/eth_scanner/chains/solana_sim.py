"""Optional local Solana simulation. Never a mainnet transaction.

The only RPC this module will hand to a validator is a loopback URL.
A public or hosted URL is refused before any process is started. When
solana-test-validator is not installed, the result is a skipped plan.
"""

from __future__ import annotations

import shutil
from typing import Any, Callable, Optional

from eth_scanner.chains.registry import normalize_solana_address
from eth_scanner.deep.blend.ityfuzz_runner import local_rpc

Runner = Callable[[list[str]], dict[str, Any]]


def plan_sim(
    address: str,
    *,
    rpc: str = "",
    clones: Optional[list[str]] = None,
    execute: bool = False,
    runner: Optional[Runner] = None,
    binary: Optional[str] = None,
) -> dict[str, Any]:
    """Plan a local validator. heat_contribution is 0. Nothing is broadcast."""
    program = normalize_solana_address(address)
    report: dict[str, Any] = {
        "chain": "solana",
        "address": program,
        "heat_contribution": 0,
        "executed": False,
        "skipped": False,
        "refused": False,
        "argv": None,
        "note": "Local validator plan only. No transaction is sent.",
    }
    if not local_rpc(rpc):
        report["refused"] = True
        report["skipped"] = True
        report["reason"] = "refuses a non-local RPC"
        return report
    extra = [normalize_solana_address(item) for item in (clones or []) if str(item).strip()]
    resolved = shutil.which("solana-test-validator") if binary is None else (binary or None)
    argv = validator_argv(resolved or "solana-test-validator", program, rpc, extra)
    report["argv"] = argv
    if resolved is None:
        report["skipped"] = True
        report["reason"] = "solana-test-validator is not installed"
        return report
    if not execute:
        report["skipped"] = True
        report["reason"] = "plan only; pass --run to start a local validator"
        return report
    launch = runner or _run_local
    outcome = launch(argv)
    report["executed"] = True
    report["result"] = outcome
    report["heat_contribution"] = 0
    return report


def validator_argv(binary: str, program: str, rpc: str, clones: list[str]) -> list[str]:
    """Argv for a loopback validator. Raises if any URL is not local."""
    if not local_rpc(rpc):
        raise ValueError("solana sim refuses a non-local RPC")
    argv = [
        binary,
        "--reset",
        "--bind-address",
        "127.0.0.1",
        "--rpc-port",
        "8899",
        "--url",
        rpc,
        "--clone-upgradeable-program",
        program,
    ]
    for account in clones:
        argv.extend(["--clone", account])
    if _unsafe(argv):
        raise ValueError("solana sim refuses a non-local RPC")
    return argv


def _unsafe(argv: list[str]) -> bool:
    for arg in argv:
        if "sendTransaction" in arg or "requestAirdrop" in arg:
            return True
        if arg.startswith("http://") or arg.startswith("https://"):
            if not local_rpc(arg):
                return True
    return False


def _run_local(argv: list[str]) -> dict[str, Any]:
    """Start a local validator and stop it. The argv is loopback-only."""
    import subprocess

    if _unsafe(argv):
        raise ValueError("solana sim refuses a non-local RPC")
    proc = subprocess.Popen(
        argv,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
    return {"returncode": proc.returncode, "heat_contribution": 0, "sent": False}
