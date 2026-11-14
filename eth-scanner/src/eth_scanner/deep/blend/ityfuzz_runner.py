"""Ityfuzz on a local anvil fork only.

The argv never enables flashloans, never names a public chain, and never
asks the tool to print a transaction. ETH_RPC_URL must be loopback.
"""

from __future__ import annotations

import os
from typing import Optional
from urllib.parse import urlparse

from eth_scanner.deep.runners import ityfuzz_bin

_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def local_rpc(url: str) -> bool:
    raw = (url or "").strip()
    if not raw:
        return False
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    return parsed.scheme in {"http", "https"} and host in _LOOPBACK


def ityfuzz_argv(bin_path: str, targets: list[str], rpc: str) -> list[str]:
    """Build a read-only local-fork command. Raises if rpc is not loopback."""
    if not local_rpc(rpc):
        raise ValueError("ityfuzz refuses a non-local RPC")
    cleaned = [t.strip() for t in targets if t and t.strip()]
    if not cleaned:
        raise ValueError("ityfuzz needs at least one local target")
    # Pinned invocation. No --flashloan, no broadcast, no exploit printer.
    return [
        bin_path,
        "evm",
        "-t",
        ",".join(cleaned),
        "-c",
        "local",
        "--onchain-block-number",
        "1",
    ]


def ityfuzz_env(rpc: str) -> dict[str, str]:
    if not local_rpc(rpc):
        raise ValueError("ityfuzz refuses a non-local RPC")
    env = {key: value for key, value in os.environ.items() if key not in {"ETH_RPC_URL"}}
    env["ETH_RPC_URL"] = rpc
    return env


def resolve_bin() -> Optional[str]:
    return ityfuzz_bin()
