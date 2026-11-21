"""Load touched storage into a local simulation from a read-only trace or proof.

``debug_traceTransaction`` with ``prestateTracer`` is preferred. When debug
is missing, ``eth_getProof`` then ``eth_getStorageAt`` read the slots the
caller already named (EIP-1967 by default). Loaded slots are evidence.
They do not add heat.

``anvil_setStorageAt`` runs only against a loopback anvil. A public URL is
refused. A missing method or HTTP 429 leaves the simulation on its current
state.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Optional

from eth_scanner.chain.cu_budget import (
    DEFAULT_STORAGE_CU,
    CuBudget,
    CuBudgetExceeded,
    cap_from_env,
)
from eth_scanner.chain.trace_seeds import _call, _fail_note, _rate_limited, _unsupported
from eth_scanner.deep.blend.ityfuzz_runner import local_rpc
from eth_scanner.feed.lists import normalize_address
from eth_scanner.ingest.rpc_client import RpcTransientError, RpcUnavailable

RpcFn = Callable[..., Any]

# EIP-1967 implementation and admin slots. Used only when no trace named slots.
_IMPL_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
_ADMIN_SLOT = "0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103"
_DEFAULT_SLOTS = ("0x" + "00" * 32, _IMPL_SLOT, _ADMIN_SLOT)
_MAX_SLOTS = 32
_MAX_TRACES = 1


def load_storage(
    address: str,
    rpc_url: str = "",
    *,
    tx_hashes: Optional[list[str]] = None,
    slots: Optional[list[str]] = None,
    budget: Optional[CuBudget] = None,
    rpc: Optional[RpcFn] = None,
    local_rpc_url: str = "",
) -> dict[str, Any]:
    """Read touched slots and, when asked, copy them onto a local anvil."""
    target = normalize_address(address)
    book = budget or CuBudget(cap_from_env("ETH_SCANNER_STORAGE_CU", DEFAULT_STORAGE_CU))
    caller = rpc or _default_rpc
    body: dict[str, Any] = {
        "status": "skipped",
        "heat_contribution": 0,
        "label": "evidence only",
        "note": "",
        "address": target,
        "slots": [],
        "applied_local": False,
        "degraded": False,
        "source": "",
        "cu": {},
    }
    if not target:
        body["note"] = "address missing"
        body["cu"] = book.snapshot()
        return body
    if not (rpc_url or "").strip():
        body["note"] = "ETH_RPC_URL unset — simulation keeps its current state"
        body["cu"] = book.snapshot()
        return body

    loaded: list[dict[str, str]] = []
    source = ""
    degraded = False
    note = ""
    try:
        loaded, source, degraded, note = _read_slots(
            caller, rpc_url, target, list(tx_hashes or []), list(slots or []), book,
        )
    except CuBudgetExceeded:
        degraded = True
        note = "compute-unit cap reached while reading storage"
    except (RpcUnavailable, RpcTransientError, RuntimeError, OSError, TimeoutError) as exc:
        degraded = True
        note = _fail_note(exc)

    applied = False
    if loaded and (local_rpc_url or "").strip():
        try:
            applied, apply_note = apply_local(local_rpc_url, target, loaded, rpc=caller)
            if apply_note:
                note = (note + "; " if note else "") + apply_note
            if not applied:
                degraded = True
        except (RpcUnavailable, RpcTransientError, RuntimeError, OSError, TimeoutError) as exc:
            degraded = True
            note = (note + "; " if note else "") + "local storage not applied (%s)" % str(exc)[:120]

    body["slots"] = loaded
    body["source"] = source
    body["applied_local"] = applied
    body["degraded"] = degraded
    body["note"] = note or ("touched storage loaded" if loaded else "no storage slots in the sample")
    if degraded and not loaded:
        body["status"] = "degraded"
    elif loaded:
        body["status"] = "degraded" if degraded else "ok"
    else:
        body["status"] = "empty"
    body["cu"] = book.snapshot()
    return body


def apply_local(
    local_rpc_url: str,
    address: str,
    slots: list[dict[str, str]],
    *,
    rpc: Optional[RpcFn] = None,
) -> tuple[bool, str]:
    """Copy slots with ``anvil_setStorageAt``. Refuses any non-loopback URL."""
    if not local_rpc(local_rpc_url):
        return False, "refused storage write on a non-local RPC"
    caller = rpc or _default_rpc
    target = normalize_address(address)
    for row in slots[:_MAX_SLOTS]:
        slot = _slot(row.get("slot") or "")
        value = _word(row.get("value") or "")
        if not slot or not value:
            continue
        caller(local_rpc_url, "anvil_setStorageAt", [target, slot, value], timeout_s=8.0)
    return True, "slots copied onto the local anvil"


def write_evidence(dest: Path, report: dict[str, Any]) -> Path:
    path = Path(dest) / "corpus" / "storage.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "heat_contribution": 0,
        "label": "slots loaded into the local simulation",
        "source": report.get("source") or "",
        "applied_local": bool(report.get("applied_local")),
        "slots": list(report.get("slots") or []),
        "cu": report.get("cu") or {},
        "note": report.get("note") or "",
    }, indent=2), encoding="utf-8")
    return path


def _read_slots(
    rpc: RpcFn,
    url: str,
    target: str,
    tx_hashes: list[str],
    named: list[str],
    budget: CuBudget,
) -> tuple[list[dict[str, str]], str, bool, str]:
    degraded = False
    note = ""
    for digest in [item for item in tx_hashes if item][:_MAX_TRACES]:
        if not budget.allow("debug_traceTransaction"):
            break
        try:
            traced = _call(rpc, url, "debug_traceTransaction", [digest, {
                "tracer": "prestateTracer",
                "tracerConfig": {"diffMode": False},
            }], budget)
        except CuBudgetExceeded:
            raise
        except (RpcUnavailable, RpcTransientError, RuntimeError, OSError, TimeoutError) as exc:
            if _unsupported(exc):
                degraded = True
                note = "debug_traceTransaction unavailable"
                break
            if _rate_limited(exc):
                return [], "", True, _fail_note(exc)
            raise
        slots = _slots_from_prestate(traced, target)
        if slots:
            return slots, "debug_traceTransaction", False, ""
        note = "prestate tracer returned no storage for the target"

    wanted = _named_slots(named)
    try:
        proof = _call(rpc, url, "eth_getProof", [target, wanted, "latest"], budget)
    except CuBudgetExceeded:
        raise
    except (RpcUnavailable, RpcTransientError, RuntimeError, OSError, TimeoutError) as exc:
        if not _unsupported(exc):
            if _rate_limited(exc):
                return [], "", True, _fail_note(exc)
            raise
        proof = None
    if isinstance(proof, dict):
        slots = _slots_from_proof(proof)
        return slots, "eth_getProof", degraded, note

    slots = []
    for slot in wanted:
        if not budget.allow("eth_getStorageAt"):
            degraded = True
            note = (note + "; " if note else "") + "compute-unit cap reached"
            break
        try:
            value = _call(rpc, url, "eth_getStorageAt", [target, slot, "latest"], budget)
        except CuBudgetExceeded:
            degraded = True
            note = "compute-unit cap reached"
            break
        except (RpcUnavailable, RpcTransientError, RuntimeError, OSError, TimeoutError) as exc:
            if _rate_limited(exc) or _unsupported(exc):
                return slots, "eth_getStorageAt", True, _fail_note(exc)
            raise
        word = _word(str(value or ""))
        if word:
            slots.append({"slot": slot, "value": word, "source": "eth_getStorageAt"})
    return slots, "eth_getStorageAt", degraded, note


def _slots_from_prestate(payload: Any, target: str) -> list[dict[str, str]]:
    node = payload
    if isinstance(payload, dict) and isinstance(payload.get("pre"), dict):
        node = payload["pre"]
    if not isinstance(node, dict):
        return []
    account = None
    for key, value in node.items():
        if normalize_address(str(key)) == target and isinstance(value, dict):
            account = value
            break
    storage = (account or {}).get("storage") if isinstance(account, dict) else None
    if not isinstance(storage, dict):
        return []
    rows = []
    for slot, value in storage.items():
        cleaned_slot = _slot(str(slot))
        word = _word(str(value))
        if not cleaned_slot or not word:
            continue
        rows.append({"slot": cleaned_slot, "value": word, "source": "debug_traceTransaction"})
        if len(rows) >= _MAX_SLOTS:
            break
    return rows


def _slots_from_proof(proof: dict[str, Any]) -> list[dict[str, str]]:
    rows = []
    for item in proof.get("storageProof") or []:
        if not isinstance(item, dict):
            continue
        slot = _slot(str(item.get("key") or ""))
        word = _word(str(item.get("value") or ""))
        if not slot or not word:
            continue
        rows.append({"slot": slot, "value": word, "source": "eth_getProof"})
        if len(rows) >= _MAX_SLOTS:
            break
    return rows


def _named_slots(named: list[str]) -> list[str]:
    rows: list[str] = []
    for raw in list(named) + list(_DEFAULT_SLOTS):
        slot = _slot(str(raw))
        if slot and slot not in rows:
            rows.append(slot)
        if len(rows) >= _MAX_SLOTS:
            break
    return rows


def _slot(raw: str) -> str:
    text = (raw or "").strip().lower()
    if not text.startswith("0x"):
        text = "0x" + text
    body = text[2:]
    if not body or any(ch not in "0123456789abcdef" for ch in body) or len(body) > 64:
        return ""
    return "0x" + body.rjust(64, "0")


def _word(raw: str) -> str:
    return _slot(raw)


def _default_rpc(url: str, method: str, params: list[Any], timeout_s: float = 8.0) -> Any:
    from eth_scanner.ingest.rpc_client import rpc_call
    return rpc_call(url, method, params, timeout_s=timeout_s)
