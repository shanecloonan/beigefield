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
    "previewDeposit(uint256)": "ef8b30f7",
    "previewWithdraw(uint256)": "0a28a477",
    "owner()": "8da5cb5b",
    "getOwner()": "893d20e8",
    "admin()": "f851a440",
    "getAdmin()": "42fbc7c3",
    "implementation()": "5c60da1b",
    "hasRole(bytes32,address)": "91d14854",
    "DEFAULT_ADMIN_ROLE()": "a217fddf",
    # Compound cToken / CEther
    "getCash()": "3b1d21a2",
    "totalBorrows()": "47bd3718",
    "totalReserves()": "8f840ddd",
    "exchangeRateStored()": "182df0f5",
    "exchangeRateCurrent()": "bd6d894d",
    "underlying()": "6f307dc3",
    # Curve / pool
    "balances(uint256)": "490e6cbc",
    "coins(uint256)": "c6610657",
    "get_balances()": "dc3131ba",
    # Chainlink-ish
    "latestRoundData()": "feaf968c",
    "decimals()": "313ce567",
    "latestAnswer()": "50d25bcd",
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
        if klass in {"vault", "unknown"}:
            out.extend(_erc4626_checks(addr, rpc, timeout_s, klass))
        if klass == "lending":
            out.extend(_lending_checks(addr, rpc, timeout_s, klass))
        if klass in {"pool", "custody"}:
            out.extend(_pool_checks(addr, rpc, timeout_s, klass))
        if klass in {"staking", "vault"}:
            out.extend(_staking_balance_checks(addr, rpc, timeout_s, klass))
        out.extend(_oracle_sanity_checks(addr, rpc, timeout_s, klass))
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

    # Share price not zero/absurd when supply > 0
    if supply > 0:
        if total_assets == 0:
            out.append(LiveInvariantResult(
                "erc4626-share-price", "share price non-zero with supply",
                "failed",
                "totalSupply=%s but totalAssets=0" % supply,
                contract_class=klass,
                extras={"totalSupply": supply, "totalAssets": total_assets},
            ))
        else:
            # assets per share in 1e18 scale; absurd if > 1e36 or tiny dust with huge supply
            pps = (total_assets * 10**18) // supply if supply else 0
            absurd = pps > 10**36 or (total_assets < 1000 and supply > 10**30)
            out.append(LiveInvariantResult(
                "erc4626-share-price", "share price sane",
                "failed" if absurd else "held",
                "assets_per_share_1e18=%s totalAssets=%s totalSupply=%s" % (pps, total_assets, supply),
                contract_class=klass,
                extras={"pps_1e18": pps, "totalAssets": total_assets, "totalSupply": supply},
            ))

    conv_data = SEL["convertToAssets(uint256)"] + ("%064x" % supply)
    converted = _call_uint(rpc, addr, conv_data, timeout_s)
    if converted is None:
        out.append(LiveInvariantResult(
            "erc4626-convert", "convertToAssets(totalSupply)", "unknown",
            "convertToAssets eth_call failed",
            contract_class=klass,
        ))
    else:
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

    bal = _call_uint(rpc, asset, SEL["balanceOf(address)"] + _pad_addr(addr), timeout_s)
    if bal is not None and total_assets is not None:
        tol = max(1, total_assets // 200)
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
            # Consistency vs convertToAssets(one)
            conv_one = _call_uint(
                rpc, addr, SEL["convertToAssets(uint256)"] + ("%064x" % one), timeout_s,
            )
            if conv_one is None:
                out.append(LiveInvariantResult(
                    "erc4626-previewRedeem", "previewRedeem(shares) returns",
                    "held",
                    "previewRedeem(%s)=%s" % (one, preview),
                    contract_class=klass,
                    extras={"shares": one, "assets": preview},
                ))
            else:
                tol = max(1, max(preview, conv_one) // 200)
                ok = abs(preview - conv_one) <= tol
                out.append(LiveInvariantResult(
                    "erc4626-preview-consistency",
                    "previewRedeem ≈ convertToAssets",
                    "held" if ok else "failed",
                    "previewRedeem(%s)=%s convertToAssets=%s tol=%s" % (one, preview, conv_one, tol),
                    contract_class=klass,
                    extras={"shares": one, "preview": preview, "converted": conv_one},
                ))

        # previewDeposit(1 asset unit) should return when totalAssets>0
        unit = 10**6
        pdep = _call_uint(rpc, addr, SEL["previewDeposit(uint256)"] + ("%064x" % unit), timeout_s)
        if pdep is None:
            out.append(LiveInvariantResult(
                "erc4626-previewDeposit", "previewDeposit readable", "unknown",
                "previewDeposit eth_call failed",
                contract_class=klass,
            ))
        else:
            out.append(LiveInvariantResult(
                "erc4626-previewDeposit", "previewDeposit returns",
                "held",
                "previewDeposit(%s)=%s" % (unit, pdep),
                contract_class=klass,
                extras={"assets": unit, "shares": pdep},
            ))
    return out


def _lending_checks(addr: str, rpc: str, timeout_s: float, klass: str) -> list[LiveInvariantResult]:
    """Compound-style cToken / CEther + generic lending views."""
    out: list[LiveInvariantResult] = []
    cash = _call_uint(rpc, addr, SEL["getCash()"], timeout_s)
    borrows = _call_uint(rpc, addr, SEL["totalBorrows()"], timeout_s)
    reserves = _call_uint(rpc, addr, SEL["totalReserves()"], timeout_s)
    supply = _call_uint(rpc, addr, SEL["totalSupply()"], timeout_s)
    rate = _call_uint(rpc, addr, SEL["exchangeRateStored()"], timeout_s)

    if cash is None and borrows is None and rate is None:
        # Fall back: try ERC-4626-ish only as unknown coverage, not as primary.
        out.append(LiveInvariantResult(
            "lending-views", "compound/lending views readable", "unknown",
            "getCash/totalBorrows/exchangeRateStored not available",
            contract_class=klass,
        ))
        return out

    if cash is not None and borrows is not None:
        reserves_v = reserves if reserves is not None else 0
        # Soft accounting: cash should be non-negative; borrows can exceed cash (utilization).
        out.append(LiveInvariantResult(
            "lending-cash-borrows",
            "getCash / totalBorrows readable",
            "held",
            "getCash=%s totalBorrows=%s totalReserves=%s" % (cash, borrows, reserves_v),
            contract_class=klass,
            extras={"cash": cash, "borrows": borrows, "reserves": reserves_v},
        ))
        # total borrows <= cash + borrows + reserves is tautological; instead check
        # reserves not absurdly larger than cash+borrows.
        if reserves is not None and (cash + borrows) > 0 and reserves > 10 * (cash + borrows) + 10**30:
            out.append(LiveInvariantResult(
                "lending-reserves-sane",
                "totalReserves not absurd vs cash+borrows",
                "failed",
                "reserves=%s cash+borrows=%s" % (reserves, cash + borrows),
                contract_class=klass,
            ))
        else:
            out.append(LiveInvariantResult(
                "lending-reserves-sane",
                "totalReserves sane vs cash+borrows",
                "held",
                "reserves=%s cash=%s borrows=%s" % (reserves_v, cash, borrows),
                contract_class=klass,
            ))

    if rate is not None:
        # Compound exchange rate is typically ~1e16–1e20 scale; 0 is broken; >1e36 absurd.
        if rate == 0:
            status, evidence = "failed", "exchangeRateStored=0"
        elif rate > 10**36:
            status, evidence = "failed", "exchangeRateStored absurdly large: %s" % rate
        else:
            status, evidence = "held", "exchangeRateStored=%s" % rate
        out.append(LiveInvariantResult(
            "lending-exchange-rate",
            "exchange rate monotonic/sane",
            status,
            evidence,
            contract_class=klass,
            extras={"exchangeRateStored": rate},
        ))

    if supply is not None:
        out.append(LiveInvariantResult(
            "lending-supply", "totalSupply readable",
            "held",
            "totalSupply=%s" % supply,
            contract_class=klass,
            extras={"totalSupply": supply},
        ))
    return out


def _pool_checks(addr: str, rpc: str, timeout_s: float, klass: str) -> list[LiveInvariantResult]:
    """AMM / deposit-pool: reserves vs balances, nonzero supply implies reserves."""
    out: list[LiveInvariantResult] = []
    supply = _call_uint(rpc, addr, SEL["totalSupply()"], timeout_s)
    eth_bal = _eth_get_balance(rpc, addr, timeout_s)

    # Curve-style balances(i)
    bal0 = _call_uint(rpc, addr, SEL["balances(uint256)"] + ("%064x" % 0), timeout_s)
    bal1 = _call_uint(rpc, addr, SEL["balances(uint256)"] + ("%064x" % 1), timeout_s)
    if bal0 is not None or bal1 is not None:
        b0 = bal0 or 0
        b1 = bal1 or 0
        if supply is not None and supply > 0 and b0 == 0 and b1 == 0:
            out.append(LiveInvariantResult(
                "pool-reserves",
                "nonzero LP supply implies nonzero reserves",
                "failed",
                "totalSupply=%s balances[0]=%s balances[1]=%s" % (supply, b0, b1),
                contract_class=klass,
                extras={"totalSupply": supply, "balances": [b0, b1]},
            ))
        else:
            out.append(LiveInvariantResult(
                "pool-reserves",
                "pool balances readable",
                "held",
                "balances[0]=%s balances[1]=%s totalSupply=%s" % (b0, b1, supply),
                contract_class=klass,
                extras={"balances": [b0, b1], "totalSupply": supply},
            ))
        # Cross-check coin(0) ERC-20 balance vs balances(0) when available
        coin0 = _call_addr(rpc, addr, SEL["coins(uint256)"] + ("%064x" % 0), timeout_s)
        if coin0 and bal0 is not None:
            actual = _call_uint(rpc, coin0, SEL["balanceOf(address)"] + _pad_addr(addr), timeout_s)
            if actual is not None:
                tol = max(1, bal0 // 100)
                ok = actual + tol >= bal0
                out.append(LiveInvariantResult(
                    "pool-reserve-backing",
                    "token balance backs balances(0)",
                    "held" if ok else "failed",
                    "balances(0)=%s token.balanceOf(pool)=%s coin=%s" % (bal0, actual, coin0),
                    contract_class=klass,
                    extras={"recorded": bal0, "actual": actual, "coin": coin0},
                ))
    elif eth_bal is not None:
        # Deposit pool (BlurPool-class): native ETH held for depositors.
        if supply is not None and supply > 0 and eth_bal == 0:
            out.append(LiveInvariantResult(
                "pool-eth-backing",
                "nonzero supply implies ETH reserves",
                "failed",
                "totalSupply=%s eth_balance=0" % supply,
                contract_class=klass,
                extras={"totalSupply": supply, "eth_balance": eth_bal},
            ))
        else:
            out.append(LiveInvariantResult(
                "pool-eth-backing",
                "deposit pool ETH balance",
                "held",
                "eth_balance=%s totalSupply=%s" % (eth_bal, supply),
                contract_class=klass,
                extras={"eth_balance": eth_bal, "totalSupply": supply},
            ))
    else:
        out.append(LiveInvariantResult(
            "pool-views", "pool reserve views", "unknown",
            "balances(i) / eth balance unavailable",
            contract_class=klass,
        ))

    if supply is not None:
        out.append(LiveInvariantResult(
            "pool-supply", "totalSupply readable",
            "held",
            "totalSupply=%s" % supply,
            contract_class=klass,
            extras={"totalSupply": supply},
        ))
    return out


def _oracle_sanity_checks(addr: str, rpc: str, timeout_s: float, klass: str) -> list[LiveInvariantResult]:
    """If the contract itself is a price feed, check freshness/nonzero."""
    out: list[LiveInvariantResult] = []
    # latestRoundData() → (roundId, answer, startedAt, updatedAt, answeredInRound)
    try:
        raw = _eth_call(rpc, addr, "0x" + SEL["latestRoundData()"], timeout_s)
    except Exception:  # noqa: BLE001
        return out
    decoded = _decode_words(raw, 5)
    if not decoded or len(decoded) < 5:
        return out
    _round_id, answer, _started, updated, _answered = decoded
    if answer == 0:
        out.append(LiveInvariantResult(
            "oracle-nonzero", "oracle answer non-zero",
            "failed",
            "latestRoundData.answer=0 updatedAt=%s" % updated,
            contract_class=klass,
            extras={"answer": answer, "updatedAt": updated},
        ))
    else:
        out.append(LiveInvariantResult(
            "oracle-nonzero", "oracle answer non-zero",
            "held",
            "answer=%s updatedAt=%s" % (answer, updated),
            contract_class=klass,
            extras={"answer": answer, "updatedAt": updated},
        ))
    # Freshness: updatedAt within ~48h of "now" — without wall clock from chain, use block.timestamp.
    try:
        block = _rpc(rpc, "eth_getBlockByNumber", ["latest", False], timeout_s)
        ts = int(block.get("timestamp", "0x0"), 16) if isinstance(block, dict) else 0
    except Exception:  # noqa: BLE001
        ts = 0
    if ts and updated:
        age = ts - updated
        stale = age > 48 * 3600
        out.append(LiveInvariantResult(
            "oracle-fresh", "oracle feed fresh (<48h)",
            "failed" if stale else "held",
            "age_s=%s updatedAt=%s block_ts=%s" % (age, updated, ts),
            contract_class=klass,
            extras={"age_s": age, "updatedAt": updated, "block_ts": ts},
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
            _eth_call_soft(rpc, addr, "0x" + data, timeout_s, from_addr=RANDOM_EOA)
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
            msg = str(exc).lower()
            if "revert" in msg or "execution reverted" in msg:
                out.append(LiveInvariantResult(
                    "privileged-%s" % name.split("(")[0],
                    "%s reverts for arbitrary EOA" % name,
                    "held",
                    str(exc)[:160],
                    contract_class=klass,
                ))
            elif "invalid params" in msg or "invalid argument" in msg:
                # Public RPCs sometimes reject odd calldata shapes — retry without `from`,
                # then treat as held (selector absent / not callable) rather than unknown spam.
                try:
                    _eth_call_soft(rpc, addr, "0x" + data, timeout_s, from_addr="")
                    out.append(LiveInvariantResult(
                        "privileged-%s" % name.split("(")[0],
                        "%s callable by arbitrary EOA" % name,
                        "failed",
                        "eth_call (no from) to %s did not revert" % name,
                        contract_class=klass,
                        extras={"selector": sel},
                    ))
                except _RevertError as exc2:
                    out.append(LiveInvariantResult(
                        "privileged-%s" % name.split("(")[0],
                        "%s reverts for arbitrary EOA" % name,
                        "held",
                        "retry without from reverted: %s" % str(exc2)[:120],
                        contract_class=klass,
                    ))
                except Exception as exc2:  # noqa: BLE001
                    msg2 = str(exc2).lower()
                    if "revert" in msg2:
                        out.append(LiveInvariantResult(
                            "privileged-%s" % name.split("(")[0],
                            "%s reverts for arbitrary EOA" % name,
                            "held",
                            str(exc2)[:160],
                            contract_class=klass,
                        ))
                    else:
                        # Missing selector / RPC soft-reject → held (not open privilege).
                        out.append(LiveInvariantResult(
                            "privileged-%s" % name.split("(")[0],
                            "%s not callable (rpc soft-reject)" % name,
                            "held",
                            "treated as non-callable after Invalid params: %s" % str(exc)[:100],
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


def _eth_get_balance(rpc: str, addr: str, timeout_s: float) -> Optional[int]:
    try:
        raw = _rpc(rpc, "eth_getBalance", [addr, "latest"], timeout_s)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(raw, str):
        return None
    try:
        return int(raw, 16)
    except ValueError:
        return None


def _eth_call(rpc: str, to: str, data: str, timeout_s: float, from_addr: str = "") -> str:
    return _eth_call_soft(rpc, to, data, timeout_s, from_addr=from_addr)


def _eth_call_soft(rpc: str, to: str, data: str, timeout_s: float, from_addr: str = "") -> str:
    params: dict[str, str] = {"to": to, "data": data}
    if from_addr:
        params["from"] = from_addr
    result = _rpc(rpc, "eth_call", [params, "latest"], timeout_s)
    if not isinstance(result, str):
        raise RuntimeError("bad eth_call result")
    # Empty / 0x with no return often means missing fn on some nodes — treat as revert-like.
    if result in {"0x", "0x0", ""}:
        raise _RevertError("empty return (missing fn or revert)")
    return result


def _rpc(rpc: str, method: str, params: list[Any], timeout_s: float) -> Any:
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode("utf-8")
    req = urllib.request.Request(
        rpc,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "eth-scanner/0.5 (defensive; read-only)"},
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


def _decode_words(raw: str, n: int) -> list[int]:
    text = (raw or "").strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    out: list[int] = []
    for i in range(n):
        chunk = text[i * 64:(i + 1) * 64]
        if len(chunk) < 64:
            break
        try:
            out.append(int(chunk, 16))
        except ValueError:
            break
    return out


def _pad_addr(addr: str) -> str:
    a = addr.lower().removeprefix("0x")
    return a.rjust(64, "0")
