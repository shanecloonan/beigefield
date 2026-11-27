"""Scan contracts that actually hold ETH or major tokens.

The candidate file is vaults, pools, escrows, treasuries, and top holders.
A reported TVL figure is not a balance. This job measures native ETH plus
WETH, USDC, USDT, DAI, WBTC, stETH, wstETH, and USDe with Multicall3, drops
tokens, routers, empty accounts, and anything under $5,000, then keeps the
richest 500 that are not already on the board.

The normal scan runs first. Fork and fuzz run only when the new heat is
above 0. The CU cap covers the measurement and both scan phases.
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path
from typing import Any, Optional

from eth_scanner.desk.high_prob import finished_addresses, run_high_prob_batch
from eth_scanner.desk.signal_rerun import redact, safe_address
from eth_scanner.ingest.funds import MAJOR_TOKENS, FundsSnapshot, probe_funds_batch

MIN_FUNDS_USD = 5_000
DEFAULT_LIMIT = 500
DEFAULT_BUDGET_CU = 400_000
_CANDIDATES = Path(__file__).resolve().parents[3] / "data" / "held_candidates.json"

# The token contracts themselves, and routers that pass tokens through.
# A pool or vault that holds those tokens stays in.
DENY_ADDRESSES = frozenset({
    addr
    for _symbol, addr, _hint, _dec in MAJOR_TOKENS
} | {
    "0x7a250d5630b4cf539739df2c5dacb4c659f2488d",  # Uniswap V2 router
    "0xe592427a0aece92de3edee1f18e0157c05861564",  # Uniswap V3 SwapRouter
    "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45",  # Uniswap SwapRouter02
    "0xef1c6e67703c7bd7107eed8303fbe6ec2554bf6b",  # Uniswap Universal Router
    "0x3fc91a3afd70395cd496c647d5a6cc9d4b2b7fad",  # Uniswap Universal Router 2
    "0x1111111254eeb25477b68fb85ed929f73a960582",  # 1inch v5
    "0x111111125421ca6dc452d289314280a0f8842a65",  # 1inch v6
    "0xdef1c0ded9bec7f1a1670819833240f027b25eff",  # 0x Exchange Proxy
    "0x6131b5fae19ea4f9d964eac0408e4408b66337b5",  # Kyber meta aggregation
})


def load_candidates(path: Optional[Path] = None) -> list[dict[str, Any]]:
    target = path or _CANDIDATES
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get("candidates") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _usd(snap: Any) -> Optional[float]:
    if snap is None:
        return None
    if isinstance(snap, FundsSnapshot):
        if snap.status != "ok" or snap.total_usd is None:
            return None
        return float(snap.total_usd)
    if isinstance(snap, dict):
        if str(snap.get("status") or "ok") != "ok":
            return None
        raw = snap.get("total_usd")
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
    return None


def _has_code(code: Any) -> bool:
    text = str(code or "").strip().lower()
    return text.startswith("0x") and len(text) > 2


def rank_held(
    candidates: list[dict[str, Any]],
    snapshots: dict[str, Any],
    codes: dict[str, str],
    *,
    finished: Optional[set[str]] = None,
    limit: int = DEFAULT_LIMIT,
    min_usd: float = MIN_FUNDS_USD,
) -> list[dict[str, Any]]:
    """Richest contracts by the measured balance. Tokens, routers, and EOAs drop out."""
    done = finished or set()
    cap = max(0, int(limit))
    chosen: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in candidates:
        addr = safe_address(row.get("address"))
        if not addr or addr in seen or addr in done or addr in DENY_ADDRESSES:
            continue
        seen.add(addr)
        usd = _usd(snapshots.get(addr))
        if usd is None or usd < float(min_usd):
            continue
        if not _has_code(codes.get(addr)):
            continue
        chosen.append({
            "address": addr,
            "protocol": str(row.get("protocol") or "")[:80],
            "category": str(row.get("kind") or row.get("category") or "")[:60],
            "est_usd_held": round(usd, 2),
            "funds_usd": round(usd, 2),
            "source": "measured",
            "kind": str(row.get("kind") or ""),
        })
    chosen.sort(key=lambda item: (-float(item["est_usd_held"]), item["address"]))
    return chosen[:cap]


def _contracts(url: str, addresses: list[str], proxy: Any) -> Optional[set[str]]:
    """Addresses with runtime code. None means the provider or the cap stopped us."""
    live: set[str] = set()
    for start in range(0, len(addresses), 40):
        if proxy.stop_reason:
            return None
        chunk = addresses[start : start + 40]
        payload = [
            {"jsonrpc": "2.0", "id": index, "method": "eth_getCode", "params": [addr, "latest"]}
            for index, addr in enumerate(chunk)
        ]
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode("utf-8") or "[]")
        except Exception:
            if proxy.stop_reason:
                return None
            continue
        if proxy.stop_reason:
            return None
        if isinstance(body, dict):
            body = [body]
        by_id = {item.get("id"): item for item in body if isinstance(item, dict)}
        for index, addr in enumerate(chunk):
            result = str((by_id.get(index) or {}).get("result") or "")
            if _has_code(result):
                live.add(addr)
    return live


def _measure(
    store: Any,
    settings: Any,
    addresses: list[str],
    *,
    budget_cu: int,
    lease_wait_s: float,
) -> dict[str, Any]:
    """Balance batch, then code check, inside the scan-cycle lease and the CU cap."""
    from eth_scanner.desk.signal_rerun import CuProxy, _lock_rpc
    from eth_scanner.feed.runner import acquire_scan_cycle, release_scan_cycle

    upstream = str(getattr(settings, "eth_rpc_url", "") or "").strip()
    if not upstream:
        return {"status": "skipped", "notes": ["ETH_RPC_URL unset"], "snapshots": {}, "codes": {}}
    try:
        owner = acquire_scan_cycle(store, wait_s=lease_wait_s, poll_s=15.0)
    except TimeoutError:
        return {"status": "blocked", "notes": ["another scan cycle holds the cursor"], "snapshots": {}, "codes": {}}
    proxy = CuProxy(upstream, int(budget_cu))
    local = proxy.start()
    settings.eth_rpc_url = local
    _lock_rpc(local)
    snapshots: dict[str, FundsSnapshot] = {}
    stop = ""
    try:
        snapshots = probe_funds_batch(addresses, rpc_url=local, batch_size=25, timeout_s=25.0)
        if proxy.stop_reason:
            stop = proxy.stop_reason
            snapshots = {}
        else:
            funded = [
                addr for addr, snap in snapshots.items()
                if snap.status == "ok" and snap.total_usd is not None and float(snap.total_usd) >= MIN_FUNDS_USD
            ]
            live = _contracts(local, funded, proxy)
            if live is None:
                stop = proxy.stop_reason or "cu budget"
                snapshots = {}
            else:
                for addr in funded:
                    if addr not in live:
                        snapshots.pop(addr, None)
    finally:
        release_scan_cycle(store, owner, stop or "held-funds measure finished")
        proxy.stop()
        settings.eth_rpc_url = upstream
    return {
        "status": stop or "ok",
        "snapshots": snapshots,
        "cu_used": proxy.budget.spent,
        "cu_calls": len(proxy.budget.calls),
        "stop_reason": proxy.stop_reason,
        "notes": [],
    }


def run_held_funds_batch(
    store: Any,
    settings: Any,
    *,
    limit: int = DEFAULT_LIMIT,
    budget_cu: int = DEFAULT_BUDGET_CU,
    deadline_s: float = 300 * 60,
    lease_wait_s: float = 20 * 60,
    dry_run: bool = False,
    scan_one: Any = None,
    candidate_path: Optional[Path] = None,
    candidates: Optional[list[dict[str, Any]]] = None,
    snapshots: Optional[dict[str, Any]] = None,
    codes: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """Measure balances, keep the top contracts, then scan them.

    Injected ``snapshots`` skip the RPC measure so a test can rank without a chain.
    """
    started = time.monotonic()
    rows = candidates if candidates is not None else load_candidates(candidate_path)
    finished, err = finished_addresses(store)
    plan: dict[str, Any] = {
        "mode": "held-funds",
        "status": "ok",
        "limit": int(limit),
        "min_funds_usd": MIN_FUNDS_USD,
        "budget_cu": int(budget_cu),
        "pool": 0,
        "found": 0,
        "scanned": 0,
        "notes": [
            "ranked by ETH plus major-token balances measured at the address",
            "tokens and routers are left out; an empty account is left out",
            "the under-$5k queues were not read",
            "a provider stop or the CU cap leaves the in-flight contract without a verdict",
        ],
        "rerun": [],
        "unfinished": [],
        "cu_used": 0,
        "cu_calls": 0,
        "stop_reason": "",
        "drainable": [],
    }
    if err:
        plan["status"] = "error"
        plan["notes"].append("could not read finished scans: %s" % err)
        return plan
    pool = []
    for row in rows:
        addr = safe_address(row.get("address"))
        if addr and addr not in finished and addr not in DENY_ADDRESSES:
            pool.append(row)
    plan["pool"] = len(pool)
    plan["skipped_finished"] = len(rows) - len(pool)
    if not pool:
        plan["status"] = "done"
        plan["notes"].append("no unscanned vault, pool, or holder to measure")
        return plan

    measure_cu = 0
    measure_calls = 0
    if snapshots is None:
        if dry_run:
            plan["status"] = "dry-run"
            plan["notes"].append("%d addresses would be measured" % len(pool))
            return plan
        measured = _measure(
            store,
            settings,
            [safe_address(row.get("address")) for row in pool],
            budget_cu=int(budget_cu),
            lease_wait_s=lease_wait_s,
        )
        measure_cu = int(measured.get("cu_used") or 0)
        measure_calls = int(measured.get("cu_calls") or 0)
        plan["cu_used"] = measure_cu
        plan["cu_calls"] = measure_calls
        plan["stop_reason"] = measured.get("stop_reason") or ""
        if measured.get("status") in {"skipped", "blocked", "monthly capacity", "auth", "rate limited", "cu budget"}:
            plan["status"] = measured.get("status")
            plan["notes"].extend(measured.get("notes") or [])
            if measured.get("status") not in {"skipped", "blocked"}:
                plan["notes"].append("stopped during the balance measure; no verdict was written")
            return plan
        snapshots = measured.get("snapshots") or {}
        codes = {addr: "0x01" for addr in snapshots}
    elif codes is None:
        codes = {safe_address(row.get("address")): "0x01" for row in pool}

    selected = rank_held(pool, snapshots, codes or {}, finished=finished, limit=limit)
    plan["found"] = len(selected)
    plan["measured_ok"] = sum(1 for snap in snapshots.values() if _usd(snap) is not None)
    if not selected:
        plan["status"] = "done" if not dry_run else "dry-run"
        plan["notes"].append("no contract held $5000 of ETH or major tokens")
        return plan
    if dry_run:
        plan["status"] = "dry-run"
        plan["selected_rows"] = selected
        return plan

    remaining = max(60.0, float(deadline_s) - (time.monotonic() - started))
    # The measure already spent part of the cap. The scan uses what is left.
    scan_budget = max(0, int(budget_cu) - measure_cu)
    report = run_high_prob_batch(
        store,
        settings,
        limit=len(selected),
        budget_cu=scan_budget,
        deadline_s=remaining,
        lease_wait_s=lease_wait_s,
        dry_run=False,
        scan_one=scan_one,
        master=selected,
        master_source="measured",
        tranche_path=Path("/no/such/held-tranche.json"),
    )
    report["mode"] = "held-funds"
    report["pool"] = plan["pool"]
    report["found"] = len(selected)
    report["measured_ok"] = plan["measured_ok"]
    report["min_funds_usd"] = MIN_FUNDS_USD
    report["cu_used"] = measure_cu + int(report.get("cu_used") or 0)
    report["cu_calls"] = measure_calls + int(report.get("cu_calls") or 0)
    report["notes"] = plan["notes"] + list(report.get("notes") or [])
    if not report.get("stop_reason"):
        report["stop_reason"] = plan.get("stop_reason") or ""
    return report
