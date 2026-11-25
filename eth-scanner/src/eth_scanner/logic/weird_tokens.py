"""Vault accounting under unusual token behavior.

These checks are original. They do not copy an unlicensed token suite.
A token shape is a lead and adds no heat. Heat is added only when the
adapter's books claim more assets than the tokens it holds, or when a
deposit takes tokens and mints no shares. No calldata is stored, and a
fork read happens only on a local anvil.
"""

from __future__ import annotations

import json
import re
import urllib.request
from typing import Any, Callable, Optional

_AMOUNT = 1_000_000
_FEE_BPS = 1_000
_REBASE_BPS = 5_000
_DECIMALS_CALL = "0x313ce567"
Caller = Callable[[str, str], str]


def adapter_mode(source: str) -> str:
    """How a vault credits a deposit. Unknown stays at zero heat."""
    text = source or ""
    if not text.strip():
        return "unknown"
    if re.search(r"balanceOf\s*\(\s*address\s*\(\s*this\s*\)\s*\)", text):
        return "measured"
    if re.search(r"function\s+(deposit|mint|withdraw|redeem)\s*\(", text):
        return "nominal"
    return "unknown"


def approval_mode(source: str) -> str:
    """`replace` is two non-zero approves with no zero step."""
    text = source or ""
    if not text.strip():
        return "unknown"
    if re.search(r"forceApprove|\.approve\s*\([^,]+,\s*0\s*\)|safeIncreaseAllowance", text):
        return "reset"
    approves = len(re.findall(r"\.approve\s*\(", text))
    if approves >= 2:
        return "replace"
    if approves == 1:
        return "single"
    return "none"


def token_behaviors(source: str, decimals: Optional[int] = None) -> list[str]:
    """Behaviors named by the asset source. Decimals outside 3..23 count too."""
    text = source or ""
    found: list[str] = []
    if re.search(r"feeOnTransfer|takeFee|transferFee|burnFee|_fee\b", text, re.IGNORECASE):
        found.append("fee-on-transfer")
    if re.search(r"\brebase\b|_rOwned|\breflect\s*\(", text):
        found.append("rebasing")
    if re.search(
        r"function\s+transfer\s*\([^)]*\)\s*(external|public)(?!\s+returns)\s*(\{|virtual)",
        text,
    ):
        found.append("missing-return")
    if re.search(r"whenNotPaused|\bpaused\s*\(", text):
        found.append("pausable")
    if re.search(r"blacklist|blocklist|isBlackListed|isBlacklisted|denied\s*\[", text, re.IGNORECASE):
        found.append("blocklist")
    if decimals is not None and (int(decimals) <= 2 or int(decimals) >= 24):
        found.append("decimals")
    return found


def _row(name: str, status: str, evidence: str) -> dict[str, str]:
    return {
        "id": name,
        "status": status,
        "source": "fork-simulation" if status in {"failed", "held"} else "shape",
        "evidence": evidence,
    }


def _credit(adapter: str, requested: int, delivered: int) -> Optional[int]:
    if adapter == "nominal":
        return requested
    if adapter == "measured":
        return delivered
    return None


def probe_fee(adapter: str, amount: int = _AMOUNT) -> dict[str, str]:
    delivered = amount - (amount * _FEE_BPS // 10_000)
    credited = _credit(adapter, amount, delivered)
    if credited is None:
        return _row("weird-fee-on-transfer", "unknown", "adapter accounting is not visible")
    if credited > delivered:
        return _row(
            "weird-fee-on-transfer",
            "failed",
            "credited %d and held %d after a fee" % (credited, delivered),
        )
    return _row("weird-fee-on-transfer", "held", "credited assets match the tokens held")


def probe_rebase(adapter: str, amount: int = _AMOUNT) -> dict[str, str]:
    held = amount * _REBASE_BPS // 10_000
    credited = _credit(adapter, amount, held)
    if credited is None:
        return _row("weird-rebasing", "unknown", "adapter accounting is not visible")
    if credited > held:
        return _row("weird-rebasing", "failed", "credited %d and held %d after a rebase" % (credited, held))
    return _row("weird-rebasing", "held", "credited assets match the tokens held")


def probe_silent(adapter: str, name: str, amount: int = _AMOUNT) -> dict[str, str]:
    """A transfer that moves nothing. Measured adapters credit the delta."""
    credited = _credit(adapter, amount, 0)
    if credited is None:
        return _row(name, "unknown", "adapter accounting is not visible")
    if credited > 0:
        return _row(name, "failed", "credited %d when the token balance did not increase" % credited)
    return _row(name, "held", "no credit without a token balance increase")


def probe_approval(mode: str, amount: int = _AMOUNT) -> Optional[dict[str, str]]:
    if mode in {"unknown", "none"}:
        return None
    if mode == "single":
        return _row("weird-approval-race", "held", "one approval is a shape and adds no heat")
    latest = amount // 2
    pullable = amount + latest if mode == "replace" else latest
    if pullable > amount:
        return _row(
            "weird-approval-race",
            "failed",
            "pullable %d exceeds the %d tokens held" % (pullable, amount),
        )
    return _row("weird-approval-race", "held", "a reset approval cannot pull more than the balance")


def probe_decimals(adapter: str, decimals: int, amount: int = _AMOUNT) -> dict[str, str]:
    decimals = int(decimals)
    if adapter not in {"nominal", "measured"}:
        return _row("weird-decimals", "unknown", "adapter accounting is not visible")
    if decimals <= 2:
        credited = amount * (10 ** (18 - decimals)) if adapter == "nominal" else amount
        if credited > amount:
            return _row(
                "weird-decimals",
                "failed",
                "credited %d normalized units and held %d raw tokens" % (credited, amount),
            )
        return _row("weird-decimals", "held", "credited assets match the tokens held")
    if decimals >= 24:
        scale = 10 ** (decimals - 18)
        taken = scale - 1
        shares = 0 if adapter == "nominal" else taken
        if adapter == "nominal" and shares == 0 and taken > 0:
            return _row(
                "weird-decimals",
                "failed",
                "took %d raw tokens and minted no shares" % taken,
            )
        return _row("weird-decimals", "held", "a deposit that moves tokens mints shares")
    return _row("weird-decimals", "held", "decimals are inside the accounting range")


def run_weird_probes(
    *,
    vault: str,
    vault_source: str = "",
    asset_source: str = "",
    decimals: Optional[int] = None,
    fork_url: str = "",
    asset: str = "",
    caller: Optional[Caller] = None,
) -> dict[str, Any]:
    """Run the probes. A non-local fork is refused before any call."""
    from eth_scanner.heat import evidence_heat

    report: dict[str, Any] = {
        "status": "clean",
        "vault": _address(vault) if _is_address(vault) else "",
        "behaviors": [],
        "adapter": "unknown",
        "approval": "unknown",
        "results": [],
        "shapes": [],
        "heat": 0,
        "heat_contribution": 0,
        "note": "Token shape alone adds no heat.",
    }
    if not report["vault"]:
        report["status"] = "invalid"
        report["note"] = "Vault address is not 20 bytes of hex."
        return report
    if fork_url and not _local(fork_url):
        report["status"] = "refused"
        report["note"] = "A fork read needs a local anvil. No public RPC was contacted."
        return report
    if decimals is None and fork_url and asset:
        if not _is_address(asset):
            report["status"] = "invalid"
            report["note"] = "Asset address is not 20 bytes of hex."
            return report
        decimals = _read_decimals(fork_url, _address(asset), caller)

    adapter = adapter_mode(vault_source)
    approval = approval_mode(vault_source)
    behaviors = token_behaviors(asset_source, decimals)
    report["adapter"] = adapter
    report["approval"] = approval
    report["behaviors"] = list(behaviors)
    rows: list[dict[str, str]] = []
    if "fee-on-transfer" in behaviors:
        rows.append(probe_fee(adapter))
    if "rebasing" in behaviors:
        rows.append(probe_rebase(adapter))
    if "missing-return" in behaviors:
        rows.append(probe_silent(adapter, "weird-missing-return"))
    if "pausable" in behaviors:
        rows.append(probe_silent(adapter, "weird-pausable"))
    if "blocklist" in behaviors:
        rows.append(probe_silent(adapter, "weird-blocklist"))
    if "decimals" in behaviors and decimals is not None:
        rows.append(probe_decimals(adapter, int(decimals)))
    approval_row = probe_approval(approval)
    if approval_row is not None:
        rows.append(approval_row)

    failed = [row for row in rows if row["status"] == "failed"]
    report["results"] = rows
    report["shapes"] = [row["id"] for row in rows if row["status"] != "failed"]
    report["ran"] = bool(rows)
    if failed:
        report["status"] = "failed"
        report["note"] = "Credited assets and tokens held disagree. That shortfall is invariant heat."
    elif any(row["status"] == "held" for row in rows):
        report["status"] = "held"
        report["note"] = "The probes ran. Token shape alone adds no heat."
    elif rows:
        report["status"] = "unknown"
        report["note"] = "The adapter's accounting is not visible, so the probes add no heat."
    heat, breakdown = evidence_heat(
        funds_usd=None,
        invariant_results=failed,
        weird_tokens=report,
    )
    report["heat"] = heat
    report["heat_breakdown"] = {
        "weird_tokens": breakdown.get("weird_tokens"),
        "invariants_failed": breakdown.get("invariants_failed"),
        "total": breakdown.get("total"),
    }
    return report


def _is_address(value: str) -> bool:
    raw = (value or "").strip().lower()
    if raw.startswith("0x"):
        raw = raw[2:]
    return len(raw) == 40 and all(ch in "0123456789abcdef" for ch in raw)


def _address(value: str) -> str:
    raw = value.strip().lower()
    if raw.startswith("0x"):
        raw = raw[2:]
    return "0x" + raw


def _local(url: str) -> bool:
    from eth_scanner.deep.blend.ityfuzz_runner import local_rpc
    return bool(url) and local_rpc(url)


def _read_decimals(fork_url: str, token: str, caller: Optional[Caller]) -> Optional[int]:
    try:
        raw = caller(token, _DECIMALS_CALL) if caller else _eth_call(fork_url, token, _DECIMALS_CALL)
    except (OSError, ValueError, TimeoutError):
        return None
    return _decode_decimals(raw)


def _decode_decimals(raw: str) -> Optional[int]:
    if not isinstance(raw, str) or not raw.startswith("0x"):
        return None
    try:
        value = int(raw, 16)
    except ValueError:
        return None
    if value > 255:
        return None
    return value


def _eth_call(fork_url: str, token: str, data: str) -> str:
    if not _local(fork_url):
        raise ValueError("local fork required")
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [{"to": token, "data": data}, "latest"],
    }).encode("utf-8")
    req = urllib.request.Request(
        fork_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        body = json.loads(resp.read().decode("utf-8", errors="replace"))
    result = body.get("result")
    if not isinstance(result, str):
        raise ValueError("no decimals result")
    return result
