"""Cross-contract paths from an open entry to a sensitive shape.

A path is a lead. It does not add heat and it does not replace a detector.
Address reads are optional and read-only. Nothing is broadcast.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional

from eth_scanner.heuristics.invariant_pass import functions, match_brace, strip_comments
from eth_scanner.research.keccak import selector4

_CONTRACT = re.compile(r"\b(contract|library)\s+([A-Za-z_][A-Za-z0-9_]*)\b")
_GATE = re.compile(r"\bonly(?:Owner|Admin|Role|Guardian|Auth|Proxy)\b|\brequiresAuth\b", re.I)
_CALL = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_]*)\s*(?:\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\))?\s*\.\s*"
    r"([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)"
)
_VALUE = re.compile(
    r"\.(?:transfer|transferFrom|safeTransfer|safeTransferFrom)\s*\(|"
    r"\b_?(?:mint|burn|deposit|withdraw)\s*\(",
    re.I,
)
_SIG = re.compile(r"\becrecover\s*\(|\brecover\s*\(", re.I)
_NONCE = re.compile(r"\bnonces?\b", re.I)
_PUBLIC_ADDR = re.compile(
    r"\baddress\s+(?:public\s+immutable|immutable\s+public|public)\s+([A-Za-z_][A-Za-z0-9_]*)"
)
_ASSIGN = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([A-Za-z_][A-Za-z0-9_]*)\s*;"
)
_SKIP_NAMES = frozenset({
    "address", "uint", "uint256", "uint128", "uint8", "int", "int256", "bool",
    "bytes", "bytes32", "string", "memory", "calldata", "storage", "payable",
})
_SINK_METHODS = frozenset({
    "transfer", "transferfrom", "safetransfer", "safetransferfrom",
    "mint", "burn", "deposit", "withdraw",
})


def _params(header: str) -> list[str]:
    match = re.search(r"\((.*)\)", header or "", re.S)
    if not match:
        return []
    names = []
    for part in match.group(1).split(","):
        idents = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", part)
        if not idents:
            continue
        name = idents[-1]
        if name not in _SKIP_NAMES:
            names.append(name)
    return names


def _open_entry(fn: dict[str, Any]) -> bool:
    vis = str(fn.get("vis") or "")
    if "external" not in vis and "public" not in vis:
        return False
    if "view" in vis or vis == "constructor":
        return False
    return _GATE.search(str(fn.get("header") or "")) is None


def _contracts(source: str) -> list[dict[str, Any]]:
    clean = strip_comments(source or "", "solidity")
    rows = []
    for match in _CONTRACT.finditer(clean):
        brace = clean.find("{", match.end())
        if brace < 0:
            continue
        end = match_brace(clean, brace)
        body = clean[match.start():end + 1]
        fns = []
        for fn in functions(body, body, "solidity"):
            item = dict(fn)
            item["params"] = _params(str(fn.get("header") or ""))
            item["contract"] = match.group(2)
            fns.append(item)
        rows.append({
            "kind": match.group(1),
            "name": match.group(2),
            "body": body,
            "functions": fns,
        })
    return rows


def _tainted(fn: dict[str, Any]) -> set[str]:
    names = set(fn.get("params") or [])
    body = str(fn.get("body") or "")
    for match in _ASSIGN.finditer(body):
        if match.group(2) in names:
            names.add(match.group(1))
    return names


def _by_name(contracts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for contract in contracts:
        for fn in contract["functions"]:
            found.setdefault(str(fn.get("name") or ""), fn)
    return found


def _lead(kind: str, entry: dict[str, Any], sink: str, tainted: list[str], target: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "entry": "%s.%s" % (entry.get("contract"), entry.get("name")),
        "sink": sink,
        "tainted": tainted,
        "target": target,
        "heat_contribution": 0,
    }


def word_address(raw: str) -> str:
    text = (raw or "").strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    if len(text) < 40:
        return ""
    addr = text[-40:]
    try:
        if int(addr, 16) == 0:
            return ""
    except ValueError:
        return ""
    return "0x" + addr


def resolve_public(
    source: str,
    address: str,
    call: Optional[Callable[[str, str], str]],
) -> dict[str, str]:
    """Read public address getters. `call` is eth_call and may be omitted."""
    if not call or not address:
        return {}
    found: dict[str, str] = {}
    for name in _PUBLIC_ADDR.findall(source or ""):
        try:
            raw = call(address, selector4("%s()" % name))
        except Exception:
            continue
        decoded = word_address(str(raw or ""))
        if decoded:
            found[name] = decoded
    return found


def reachability_report(
    source: str,
    *,
    resolved: Optional[dict[str, str]] = None,
    address: str = "",
    call: Optional[Callable[[str, str], str]] = None,
) -> dict[str, Any]:
    """Return cross-contract leads. Path existence adds no heat."""
    contracts = _contracts(source or "")
    catalog = _by_name(contracts)
    targets = {str(k): word_address(str(v)) or str(v) for k, v in dict(resolved or {}).items()}
    targets.update(resolve_public(source or "", address, call))
    leads: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(kind: str, entry: dict[str, Any], sink: str, names: list[str], target: str) -> None:
        key = (kind, str(entry.get("name")), sink)
        if key in seen:
            return
        seen.add(key)
        leads.append(_lead(kind, entry, sink, names, target))

    for contract in contracts:
        if contract["kind"] == "library":
            continue
        for fn in contract["functions"]:
            if not _open_entry(fn):
                continue
            tainted = _tainted(fn)
            body = str(fn.get("body") or "")
            for match in _CALL.finditer(body):
                type_name, object_name, method, args = match.groups()
                object_name = object_name or type_name
                arg_names = [tok for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", args or "") if tok in tainted]
                other = catalog.get(method)
                library = next((row for row in contracts if row["kind"] == "library" and row["name"] == type_name), None)
                other_contract = ""
                if other and str(other.get("contract")) != contract["name"]:
                    other_contract = str(other.get("contract"))
                elif any(row["name"] == type_name and row["name"] != contract["name"] for row in contracts):
                    other_contract = type_name
                target = targets.get(object_name, "")
                if other_contract:
                    edges.append({
                        "from": "%s.%s" % (contract["name"], fn.get("name")),
                        "to": "%s.%s" % (other_contract, method),
                        "target": target,
                    })
                sink_body = str((other or {}).get("body") or "")
                method_is_sink = method.lower() in _SINK_METHODS or bool(_VALUE.search(sink_body))
                if library:
                    lib_fn = next((item for item in library["functions"] if item.get("name") == method), None)
                    if arg_names and lib_fn and _VALUE.search(str(lib_fn.get("body") or "")):
                        add("library-misuse", fn, "%s.%s" % (library["name"], method), arg_names, target)
                elif other_contract and arg_names and method_is_sink:
                    add("accounting-split", fn, "%s.%s" % (other_contract, method), arg_names, target)
            if _SIG.search(body):
                for other in contracts:
                    if other["name"] == contract["name"] or not _NONCE.search(other["body"]):
                        continue
                    called = any(
                        item.group(1) == other["name"] or (catalog.get(item.group(3)) or {}).get("contract") == other["name"]
                        for item in _CALL.finditer(body)
                    )
                    if called:
                        add("signature-nonce-split", fn, "%s.nonce" % other["name"], sorted(tainted), "")

    return {
        "status": "ok" if leads else "no-path",
        "leads": leads,
        "edges": edges,
        "resolved": targets,
        "heat_contribution": 0,
        "note": "A cross-contract path is a lead. It does not add heat, and the existing detectors still run.",
    }
