"""Re-score every contract that was ever Maybe or carried a heat signal.

The list is the union of stored scan rows and the public-board seed. Fork
verify runs only when this job turns it on. The shared scan-cycle lease is
held for the whole pass so the monitor and the backfill do not scan at the
same time. Chain I/O stays read-only. Call sequences are not kept.
"""

from __future__ import annotations

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib import error as urlerror
from urllib import request as urlrequest

from eth_scanner.chain.cu_budget import CU_ESTIMATES, DEFAULT_UNKNOWN_CU, CuBudget

# Lane A (code, balances, storage, capped traces) plus a short anvil fork.
# The fork number is a ceiling: anvil's lazy reads are counted for real by
# the local proxy, and the pass stops when the running total crosses the cap.
SCAN_CU = 8_000
FORK_CU = 32_000
PER_CONTRACT_CU = SCAN_CU + FORK_CU
DEFAULT_BUDGET_CU = 4_000_000
PAGE = 1000
MAX_ROWS = 40_000

# Anvil's fork traffic uses these on top of the published scan methods.
# A zero cost is a free local probe (client version, net version).
_FORK_CU = {
    "eth_getBlockByNumber": 16,
    "eth_getBlockByHash": 16,
    "eth_chainId": 10,
    "eth_getTransactionCount": 17,
    "eth_getTransactionReceipt": 15,
    "eth_feeHistory": 10,
    "eth_gasPrice": 19,
    "eth_maxPriorityFeePerGas": 10,
    "eth_estimateGas": 87,
    "eth_getProof": 80,
    "net_version": 0,
    "web3_clientVersion": 0,
    "eth_syncing": 10,
}

_YES = {"drain-found", "drain", "yes"}
_MAYBE = {"maybe"}
_URL = re.compile(r"https?://\S+", re.I)
_CALLDATA = re.compile(r"0x[0-9a-fA-F]{16,}")
_SEED = Path(__file__).with_name("signal_rerun_seed.json")


def redact(text: str) -> str:
    cleaned = _URL.sub("[url]", str(text or ""))
    return _CALLDATA.sub("0x…", cleaned)


def per_contract_cu() -> int:
    return PER_CONTRACT_CU


def estimate_cu(count: int) -> dict[str, int]:
    n = max(0, int(count))
    return {
        "contracts": n,
        "cu_per_contract": PER_CONTRACT_CU,
        "scan_cu": SCAN_CU,
        "fork_cu": FORK_CU,
        "estimated_cu": n * PER_CONTRACT_CU,
    }


def _num(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _breakdown(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("heat_breakdown")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return dict(raw) if isinstance(raw, dict) else {}


def _caller_profit(row: dict[str, Any]) -> int:
    blobs = [
        json.dumps(_breakdown(row), default=str),
        json.dumps(row.get("notes") or [], default=str),
        str(row.get("drop_reason") or ""),
    ]
    best = 0
    for blob in blobs:
        for match in re.finditer(r"caller_profit_delta[=:](\d+)", blob):
            best = max(best, int(match.group(1)))
    direct = _breakdown(row).get("caller_profit_delta")
    if isinstance(direct, (int, float)) and direct > best:
        best = int(direct)
    return best


def desk_verdict(row: dict[str, Any]) -> str:
    """Yes / Maybe / No, matching the desk: a drain is Yes, any heat is Maybe."""
    bucket = str(row.get("blend_bucket") or "").strip().lower()
    if bucket in _YES:
        return "yes"
    if bucket == "no" and _num(row.get("heat")) <= 0 and _num(row.get("blend_heat")) <= 0:
        if _caller_profit(row) <= 0 and _num(_breakdown(row).get("funds_in_heat")) <= 0:
            return "no"
    if bucket in _MAYBE:
        return "maybe"
    breakdown = _breakdown(row)
    if _num(breakdown.get("funds_in_heat")) > 0 or _caller_profit(row) > 0:
        return "yes"
    if _num(row.get("heat")) > 0 or _num(row.get("blend_heat")) > 0:
        return "maybe"
    return "no"


def _failed_invariant(row: dict[str, Any]) -> bool:
    raw = row.get("invariant_results")
    if not isinstance(raw, list):
        raw = _breakdown(row).get("invariant_results")
    if not isinstance(raw, list):
        return False
    for item in raw:
        if isinstance(item, dict) and str(item.get("status") or "").lower() == "failed":
            return True
    return False


def _conservation_fail(row: dict[str, Any]) -> bool:
    raw = _breakdown(row).get("conservation")
    if not isinstance(raw, list):
        return False
    for item in raw:
        if isinstance(item, dict) and str(item.get("status") or "").lower() == "fail":
            if _num(item.get("value_delta")) > 0:
                return True
    return False


def signal_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if _num(row.get("heat")) > 0 or _num(row.get("blend_heat")) > 0:
        reasons.append("heat")
    bucket = str(row.get("blend_bucket") or "").strip().lower()
    if bucket in _MAYBE or bucket in _YES:
        reasons.append("bucket")
    verdict = desk_verdict(row)
    if verdict == "maybe" and "heat" not in reasons and "bucket" not in reasons:
        reasons.append("maybe")
    if verdict == "yes" and "bucket" not in reasons:
        reasons.append("drain")
    breakdown = _breakdown(row)
    for key in ("original_peak", "peak_heat", "invariants_failed", "privileged_callable",
                "eoa_admin", "corroborated", "gated_leads", "exploit_poc_heat", "funds_in_heat"):
        if _num(breakdown.get(key)) > 0 and key not in reasons:
            reasons.append(key)
    if _failed_invariant(row):
        reasons.append("failed_invariant")
    if _conservation_fail(row):
        reasons.append("conservation")
    return reasons


def is_signal(row: dict[str, Any]) -> bool:
    return bool(signal_reasons(row))


def signal_peak(row: dict[str, Any]) -> int:
    breakdown = _breakdown(row)
    values = [
        _num(row.get("heat")),
        _num(row.get("blend_heat")),
        _num(row.get("peak_heat")),
        _num(breakdown.get("original_peak")),
        _num(breakdown.get("peak_heat")),
        _num(breakdown.get("total")),
    ]
    return max(values) if values else 0


def chain_of(row: dict[str, Any]) -> str:
    text = str(row.get("chain") or "").strip().lower()
    return text or "ethereum"


def safe_address(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text.startswith("0x"):
        text = "0x" + text
    if len(text) != 42 or any(ch not in "0123456789abcdef" for ch in text[2:]):
        return ""
    return text


def _when(row: dict[str, Any]) -> str:
    return str(row.get("created_at") or row.get("updated_at") or "")


def fold_signals(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Dedupe by chain and address. The newest row is the current verdict.

    A contract stays on the list when any older row was a signal, including
    one that was later downgraded. Non-mainnet rows are returned separately.
    """
    best: dict[tuple[str, str], dict[str, Any]] = {}
    other: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        chain = chain_of(row)
        address = safe_address(row.get("address"))
        if not address:
            continue
        signal = is_signal(row)
        if chain not in {"ethereum", "eth", "mainnet"}:
            if signal:
                other.append({
                    "chain": chain,
                    "address": address,
                    "reason": "not ethereum; this job uses the mainnet ETH_RPC_URL",
                })
            continue
        key = ("ethereum", address)
        peak = signal_peak(row) if signal else 0
        reasons = signal_reasons(row) if signal else []
        slot = best.get(key)
        if slot is None:
            best[key] = {
                "chain": "ethereum",
                "address": address,
                "peak": peak,
                "reasons": list(reasons),
                "name": str(row.get("contract_name") or ""),
                "latest": row,
                "signal": signal,
            }
            continue
        slot["peak"] = max(int(slot["peak"]), peak)
        slot["signal"] = bool(slot["signal"] or signal)
        for reason in reasons:
            if reason not in slot["reasons"]:
                slot["reasons"].append(reason)
        if not slot["name"]:
            slot["name"] = str(row.get("contract_name") or "")
        if _when(row) >= _when(slot["latest"]):
            slot["latest"] = row
            if row.get("contract_name"):
                slot["name"] = str(row.get("contract_name") or slot["name"])
    ranked = [item for item in best.values() if item.get("signal")]
    ranked.sort(key=lambda item: (-int(item["peak"]), item["address"]))
    return ranked, other


def prioritize(
    candidates: list[dict[str, Any]],
    *,
    budget_cu: int = DEFAULT_BUDGET_CU,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep the hottest contracts that fit in the CU budget. The rest are deferred."""
    cap = max(0, int(budget_cu))
    ordered = sorted(
        candidates,
        key=lambda row: (-int(row.get("peak") or 0), str(row.get("address") or "")),
    )
    selected: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    spent = 0
    for row in ordered:
        if spent + PER_CONTRACT_CU > cap:
            deferred.append({
                "chain": row.get("chain") or "ethereum",
                "address": row.get("address") or "",
                "peak": int(row.get("peak") or 0),
                "reason": "cu budget",
            })
            continue
        selected.append(row)
        spent += PER_CONTRACT_CU
    return selected, deferred


def load_seed() -> list[dict[str, Any]]:
    try:
        raw = json.loads(_SEED.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    rows = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        peak = _num(item.get("peak_heat"))
        verdict = str(item.get("verdict") or "")
        rows.append({
            "chain": item.get("chain") or "ethereum",
            "address": item.get("address") or "",
            "heat": peak if verdict == "maybe" else 0,
            "blend_heat": 0,
            "blend_bucket": verdict if verdict in {"maybe", "yes", "no"} else "",
            "heat_breakdown": {"original_peak": peak} if peak > 0 else {},
            "contract_name": item.get("contract_name") or "",
            "created_at": "1970-01-01T00:00:00Z",
        })
    return rows


def _page(store: Any, table: str, select: str) -> tuple[list[dict[str, Any]], str]:
    req = getattr(store, "_req", None)
    if not callable(req):
        return [], "store has no remote query"
    rows: list[dict[str, Any]] = []
    offset = 0
    while offset < MAX_ROWS:
        query = {
            "select": select,
            "order": "created_at.asc",
            "limit": str(PAGE),
            "offset": str(offset),
        }
        try:
            batch = req("GET", table, query=query)
        except Exception as exc:  # noqa: BLE001 — a missing column falls back
            return rows, redact(str(exc))[:240]
        if not isinstance(batch, list) or not batch:
            break
        rows.extend(item for item in batch if isinstance(item, dict))
        if len(batch) < PAGE:
            break
        offset += PAGE
    if offset >= MAX_ROWS:
        return rows, "stopped after %d rows" % MAX_ROWS
    return rows, ""


def collect_candidates(store: Any) -> dict[str, Any]:
    """Every historical Maybe or heat signal, deduped, plus rows this job will not scan."""
    notes: list[str] = []
    rows: list[dict[str, Any]] = list(load_seed())
    scans, err = _page(
        store,
        "test_scan_runs",
        "address,chain,heat,blend_heat,blend_bucket,bucket,heat_breakdown,notes,drop_reason,contract_name,created_at,status,invariant_results",
    )
    if err and not scans:
        scans, err = _page(
            store,
            "test_scan_runs",
            "address,heat,blend_heat,blend_bucket,heat_breakdown,notes,contract_name,created_at",
        )
    if err:
        notes.append("test_scan_runs: " + err)
    rows.extend(scans)
    results, err = _page(
        store,
        "eth_scan_results",
        "address,heat,bucket,heat_breakdown,notes,invariant_results,created_at",
    )
    if err and not results:
        results, err = _page(store, "eth_scan_results", "address,heat,bucket,created_at")
    if err:
        notes.append("eth_scan_results: " + err)
    rows.extend(results)
    targets, err = _page(store, "eth_scan_targets", "address,chain,heat,bucket,heat_breakdown,updated_at")
    if err and not targets:
        targets, err = _page(store, "eth_scan_targets", "address,heat,bucket")
    if err:
        notes.append("eth_scan_targets: " + err)
    for target in targets:
        target.setdefault("created_at", target.get("updated_at") or "")
    rows.extend(targets)
    ethereum, other = fold_signals(rows)
    return {"ethereum": ethereum, "other_chain": other, "notes": notes, "rows_read": len(rows)}


def explain_fork(status: str, drainable: bool) -> str:
    """Plain description. No call data."""
    if drainable or status == "broken":
        return (
            "On a local fork, an unprivileged caller increased its own balance while the "
            "contract's balance fell. Nothing was broadcast."
        )
    if status in {"ok", "held"}:
        return "The conservation check held. An unprivileged caller did not take value from the contract."
    if status == "timeout":
        return "The local fork check stopped at its time limit before it finished."
    if status == "compile-skip":
        return "Fork verify did not run because the local check did not compile."
    if status == "skipped":
        return "Fork verify did not run."
    if status == "error":
        return "Fork verify stopped on an error before it could say whether value moved."
    if status == "not-run":
        return "Fork verify did not run."
    return "Fork verify finished as %s." % (status or "unknown")


def fork_from_result(result: Any) -> dict[str, Any]:
    breakdown = getattr(result, "heat_breakdown", None) or {}
    if not isinstance(breakdown, dict):
        breakdown = {}
    poc = breakdown.get("exploit_poc") if isinstance(breakdown.get("exploit_poc"), dict) else {}
    status = str(poc.get("status") or "")
    notes = [str(item) for item in (getattr(result, "notes", None) or []) if "fork-verify" in str(item).lower()]
    if not status:
        joined = " ".join(notes).lower()
        if "timeout" in joined:
            status = "timeout"
        elif "skipped" in joined:
            status = "skipped"
        elif "error" in joined:
            status = "error"
        elif notes:
            status = "ok"
        else:
            status = "not-run"
    drainable = bool(poc.get("drainable"))
    return {
        "status": "broken" if drainable else status,
        "drainable": drainable,
        "plain": explain_fork("broken" if drainable else status, drainable),
    }


def result_row(result: Any) -> dict[str, Any]:
    breakdown = getattr(result, "heat_breakdown", None) or {}
    return {
        "heat": _num(getattr(result, "heat", 0)),
        "blend_heat": 0,
        "blend_bucket": "",
        "heat_breakdown": breakdown if isinstance(breakdown, dict) else {},
        "notes": list(getattr(result, "notes", None) or []),
        "drop_reason": "",
    }


class RpcStop(RuntimeError):
    """The Alchemy budget or a hard provider error ended the pass."""


class CuProxy:
    """Forward JSON-RPC and charge Alchemy compute units. The upstream URL is not logged."""

    def __init__(self, upstream: str, cap: int):
        self.upstream = (upstream or "").strip()
        self.budget = CuBudget(cap)
        self.stop_reason = ""
        self._lock = threading.Lock()
        self._httpd: Optional[ThreadingHTTPServer] = None

    def start(self) -> str:
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    payload = json.loads(raw.decode("utf-8") or "{}")
                except json.JSONDecodeError:
                    payload = {}
                body, status = proxy.forward(payload)
                data = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, fmt: str, *args: Any) -> None:
                return

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        port = self._httpd.server_address[1]
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        return "http://127.0.0.1:%d" % port

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    def forward(self, payload: Any) -> tuple[Any, int]:
        if isinstance(payload, list):
            out = []
            status = 200
            for item in payload:
                body, code = self._one(item if isinstance(item, dict) else {})
                if code >= 400:
                    status = code
                out.append(body)
                if self.stop_reason:
                    break
            return out, status
        return self._one(payload if isinstance(payload, dict) else {})

    def _one(self, item: dict[str, Any]) -> tuple[dict[str, Any], int]:
        method = str(item.get("method") or "unknown")
        ident = item.get("id", 1)
        with self._lock:
            if self.stop_reason:
                return _rpc_error(ident, self.stop_reason), 200
            cost = int(_FORK_CU.get(method, CU_ESTIMATES.get(method, DEFAULT_UNKNOWN_CU)))
            if self.budget.spent + cost > self.budget.cap:
                self.stop_reason = "cu budget"
                return _rpc_error(ident, "cu budget"), 200
            self.budget.spent += cost
            self.budget.calls.append(method)
        status, parsed = _post_upstream(self.upstream, item)
        reason = _provider_stop(status, parsed)
        if reason:
            with self._lock:
                self.stop_reason = reason
        return parsed if isinstance(parsed, dict) else _rpc_error(ident, "bad upstream response"), status


def _rpc_error(ident: Any, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32000, "message": message}}


def _post_upstream(url: str, item: dict[str, Any]) -> tuple[int, Any]:
    delays = (0.0, 2.0, 4.0, 8.0)
    last_status = 599
    last_body: Any = _rpc_error(item.get("id", 1), "upstream failed")
    data = json.dumps(item).encode("utf-8")
    for delay in delays:
        if delay:
            time.sleep(delay)
        req = urlrequest.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urlrequest.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                last_status = getattr(resp, "status", 200) or 200
        except urlerror.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            last_status = int(exc.code)
        except Exception:  # noqa: BLE001
            return 599, last_body
        try:
            last_body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            last_body = {"error": {"message": "unreadable upstream"}}
        if not _is_transient_429(last_status, last_body):
            return last_status, last_body
    return last_status, last_body


def _blob(status: int, body: Any) -> str:
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            return "%s %s %s" % (status, err.get("code") or "", err.get("message") or "")
        return "%s %s" % (status, json.dumps(body)[:300])
    return str(status)


def _is_transient_429(status: int, body: Any) -> bool:
    text = _blob(status, body).lower()
    if "capacity" in text or "quota" in text or "monthly" in text:
        return False
    return status == 429 or " 429" in text or "rate limit" in text


def _provider_stop(status: int, body: Any) -> str:
    text = _blob(status, body).lower()
    if "capacity" in text or "quota" in text or "monthly" in text:
        return "monthly capacity"
    if status in {401, 403} or "unauthorized" in text or "forbidden" in text:
        return "auth"
    if _is_transient_429(status, body):
        return "rate limited"
    return ""


def _lock_rpc(url: str) -> None:
    """This process uses one URL. A 429 must not fall through to a public RPC."""

    def only(preferred: str = "") -> list[str]:
        chosen = (preferred or url or "").strip().rstrip("/")
        if not chosen:
            return []
        from eth_scanner.ingest.rpc_client import is_rpc_usable
        return [chosen] if is_rpc_usable(chosen) else []

    import eth_scanner.ingest.funds as funds
    import eth_scanner.invariants.live as live

    funds.resolve_rpc_urls = only  # type: ignore[method-assign]
    live.resolve_rpc_urls = only  # type: ignore[method-assign]


def _snapshot(candidate: dict[str, Any]) -> dict[str, Any]:
    latest = candidate.get("latest") if isinstance(candidate.get("latest"), dict) else {}
    return {
        "chain": "ethereum",
        "address": candidate["address"],
        "name": candidate.get("name") or latest.get("contract_name") or "",
        "peak": int(candidate.get("peak") or 0),
        "old_verdict": desk_verdict(latest),
        "old_heat": _num(latest.get("heat") if _num(latest.get("heat")) else latest.get("blend_heat")),
        "reasons": list(candidate.get("reasons") or []),
    }


def run_signal_rerun(
    store: Any,
    settings: Any,
    *,
    budget_cu: int = DEFAULT_BUDGET_CU,
    deadline_s: float = 3600.0,
    lease_wait_s: float = 1200.0,
    dry_run: bool = False,
    scan_one: Any = None,
) -> dict[str, Any]:
    """Collect, cut to the CU budget, then re-score. Fail soft on 429 and on the cap."""
    collected = collect_candidates(store)
    selected, deferred = prioritize(collected["ethereum"], budget_cu=budget_cu)
    plan = {
        "rows_read": collected["rows_read"],
        "signals": len(collected["ethereum"]),
        "selected": len(selected),
        "deferred_budget": deferred,
        "other_chain": collected["other_chain"],
        "notes": list(collected["notes"]),
        "estimate": estimate_cu(len(selected)),
        "budget_cu": int(budget_cu),
    }
    if dry_run:
        plan["status"] = "dry-run"
        plan["rerun"] = []
        plan["changes"] = []
        plan["cu_used"] = 0
        plan["selected_rows"] = [_snapshot(row) for row in selected]
        return plan

    from eth_scanner.feed.runner import acquire_scan_cycle, refresh_scan_cycle, release_scan_cycle
    from eth_scanner.ingest.rpc_client import RpcUnavailable

    upstream = str(getattr(settings, "eth_rpc_url", "") or "").strip()
    if not upstream:
        plan["status"] = "skipped"
        plan["notes"].append("ETH_RPC_URL unset")
        plan["rerun"] = []
        plan["changes"] = []
        plan["cu_used"] = 0
        return plan

    try:
        owner = acquire_scan_cycle(store, wait_s=lease_wait_s, poll_s=15.0)
    except TimeoutError:
        plan["status"] = "blocked"
        plan["notes"].append("another scan cycle holds the cursor")
        plan["rerun"] = []
        plan["changes"] = []
        plan["cu_used"] = 0
        return plan

    proxy = CuProxy(upstream, budget_cu)
    local = proxy.start()
    settings.eth_rpc_url = local
    settings.range_min_usd = 0
    settings.range_max_usd = None
    _lock_rpc(local)
    if scan_one is None:
        from eth_scanner.lane_a.worker import run_one as scan_one

    started = time.monotonic()
    rerun: list[dict[str, Any]] = []
    unfinished: list[dict[str, Any]] = []
    stop = ""
    try:
        for index, candidate in enumerate(selected):
            if proxy.stop_reason:
                stop = proxy.stop_reason
                unfinished = [_snapshot(row) for row in selected[index:]]
                break
            if time.monotonic() - started > deadline_s:
                stop = "deadline"
                unfinished = [_snapshot(row) for row in selected[index:]]
                break
            refresh_scan_cycle(store, owner, candidate["address"])
            before = _snapshot(candidate)
            try:
                result = scan_one(candidate["address"], settings=settings, store=store)
            except RpcUnavailable:
                stop = "rpc unavailable"
                unfinished = [_snapshot(row) for row in selected[index:]]
                break
            except Exception as exc:  # noqa: BLE001 — one contract must not end the pass
                before.update({
                    "new_verdict": before["old_verdict"],
                    "new_heat": before["old_heat"],
                    "fork": {"status": "error", "drainable": False, "plain": explain_fork("error", False)},
                    "error": redact(str(exc))[:200],
                    "changed": False,
                })
                rerun.append(before)
                if proxy.stop_reason:
                    stop = proxy.stop_reason
                    unfinished = [_snapshot(row) for row in selected[index + 1:]]
                    break
                continue
            after = result_row(result)
            new_verdict = desk_verdict(after)
            new_heat = _num(after["heat"])
            before.update({
                "new_verdict": new_verdict,
                "new_heat": new_heat,
                "fork": fork_from_result(result),
                "changed": new_verdict != before["old_verdict"] or new_heat != before["old_heat"],
            })
            rerun.append(before)
        else:
            stop = stop or "done"
    finally:
        release_scan_cycle(store, owner, stop or "signal rerun finished")
        proxy.stop()

    changes = [row for row in rerun if row.get("changed")]
    plan.update({
        "status": stop or "done",
        "rerun": rerun,
        "rerun_count": len(rerun),
        "changes": changes,
        "unfinished": unfinished,
        "cu_used": proxy.budget.spent,
        "cu_calls": len(proxy.budget.calls),
        "stop_reason": proxy.stop_reason,
    })
    return plan
