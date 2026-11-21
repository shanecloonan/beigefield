"""Historical calldata seeds for the local fuzz harness.

Reads a bounded sample of past calls with Alchemy asset transfers, then
``trace_filter`` or logs, and enriches them with ``debug_traceTransaction``
when the endpoint allows it. The seeds are calldata the local harness
replays. They are not transactions and they do not add heat.

Missing methods and HTTP 429 stop the sample and return whatever was
already collected. The scan then behaves as it did with no seeds.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Optional

from eth_scanner.chain.cu_budget import (
    DEFAULT_TRACE_SEED_CU,
    CuBudget,
    CuBudgetExceeded,
    cap_from_env,
)
from eth_scanner.feed.lists import normalize_address
from eth_scanner.ingest.rpc_client import RpcTransientError, RpcUnavailable

RpcFn = Callable[..., Any]

_HEX = re.compile(r"^0x[0-9a-fA-F]*$")
_MAX_SEEDS = 16
_MAX_CALLDATA_BYTES = 512
_LOG_LOOKBACK = 2_000
_TRACE_LOOKBACK = 5_000


def collect_seeds(
    address: str,
    rpc_url: str = "",
    *,
    budget: Optional[CuBudget] = None,
    rpc: Optional[RpcFn] = None,
) -> dict[str, Any]:
    """Return a heatless seed corpus. Never raises for a provider failure."""
    target = normalize_address(address)
    book = budget or CuBudget(cap_from_env("ETH_SCANNER_TRACE_SEED_CU", DEFAULT_TRACE_SEED_CU))
    caller = rpc or _default_rpc
    body: dict[str, Any] = {
        "status": "skipped",
        "heat_contribution": 0,
        "label": "evidence only",
        "note": "",
        "address": target,
        "seeds": [],
        "sequences": [],
        "degraded": False,
        "sources": [],
        "cu": {},
    }
    if not target:
        body["note"] = "address missing"
        body["cu"] = book.snapshot()
        return body
    if not (rpc_url or "").strip():
        body["note"] = "ETH_RPC_URL unset — fuzz keeps its unseeded harness"
        body["cu"] = book.snapshot()
        return body

    note = ""
    degraded = False
    hashes: list[str] = []
    sources: list[str] = []
    try:
        hashes, source, degraded, note = _discover_hashes(caller, rpc_url, target, book)
        if source:
            sources.append(source)
    except CuBudgetExceeded:
        degraded = True
        note = "compute-unit cap reached while listing history"
    except (RpcUnavailable, RpcTransientError, RuntimeError, OSError, TimeoutError) as exc:
        degraded = True
        note = _fail_note(exc)

    seeds: list[dict[str, Any]] = []
    sequences: list[dict[str, Any]] = []
    if hashes and not book.stopped:
        try:
            seeds, sequences, enrich_source, enrich_degraded, enrich_note = _enrich(
                caller, rpc_url, target, hashes, book,
            )
            if enrich_source:
                sources.append(enrich_source)
            degraded = degraded or enrich_degraded
            if enrich_note:
                note = (note + "; " if note else "") + enrich_note
        except CuBudgetExceeded:
            degraded = True
            note = (note + "; " if note else "") + "compute-unit cap reached while reading calldata"
        except (RpcUnavailable, RpcTransientError, RuntimeError, OSError, TimeoutError) as exc:
            degraded = True
            note = (note + "; " if note else "") + _fail_note(exc)

    body["seeds"] = seeds
    body["sequences"] = sequences
    body["sources"] = sources
    body["degraded"] = degraded
    body["note"] = note or ("no historical calls in the sample" if not seeds else "historical calldata loaded")
    body["status"] = "degraded" if degraded and not seeds else ("ok" if seeds else ("degraded" if degraded else "empty"))
    body["cu"] = book.snapshot()
    return body


def write_corpora(dest: Path, corpus: dict[str, Any]) -> list[str]:
    """Write the same seeds for Echidna, Medusa, ityfuzz, and Forge.

    The files are inputs to the local harness. They are not broadcast.
    """
    root = Path(dest) / "corpus"
    seeds = list(corpus.get("seeds") or [])
    sequences = list(corpus.get("sequences") or [])
    payload = {
        "heat_contribution": 0,
        "label": "historical calldata, local replay only",
        "seeds": seeds,
        "sequences": sequences,
        "cu": corpus.get("cu") or {},
        "note": corpus.get("note") or "",
    }
    written: list[str] = []
    for rel in (
        "seeds.json",
        "echidna/seeds.json",
        "medusa/sequences.json",
        "forge/seeds.json",
    ):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        written.append(str(path))
    ity = root / "ityfuzz" / "calls.txt"
    ity.parent.mkdir(parents=True, exist_ok=True)
    lines = [str(row.get("calldata") or "") for row in seeds if row.get("calldata")]
    ity.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    written.append(str(ity))
    return written


def _default_rpc(url: str, method: str, params: list[Any], timeout_s: float = 8.0) -> Any:
    from eth_scanner.ingest.rpc_client import rpc_call
    return rpc_call(url, method, params, timeout_s=timeout_s)


def _discover_hashes(rpc: RpcFn, url: str, target: str, budget: CuBudget) -> tuple[list[str], str, bool, str]:
    try:
        result = _call(rpc, url, "alchemy_getAssetTransfers", [{
            "fromBlock": "0x0",
            "toBlock": "latest",
            "toAddress": target,
            "category": ["external"],
            "maxCount": "0x14",
            "order": "desc",
            "excludeZeroValue": False,
            "withMetadata": False,
        }], budget)
    except CuBudgetExceeded:
        raise
    except (RpcUnavailable, RpcTransientError, RuntimeError, OSError, TimeoutError) as exc:
        if not _unsupported(exc):
            if _rate_limited(exc):
                return [], "", True, _fail_note(exc)
            raise
        result = None
    if result is not None:
        rows = result.get("transfers") if isinstance(result, dict) else None
        hashes = _hashes_from_transfers(rows or [])
        return hashes, "alchemy_getAssetTransfers", False, ""

    head = _block_number(rpc, url, budget)
    start = max(0, head - _TRACE_LOOKBACK)
    try:
        traced = _call(rpc, url, "trace_filter", [{
            "fromBlock": hex(start),
            "toBlock": "latest",
            "toAddress": [target],
            "count": 20,
        }], budget)
    except CuBudgetExceeded:
        raise
    except (RpcUnavailable, RpcTransientError, RuntimeError, OSError, TimeoutError) as exc:
        if not _unsupported(exc):
            if _rate_limited(exc):
                return [], "", True, _fail_note(exc)
            raise
        traced = None
    if isinstance(traced, list):
        hashes = []
        for row in traced:
            if not isinstance(row, dict):
                continue
            digest = str(row.get("transactionHash") or "")
            if digest and digest not in hashes:
                hashes.append(digest)
            if len(hashes) >= 8:
                break
        return hashes, "trace_filter", False, ""

    log_start = max(0, head - _LOG_LOOKBACK)
    logs = _call(rpc, url, "eth_getLogs", [{
        "fromBlock": hex(log_start),
        "toBlock": "latest",
        "address": target,
    }], budget)
    hashes = []
    if isinstance(logs, list):
        for row in logs:
            if not isinstance(row, dict):
                continue
            digest = str(row.get("transactionHash") or "")
            if digest and digest not in hashes:
                hashes.append(digest)
            if len(hashes) >= 8:
                break
    return hashes, "eth_getLogs", False, ""


def _enrich(
    rpc: RpcFn,
    url: str,
    target: str,
    hashes: list[str],
    budget: CuBudget,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str, bool, str]:
    seeds: list[dict[str, Any]] = []
    sequences: list[dict[str, Any]] = []
    source = ""
    degraded = False
    note = ""
    debug_dead = False
    for digest in hashes:
        if len(seeds) >= _MAX_SEEDS or budget.stopped:
            break
        calls: list[dict[str, Any]] = []
        if not debug_dead and budget.allow("debug_traceTransaction"):
            try:
                traced = _call(rpc, url, "debug_traceTransaction", [digest, {"tracer": "callTracer"}], budget)
                calls = _calls_from_tracer(traced, target)
                for call in calls:
                    call["tx"] = digest
                source = source or "debug_traceTransaction"
            except CuBudgetExceeded:
                degraded = True
                note = "compute-unit cap reached"
                break
            except (RpcUnavailable, RpcTransientError, RuntimeError, OSError, TimeoutError) as exc:
                if _unsupported(exc):
                    debug_dead = True
                elif _rate_limited(exc):
                    degraded = True
                    note = _fail_note(exc)
                    break
                else:
                    raise
        if not calls and budget.allow("eth_getTransactionByHash"):
            try:
                tx = _call(rpc, url, "eth_getTransactionByHash", [digest], budget)
            except CuBudgetExceeded:
                degraded = True
                note = "compute-unit cap reached"
                break
            except (RpcUnavailable, RpcTransientError, RuntimeError, OSError, TimeoutError) as exc:
                if _rate_limited(exc) or _unsupported(exc):
                    degraded = True
                    note = _fail_note(exc)
                    break
                raise
            calls = _calls_from_tx(tx, target)
            source = source or "eth_getTransactionByHash"
        if not calls:
            continue
        sequence = {"tx": digest, "calls": calls[:8]}
        sequences.append(sequence)
        for call in sequence["calls"]:
            if len(seeds) >= _MAX_SEEDS:
                break
            if any(existing["calldata"] == call["calldata"] for existing in seeds):
                continue
            seeds.append(call)
    return seeds, sequences, source, degraded, note


def _calls_from_tracer(node: Any, target: str, depth: int = 0) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if not isinstance(node, dict) or depth > 8:
        return found
    to = normalize_address(str(node.get("to") or ""))
    calldata = _clean_calldata(str(node.get("input") or ""))
    if to == target and calldata:
        found.append({
            "calldata": calldata,
            "value_wei": _hex_int(node.get("value")),
            "depth": depth,
            "tx": "",
            "source": "debug_traceTransaction",
        })
    for child in node.get("calls") or []:
        found.extend(_calls_from_tracer(child, target, depth + 1))
        if len(found) >= 8:
            break
    return found[:8]


def _calls_from_tx(tx: Any, target: str) -> list[dict[str, Any]]:
    if not isinstance(tx, dict):
        return []
    if normalize_address(str(tx.get("to") or "")) != target:
        return []
    calldata = _clean_calldata(str(tx.get("input") or ""))
    if not calldata:
        return []
    return [{
        "calldata": calldata,
        "value_wei": _hex_int(tx.get("value")),
        "depth": 0,
        "tx": str(tx.get("hash") or ""),
        "source": "eth_getTransactionByHash",
    }]


def _hashes_from_transfers(rows: list[Any]) -> list[str]:
    hashes: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        digest = str(row.get("hash") or "")
        if digest and digest not in hashes:
            hashes.append(digest)
        if len(hashes) >= 8:
            break
    return hashes


def _block_number(rpc: RpcFn, url: str, budget: CuBudget) -> int:
    raw = _call(rpc, url, "eth_blockNumber", [], budget)
    try:
        return int(str(raw), 16)
    except (TypeError, ValueError):
        return 0


def _call(rpc: RpcFn, url: str, method: str, params: list[Any], budget: CuBudget) -> Any:
    key = method + ":" + json.dumps(params, sort_keys=True, default=str)
    if key in budget.cache:
        return budget.cache[key]
    if not budget.allow(method):
        raise CuBudgetExceeded(method)
    budget.charge(method)
    result = rpc(url, method, params, timeout_s=8.0)
    budget.cache[key] = result
    return result


def _clean_calldata(raw: str) -> str:
    text = (raw or "").strip().lower()
    if not _HEX.match(text):
        return ""
    body = text[2:]
    if len(body) < 8 or len(body) % 2 != 0:
        return ""
    if len(body) // 2 > _MAX_CALLDATA_BYTES:
        return ""
    return "0x" + body


def _hex_int(value: Any) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, int):
        return max(0, value)
    text = str(value).strip().lower()
    try:
        if text.startswith("0x"):
            return int(text, 16)
        if "." in text:
            return int(float(text))
        return int(text, 10)
    except (TypeError, ValueError):
        return 0


def _unsupported(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(token in text for token in (
        "32601",
        "method not found",
        "method not available",
        "not supported",
        "unsupported",
        "does not exist",
        "not available",
    ))


def _rate_limited(exc: BaseException) -> bool:
    text = str(exc).lower()
    return isinstance(exc, RpcTransientError) or "429" in text or "rate limit" in text or "too many" in text


def _fail_note(exc: BaseException) -> str:
    text = str(exc).replace("\n", " ")
    if _rate_limited(exc):
        return "rpc rate limited — seeds skipped, harness unchanged (%s)" % text[:140]
    return "history read failed — seeds skipped (%s)" % text[:140]
