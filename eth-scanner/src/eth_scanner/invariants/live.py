"""Read-only on-chain invariant evaluation via eth_call.

Per contract class: state properties at the latest block. Status is
held / failed / unknown with evidence. Never sends a transaction.
Never generates exploit / PoC / drain sequences.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from eth_scanner.ingest.funds import PUBLIC_RPCS, resolve_rpc_urls

# Common view selectors (keccak4)
SEL = {
    "totalAssets()": "01e1d114",
    "totalSupply()": "18160ddd",
    "asset()": "38d52e0f",
    "balanceOf(address)": "70a08231",
    "convertToAssets(uint256)": "07a2d13a",
    "previewRedeem(uint256)": "4cdad506",
    "previewWithdraw(uint256)": "0a28a477",
    "owner()": "8da5cb5b",
    "getOwner()": "893d20e8",
    "admin()": "f851a440",
    "getAdmin()": "42fbc7c3",
    "implementation()": "5c60da1b",
    "proxiableUUID()": "52d1902d",
    "hasRole(bytes32,address)": "91d14854",
    "DEFAULT_ADMIN_ROLE()": "a217fddf",
}

# Non-special random EOA (avoid 0xdead / zero — some public RPCs reject them as `from`).
RANDOM_EOA = "0x1111111111111111111111111111111111111111"
# Static-call from a random EOA for privileged selectors — expect revert.
PRIVILEGED_PROBE_SELECTORS = (
    ("pause()", "8456cb59"),
    ("unpause()", "3f4ba83a"),
    ("upgradeTo(address)", "3659cfe6"),
    ("upgradeToAndCall(address,bytes)", "4f1ef286"),
    ("transferOwnership(address)", "f2fde38b"),
    ("renounceOwnership()", "715018a6"),
    ("setPendingAdmin(address)", "cf58e7f0"),
)


@dataclass
class LiveInvariantResult:
    id: str
    name: str
    status: str  # held | failed | unknown
    evidence: str
    contract_class: str = ""
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_live_invariants(
    address: str,
    *,
    contract_class: str = "unknown",
    rpc_url: str = "",
    timeout_s: float = 8.0,
) -> list[LiveInvariantResult]:
    """Evaluate class-appropriate invariants. Soft-fails to unknown."""
    addr = (address or "").strip().lower()
    if not addr.startswith("0x") or len(addr) != 42:
        return [LiveInvariantResult("bad-address", "address shape", "unknown", "invalid address")]

    rpc = _pick_rpc(rpc_url)
    if not rpc:
        return [LiveInvariantResult(
            "rpc-missing", "rpc availability", "unknown",
            "no ETH_RPC_URL / public RPC available — invariants not evaluated",
        )]

    out: list[LiveInvariantResult] = []
    klass = (contract_class or "unknown").lower()
    try:
        if klass in {"vault", "lending"} or klass == "unknown":
            out.extend(_erc4626_checks(addr, rpc, timeout_s, klass))
        if klass in {"staking", "vault"}:
            out.extend(_staking_balance_checks(addr, rpc, timeout_s, klass))
        out.extend(_role_checks(addr, rpc, timeout_s, klass))
        out.extend(_privileged_call_probes(addr, rpc, timeout_s, klass))
    except Exception as exc:  # noqa: BLE001 — soft-fail whole suite
        out.append(LiveInvariantResult(
            "suite-error", "live invariant suite", "unknown",
            "eth_call suite error: %s" % str(exc)[:200],
            contract_class=klass,
        ))
    if not out:
        out.append(LiveInvariantResult(
            "no-applicable", "class coverage", "held",
            "no class-specific live checks applicable; treated as held",
            contract_class=klass,
        ))
    return out


def _pick_rpc(preferred: str) -> str:
    urls = resolve_rpc_urls(preferred)
    return urls[0] if urls else ""


def _erc4626_checks(addr: str, rpc: str, timeout_s: float, klass: str) -> list[LiveInvariantResult]:
    out: list[LiveInvariantResult] = []
    asset = _call_addr(rpc, addr, SEL["asset()"], timeout_s)
    if asset is None:
        out.append(LiveInvariantResult(
            "erc4626-asset", "asset() present", "unknown",
            "asset() not implemented or eth_call failed",
            contract_class=klass,
        ))
        return out

    total_assets = _call_uint(rpc, addr, SEL["totalAssets()"], timeout_s)
    supply = _call_uint(rpc, addr, SEL["totalSupply()"], timeout_s)
    if total_assets is None or supply is None:
        out.append(LiveInvariantResult(
            "erc4626-totals", "totalAssets/totalSupply readable", "unknown",
            "totalAssets or totalSupply eth_call failed",
            contract_class=klass,
            extras={"asset": asset},
        ))
        return out

    # convertToAssets(totalSupply) <= totalAssets (+ small tolerance)
    conv_data = SEL["convertToAssets(uint256)"] + ("%064x" % supply)
    converted = _call_uint(rpc, addr, conv_data, timeout_s)
    if converted is None:
        out.append(LiveInvariantResult(
            "erc4626-convert", "convertToAssets(totalSupply)", "unknown",
            "convertToAssets eth_call failed",
            contract_class=klass,
        ))
    else:
        # 0.5% tolerance or 1 wei
        tol = max(1, total_assets // 200)
        ok = converted <= total_assets + tol
        out.append(LiveInvariantResult(
            "erc4626-solvency",
            "convertToAssets(totalSupply) <= totalAssets",
            "held" if ok else "failed",
            "convertToAssets=%s totalAssets=%s tol=%s" % (converted, total_assets, tol),
            contract_class=klass,
            extras={"converted": converted, "totalAssets": total_assets, "totalSupply": supply, "asset": asset},
        ))

    # asset balance held by vault vs totalAssets (informational; some vaults hold elsewhere)
    bal = _call_uint(rpc, asset, SEL["balanceOf(address)"] + _pad_addr(addr), timeout_s)
    if bal is not None and total_assets is not None:
        # held when balance >= totalAssets - tol OR totalAssets is accounting-only
        tol = max(1, total_assets // 200)
        # Do not fail solely on under-balance (strategies park elsewhere) — unknown if far apart
        if bal + tol >= total_assets:
            status = "held"
            evidence = "asset.balanceOf(vault)=%s >= totalAssets=%s" % (bal, total_assets)
        elif total_assets == 0 and bal == 0:
            status = "held"
            evidence = "empty vault (0 assets / 0 balance)"
        else:
            status = "unknown"
            evidence = (
                "asset.balanceOf(vault)=%s vs totalAssets=%s — may be strategy-held; not a fail"
                % (bal, total_assets)
            )
        out.append(LiveInvariantResult(
            "erc4626-asset-balance",
            "asset balance vs totalAssets",
            status,
            evidence,
            contract_class=klass,
            extras={"balance": bal, "totalAssets": total_assets},
        ))

    # previewRedeem(1 share) consistency when supply > 0
    if supply and supply > 0:
        one = min(supply, 10**18)
        pred = SEL["previewRedeem(uint256)"] + ("%064x" % one)
        preview = _call_uint(rpc, addr, pred, timeout_s)
        if preview is None:
            out.append(LiveInvariantResult(
                "erc4626-previewRedeem", "previewRedeem readable", "unknown",
                "previewRedeem eth_call failed",
                contract_class=klass,
            ))
        else:
            out.append(LiveInvariantResult(
                "erc4626-previewRedeem", "previewRedeem(shares) returns",
                "held",
                "previewRedeem(%s)=%s" % (one, preview),
                contract_class=klass,
                extras={"shares": one, "assets": preview},
            ))
    return out


def _staking_balance_checks(addr: str, rpc: str, timeout_s: float, klass: str) -> list[LiveInvariantResult]:
    """Best-effort: totalSupply as staked units vs ETH/native not required."""
    supply = _call_uint(rpc, addr, SEL["totalSupply()"], timeout_s)
    if supply is None:
        return [LiveInvariantResult(
            "staking-supply", "totalSupply readable", "unknown",
            "totalSupply eth_call failed",
            contract_class=klass,
        )]
    return [LiveInvariantResult(
        "staking-supply", "totalSupply readable",
        "held",
        "totalSupply=%s" % supply,
        contract_class=klass,
        extras={"totalSupply": supply},
    )]


def _role_checks(addr: str, rpc: str, timeout_s: float, klass: str) -> list[LiveInvariantResult]:
    out: list[LiveInvariantResult] = []
    owner = None
    for sig in ("owner()", "getOwner()", "admin()", "getAdmin()"):
        owner = _call_addr(rpc, addr, SEL[sig], timeout_s)
        if owner is not None:
            break
    if owner is None:
        out.append(LiveInvariantResult(
            "roles-owner", "owner/admin readable", "unknown",
            "no owner()/admin() view found",
            contract_class=klass,
        ))
        return out

    kind = enrich_owner_kind(rpc, owner, timeout_s)
    extras = {"owner": owner, "kind": kind}
    # Recording only — EOA admin heat/promote is decided by the funnel with funds.
    out.append(LiveInvariantResult(
        "roles-owner",
        "owner/admin identity",
        "held",
        "owner/admin=%s kind=%s" % (owner, kind),
        contract_class=klass,
        extras=extras,
    ))
    return out


def _privileged_call_probes(addr: str, rpc: str, timeout_s: float, klass: str) -> list[LiveInvariantResult]:
    """Static eth_call from a random EOA. Expected: revert. Non-revert → failed."""
    out: list[LiveInvariantResult] = []
    for name, sel in PRIVILEGED_PROBE_SELECTORS:
        data = sel
        if name.startswith("upgradeToAndCall"):
            # upgradeToAndCall(address,bytes) — empty bytes payload
            data = sel + _pad_addr(RANDOM_EOA) + ("%064x" % 64) + ("%064x" % 0)
        elif "(address)" in name or "(address," in name:
            data = sel + _pad_addr(RANDOM_EOA)
        try:
            _eth_call(rpc, addr, "0x" + data, timeout_s, from_addr=RANDOM_EOA)
            # If it returned without error, the call did not revert — evidence of open privilege.
            out.append(LiveInvariantResult(
                "privileged-%s" % name.split("(")[0],
                "%s callable by arbitrary EOA" % name,
                "failed",
                "eth_call from %s to %s did not revert" % (RANDOM_EOA, name),
                contract_class=klass,
                extras={"selector": sel, "from": RANDOM_EOA},
            ))
        except _RevertError as exc:
            out.append(LiveInvariantResult(
                "privileged-%s" % name.split("(")[0],
                "%s reverts for arbitrary EOA" % name,
                "held",
                "eth_call reverted as expected: %s" % str(exc)[:120],
                contract_class=klass,
                extras={"selector": sel, "from": RANDOM_EOA},
            ))
        except Exception as exc:  # noqa: BLE001
            # Missing function often returns empty / execution reverted — treat soft.
            msg = str(exc).lower()
            if "revert" in msg or "execution reverted" in msg:
                out.append(LiveInvariantResult(
                    "privileged-%s" % name.split("(")[0],
                    "%s reverts for arbitrary EOA" % name,
                    "held",
                    str(exc)[:160],
                    contract_class=klass,
                ))
            else:
                out.append(LiveInvariantResult(
                    "privileged-%s" % name.split("(")[0],
                    "%s probe" % name,
                    "unknown",
                    str(exc)[:160],
                    contract_class=klass,
                ))
    return out


class _RevertError(RuntimeError):
    pass


def summarize_role_flags(results: list[LiveInvariantResult]) -> tuple[bool, bool]:
    """Return (privileged_callable, eoa_admin) from live results."""
    privileged = any(
        r.status == "failed" and r.id.startswith("privileged-") for r in results
    )
    eoa_admin = False
    for r in results:
        if r.id == "roles-owner" and (r.extras or {}).get("kind") == "eoa":
            eoa_admin = True
    return privileged, eoa_admin


def _address_kind(addr: str) -> str:
    a = (addr or "").lower()
    if a in {"", "0x" + "0" * 40, "0x0000000000000000000000000000000000000000"}:
        return "zero"
    # Heuristic: without eth_getCode we cannot be sure; treat non-zero as unknown-contract
    # unless it's a well-known short EOA pattern. Caller may enrich later.
    return "eoa-or-contract"


def enrich_owner_kind(rpc: str, owner: str, timeout_s: float = 8.0) -> str:
    """Classify owner via eth_getCode — eoa vs contract vs zero."""
    a = (owner or "").lower()
    if a in {"", "0x" + "0" * 40}:
        return "zero"
    try:
        code = _rpc(rpc, "eth_getCode", [a, "latest"], timeout_s)
        if isinstance(code, str) and code not in {"0x", "0x0", ""}:
            return "contract"
        return "eoa"
    except Exception:  # noqa: BLE001
        return "unknown"


def _call_uint(rpc: str, to: str, selector_or_data: str, timeout_s: float) -> Optional[int]:
    data = selector_or_data if selector_or_data.startswith("0x") else "0x" + selector_or_data
    try:
        raw = _eth_call(rpc, to, data, timeout_s)
    except Exception:  # noqa: BLE001
        return None
    return _decode_uint(raw)


def _call_addr(rpc: str, to: str, selector: str, timeout_s: float) -> Optional[str]:
    try:
        raw = _eth_call(rpc, to, "0x" + selector, timeout_s)
    except Exception:  # noqa: BLE001
        return None
    return _decode_addr(raw)


def _eth_call(rpc: str, to: str, data: str, timeout_s: float, from_addr: str = "") -> str:
    params: dict[str, str] = {"to": to, "data": data}
    if from_addr:
        params["from"] = from_addr
    result = _rpc(rpc, "eth_call", [params, "latest"], timeout_s)
    if not isinstance(result, str):
        raise RuntimeError("bad eth_call result")
    return result


def _rpc(rpc: str, method: str, params: list[Any], timeout_s: float) -> Any:
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode("utf-8")
    req = urllib.request.Request(
        rpc,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "eth-scanner/0.4 (defensive; read-only)"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        body = json.loads(resp.read().decode("utf-8", errors="replace"))
    err = body.get("error")
    if err:
        msg = str(err.get("message") if isinstance(err, dict) else err)
        if "revert" in msg.lower() or "execution reverted" in msg.lower():
            raise _RevertError(msg)
        raise RuntimeError(msg[:200])
    return body.get("result")


def _decode_uint(word: str) -> Optional[int]:
    raw = (word or "").strip().lower()
    if raw.startswith("0x"):
        raw = raw[2:]
    if not raw:
        return None
    try:
        return int(raw, 16)
    except ValueError:
        return None


def _decode_addr(word: str) -> Optional[str]:
    raw = (word or "").strip().lower()
    if raw.startswith("0x"):
        raw = raw[2:]
    if len(raw) < 40:
        return None
    return "0x" + raw[-40:]


def _pad_addr(addr: str) -> str:
    a = addr.lower().removeprefix("0x")
    return a.rjust(64, "0")
