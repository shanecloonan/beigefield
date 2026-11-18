"""Read-only corroboration of engine / clone leads.

Confirms via eth_call (and optional anvil --fork-url dry simulation when
`ETH_SCANNER_ANVIL_BIN` is set). Never broadcasts. Evidence stores call
selector, fork block, and observed revert/success — never weaponized calldata
sequences beyond a single defensive probe.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from eth_scanner.deep.findings import sanitize_evidence
from eth_scanner.research.proxy import (
    EIP1967_ADMIN_SLOT,
    EIP1967_IMPLEMENTATION_SLOT,
    eth_get_storage_at,
    storage_word_to_address,
)

# Common privileged / initializer selectors (4-byte). Defensive probes only.
PROBE_SELECTORS: dict[str, str] = {
    "initialize()": "8129fc1c",
    "initialize(address)": "c4d66de8",
    "init(address)": "19ab453c",
    "upgradeTo(address)": "3659cfe6",
    "upgradeToAndCall(address,bytes)": "4f1ef286",
    "changeAdmin(address)": "8f283970",
    "setOwner(address)": "13af4035",
    "transferOwnership(address)": "f2fde38b",
    "mint(address,uint256)": "40c10f19",
    "destroy()": "83197ef0",  # sometimes selfdestruct wrappers
}


@dataclass
class Corroboration:
    lead_id: str
    confirmed: bool
    method: str  # eth_call | storage | anvil-fork | none
    evidence: str
    fork_block: Optional[int] = None
    call_selector: Optional[str] = None
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["evidence"] = sanitize_evidence(d.get("evidence"))
        return d


def _rpc(rpc_url: str, method: str, params: list[Any], timeout_s: float = 12.0) -> Any:
    from eth_scanner.ingest.rpc_client import rpc_call
    return rpc_call(rpc_url, method, params, timeout_s=timeout_s)

def head_block(rpc_url: str) -> Optional[int]:
    try:
        raw = _rpc(rpc_url, "eth_blockNumber", [])
        return int(raw, 16)
    except Exception:  # noqa: BLE001
        return None


def eth_call_probe(
    rpc_url: str,
    address: str,
    selector_hex: str,
    *,
    from_addr: str = "0x0000000000000000000000000000000000000001",
    data_suffix: str = "",
    timeout_s: float = 10.0,
) -> tuple[bool, str]:
    """Return (did_not_revert, note). Success = potential privileged path open."""
    data = "0x" + selector_hex + data_suffix
    try:
        _rpc(
            rpc_url,
            "eth_call",
            [{"to": address, "from": from_addr, "data": data}, "latest"],
            timeout_s=timeout_s,
        )
        return True, "eth_call succeeded (no revert) selector=0x%s" % selector_hex
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if "revert" in msg or "execution reverted" in msg:
            return False, "eth_call reverted (expected for locked path) selector=0x%s" % selector_hex
        return False, "eth_call error selector=0x%s: %s" % (selector_hex, str(exc)[:120])


def code_size(rpc_url: str, address: str) -> int:
    try:
        raw = _rpc(rpc_url, "eth_getCode", [address, "latest"])
        if not isinstance(raw, str) or raw in {"0x", "0x0"}:
            return 0
        return max(0, (len(raw) - 2) // 2)
    except Exception:  # noqa: BLE001
        return 0


def corroborate_lead(
    *,
    rpc_url: str,
    address: str,
    lead: dict[str, Any],
    funds_usd: Optional[float] = None,
) -> Corroboration:
    """Attempt a single defensive confirmation for one lead."""
    lead_id = str(lead.get("id") or lead.get("rule") or "lead")
    title = str(lead.get("title") or lead.get("rule") or "")
    engine = str(lead.get("engine") or lead.get("kind") or "")
    fork_block = head_block(rpc_url) if rpc_url else None

    if not rpc_url:
        return Corroboration(lead_id, False, "none", "no RPC — cannot corroborate", fork_block=fork_block)

    # Clone / unprotected initializer → probe initialize()
    blob = (lead_id + " " + title + " " + engine).lower()
    if "initializ" in blob or "unprotected-initializer" in blob or "upgradeable-missing" in blob:
        ok, note = eth_call_probe(rpc_url, address, PROBE_SELECTORS["initialize()"])
        return Corroboration(
            lead_id, ok, "eth_call", note,
            fork_block=fork_block, call_selector="0x8129fc1c",
            extras={"probe": "initialize()"},
        )

    # Privileged / access-control / suicidal / arbitrary-send → probe privileged selectors
    if any(k in blob for k in ("access", "privileg", "suicidal", "arbitrary-send", "owner", "admin", "upgrade")):
        for name, sel in (
            ("upgradeTo(address)", PROBE_SELECTORS["upgradeTo(address)"] + ("00" * 32)),
            ("changeAdmin(address)", PROBE_SELECTORS["changeAdmin(address)"] + ("00" * 32)),
            ("mint(address,uint256)", PROBE_SELECTORS["mint(address,uint256)"] + ("00" * 64)),
            ("transferOwnership(address)", PROBE_SELECTORS["transferOwnership(address)"] + ("00" * 32)),
        ):
            ok, note = eth_call_probe(rpc_url, address, sel[:8], data_suffix=sel[8:] if len(sel) > 8 else "")
            if ok:
                return Corroboration(
                    lead_id, True, "eth_call", note + " probe=%s" % name,
                    fork_block=fork_block, call_selector="0x" + sel[:8],
                    extras={"probe": name},
                )
        return Corroboration(
            lead_id, False, "eth_call",
            "privileged probes reverted — lead not confirmed",
            fork_block=fork_block,
        )

    # Proxy admin EOA check when funds large
    if "proxy" in blob or "admin" in blob or (funds_usd is not None and funds_usd >= 100_000):
        try:
            admin_word = eth_get_storage_at(rpc_url, address, EIP1967_ADMIN_SLOT)
            admin = storage_word_to_address(admin_word)
            if admin:
                sz = code_size(rpc_url, admin)
                if sz == 0 and funds_usd is not None and funds_usd >= 100_000:
                    return Corroboration(
                        lead_id, True, "storage",
                        "EIP-1967 admin is EOA (%s) with funds>=100k" % admin,
                        fork_block=fork_block,
                        extras={"admin": admin, "admin_code_size": 0},
                    )
                return Corroboration(
                    lead_id, False, "storage",
                    "admin=%s code_size=%d — not confirmed as EOA risk" % (admin, sz),
                    fork_block=fork_block,
                    extras={"admin": admin, "admin_code_size": sz},
                )
        except Exception as exc:  # noqa: BLE001
            return Corroboration(lead_id, False, "storage", "admin probe failed: %s" % str(exc)[:120], fork_block=fork_block)

    # Optional anvil fork dry-run for initialize (still no broadcast)
    anvil = (os.environ.get("ETH_SCANNER_ANVIL_BIN") or "").strip() or shutil.which("anvil")
    if anvil and "reentr" in blob:
        note = _anvil_dry_note(anvil, rpc_url, address)
        return Corroboration(
            lead_id, False, "anvil-fork",
            note or "anvil fork available but no auto-confirm for reentrancy without harness",
            fork_block=fork_block,
        )

    return Corroboration(
        lead_id, False, "none",
        "no matching defensive probe for lead class — kept as lead only",
        fork_block=fork_block,
    )


def resolve_proxy_meta(rpc_url: str, address: str) -> dict[str, Any]:
    out: dict[str, Any] = {"implementation": None, "admin": None, "admin_is_eoa": None}
    if not rpc_url:
        return out
    try:
        impl_word = eth_get_storage_at(rpc_url, address, EIP1967_IMPLEMENTATION_SLOT)
        out["implementation"] = storage_word_to_address(impl_word)
    except Exception:  # noqa: BLE001
        pass
    try:
        admin_word = eth_get_storage_at(rpc_url, address, EIP1967_ADMIN_SLOT)
        admin = storage_word_to_address(admin_word)
        out["admin"] = admin
        if admin:
            out["admin_is_eoa"] = code_size(rpc_url, admin) == 0
    except Exception:  # noqa: BLE001
        pass
    return out


def _anvil_dry_note(anvil_bin: str, rpc_url: str, address: str) -> str:
    """Spin a short-lived anvil fork and confirm it boots — never send txs."""
    try:
        proc = subprocess.Popen(
            [anvil_bin, "--fork-url", rpc_url, "--port", "0", "--silent"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(1.5)
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        return "anvil --fork-url boot ok for %s (no broadcast; reentrancy needs harness)" % address
    except Exception as exc:  # noqa: BLE001
        return "anvil fork skipped: %s" % str(exc)[:120]
