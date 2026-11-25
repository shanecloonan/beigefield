"""Local Foundry fork plan for one EVM chain. Nothing is broadcast.

The report never includes the RPC URL. ``--run`` starts ``anvil`` on
127.0.0.1 only long enough to read ``eth_chainId``, then stops it.
A missing binary, a missing URL, or a chain-id mismatch skips the run.
Ethereum still uses only ETH_RPC_URL.
"""

from __future__ import annotations

import shutil
from typing import Any, Callable, Optional

from eth_scanner.chains.evm import evm_chain, rpc_choice

Runner = Callable[[list[str]], dict[str, Any]]


def plan_fork(
    chain: str,
    *,
    execute: bool = False,
    runner: Optional[Runner] = None,
    binary: Optional[str] = None,
) -> dict[str, Any]:
    """Plan a loopback anvil fork. heat_contribution is 0."""
    cfg = evm_chain(chain)
    choice = rpc_choice(cfg.name)
    report: dict[str, Any] = {
        "chain": cfg.name,
        "chain_id": cfg.chain_id,
        "rpc_source": choice["source"],
        "rpc_env": choice["env"],
        "heat_contribution": 0,
        "executed": False,
        "skipped": False,
        "refused": False,
        "binds_loopback": True,
        "argv": ["anvil", "--fork-url", "<rpc>", "--host", "127.0.0.1", "--port", "8545", "--accounts", "0"],
        "note": "Local anvil fork plan. No transaction is sent.",
    }
    if not choice["url"]:
        report["skipped"] = True
        report["reason"] = "%s is unset" % cfg.rpc_env
        return report
    resolved = shutil.which("anvil") if binary is None else (binary or None)
    argv = _argv(resolved or "anvil", choice["url"])
    if _unsafe(argv):
        report["refused"] = True
        report["skipped"] = True
        report["reason"] = "fork plan refuses a non-loopback bind"
        return report
    if not execute:
        report["skipped"] = True
        report["reason"] = "plan only"
        return report
    if resolved is None:
        report["skipped"] = True
        report["reason"] = "anvil is not installed"
        return report
    launch = runner or _run_local
    outcome = launch(argv)
    report["executed"] = True
    report["result"] = {k: v for k, v in outcome.items() if k != "argv"}
    report["heat_contribution"] = 0
    if outcome.get("chain_id") not in {None, cfg.chain_id}:
        report["refused"] = True
        report["reason"] = "fork chain id did not match"
    return report


def _argv(binary: str, rpc_url: str) -> list[str]:
    return [
        binary,
        "--fork-url",
        rpc_url,
        "--host",
        "127.0.0.1",
        "--port",
        "8545",
        "--accounts",
        "0",
        "--silent",
    ]


def _unsafe(argv: list[str]) -> bool:
    if "--host" not in argv or argv[argv.index("--host") + 1] != "127.0.0.1":
        return True
    for arg in argv:
        if "sendTransaction" in arg or "eth_send" in arg:
            return True
    return False


def _run_local(argv: list[str]) -> dict[str, Any]:
    """Start anvil, read the loopback chain id, and stop it. No transaction."""
    import json
    import socket
    import subprocess
    import time
    import urllib.request

    if _unsafe(argv):
        raise ValueError("fork plan refuses a non-loopback bind")
    proc = subprocess.Popen(
        argv,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    observed = None
    try:
        deadline = time.monotonic() + 8
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_chainId", "params": []}).encode()
        while time.monotonic() < deadline and proc.poll() is None:
            try:
                req = urllib.request.Request(
                    "http://127.0.0.1:8545",
                    data=body,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=1) as resp:
                    payload = json.loads(resp.read().decode("utf-8", errors="replace"))
                raw = str((payload or {}).get("result") or "")
                observed = int(raw, 16) if raw.startswith("0x") else None
                break
            except (OSError, socket.timeout, ValueError, json.JSONDecodeError):
                time.sleep(0.2)
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
    return {"chain_id": observed, "sent": False, "heat_contribution": 0}
