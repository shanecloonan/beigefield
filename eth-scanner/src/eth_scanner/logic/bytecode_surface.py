"""Selectors, mutability, storage, and proxy resolution from bytecode.

evmole (MIT) and whatsabi (MIT) run as external tools. Their results are
unioned. A missing tool is a skip. The prefix check only recognizes the
EIP-7702 delegation designator and the EIP-1167 clone pattern; it is not a
substitute for either tool.

Recovered selectors become local harness calls and a shorter invariant
catalog. Nothing here is broadcast, and calldata is not stored.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Optional

PINS = {
    "evmole": {
        "version": "0.10.1",
        "license": "MIT",
        "upstream": "https://github.com/cdump/evmole",
    },
    "whatsabi": {
        "version": "0.30.0",
        "license": "MIT",
        "upstream": "https://github.com/shazow/whatsabi",
    },
}

SURFACE_CAP = 2
_MAX_FUNCTIONS = 128
_MAX_SLOTS = 64
_MAX_CALLS = 8

# Standard signatures the harness already knows how to type. Not a call recipe.
_KNOWN: dict[str, tuple[str, str, str]] = {
    "01e1d114": ("totalAssets", "", "view"),
    "18160ddd": ("totalSupply", "", "view"),
    "70a08231": ("balanceOf", "address", "view"),
    "07a2d13a": ("convertToAssets", "uint256", "view"),
    "c6e6f592": ("convertToShares", "uint256", "view"),
    "38d52e0f": ("asset", "", "view"),
    "8da5cb5b": ("owner", "", "view"),
    "6e553f65": ("deposit", "uint256,address", "nonpayable"),
    "b6b55f25": ("deposit", "uint256", "nonpayable"),
    "d0e30db0": ("deposit", "", "payable"),
    "94bf804d": ("mint", "uint256,address", "nonpayable"),
    "b460af94": ("withdraw", "uint256,address,address", "nonpayable"),
    "2e1a7d4d": ("withdraw", "uint256", "nonpayable"),
    "3ccfd60b": ("withdraw", "", "nonpayable"),
    "ba087652": ("redeem", "uint256,address,address", "nonpayable"),
    "db006a75": ("redeem", "uint256", "nonpayable"),
    "a9059cbb": ("transfer", "address,uint256", "nonpayable"),
    "23b872dd": ("transferFrom", "address,address,uint256", "nonpayable"),
}

_VALUE = frozenset({
    "b460af94", "2e1a7d4d", "3ccfd60b", "ba087652", "db006a75",
    "a9059cbb", "23b872dd",
})
_ACTIONS = {
    "deposit": frozenset({"6e553f65", "b6b55f25", "d0e30db0"}),
    "withdraw": frozenset({"b460af94", "2e1a7d4d", "3ccfd60b"}),
    "redeem": frozenset({"ba087652", "db006a75"}),
}
_MUTABILITY = {"view", "pure", "payable", "nonpayable"}
def _safe_type(token: str) -> bool:
    if token in {"address", "bool", "bytes32"}:
        return True
    match = re.fullmatch(r"u?int(\d+)?", token)
    if not match:
        return False
    width = match.group(1)
    if width is None:
        return True
    size = int(width)
    return 8 <= size <= 256 and size % 8 == 0
_ADDR = re.compile(r"^0x[0-9a-f]{40}$")
_CLONE = "363d3d373d3d3d363d73"
_CLONE_TAIL = "5af43d82803e903d91602b57fd5bf3"
_PROXY_KINDS = {
    "eip1967proxy": "eip1967",
    "eip1967": "eip1967",
    "eip1167": "eip1167",
    "fixedproxy": "eip1167",
    "minimalproxy": "eip1167",
    "clone": "eip1167",
    "eip7702": "eip7702",
    "eip-7702": "eip7702",
    "proxiable": "eip1822",
    "eip1822": "eip1822",
    "beacon": "beacon",
    "eip1967beacon": "beacon",
}


def _selector(raw: Any) -> str:
    text = str(raw or "").lower().replace("0x", "")
    text = "".join(ch for ch in text if ch in "0123456789abcdef")
    if len(text) < 8:
        return ""
    return text[:8]


def _address(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    if not text:
        return ""
    if not text.startswith("0x"):
        text = "0x" + text
    text = "0x" + "".join(ch for ch in text[2:] if ch in "0123456789abcdef")
    if not _ADDR.match(text) or text == "0x" + "00" * 20:
        return ""
    return text


def _mutability(raw: Any, payable: Any = None) -> str:
    text = str(raw or "").strip().lower()
    if text in _MUTABILITY:
        return text
    if payable is True:
        return "payable"
    return ""


def _args(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, (list, tuple)):
        parts = [str(item).strip() for item in raw]
    else:
        parts = [part.strip() for part in str(raw).split(",")]
    kept: list[str] = []
    for part in parts:
        if not part:
            continue
        token = part.split()[0].lower()
        if token == "uint":
            token = "uint256"
        if token == "int":
            token = "int256"
        if not _safe_type(token):
            return ""
        kept.append(token)
    return ",".join(kept)


def _kind(raw: Any) -> str:
    text = re.sub(r"[^a-z0-9]+", "", str(raw or "").lower())
    if not text:
        return ""
    if text in _PROXY_KINDS:
        return _PROXY_KINDS[text]
    for name, kind in _PROXY_KINDS.items():
        if name in text:
            return kind
    return ""


def _fn_row(raw: Any, source: str) -> Optional[dict[str, Any]]:
    if isinstance(raw, str):
        selector = _selector(raw)
        if not selector:
            return None
        return {"selector": selector, "arguments": "", "mutability": "", "sources": [source]}
    if not isinstance(raw, dict):
        selector = _selector(getattr(raw, "selector", ""))
        if not selector:
            return None
        raw = {
            "selector": selector,
            "arguments": getattr(raw, "arguments", "") or "",
            "state_mutability": getattr(raw, "state_mutability", "") or getattr(raw, "stateMutability", ""),
        }
    selector = _selector(raw.get("selector") or raw.get("sig") or "")
    if not selector:
        return None
    return {
        "selector": selector,
        "arguments": _args(raw.get("arguments") if "arguments" in raw else raw.get("args")),
        "mutability": _mutability(raw.get("state_mutability") or raw.get("stateMutability") or raw.get("mutability"), raw.get("payable")),
        "sources": [source],
    }


def _storage_row(raw: Any) -> Optional[dict[str, Any]]:
    if not isinstance(raw, dict):
        slot = getattr(raw, "slot", None)
        if slot is None:
            return None
        raw = {"slot": slot, "offset": getattr(raw, "offset", 0), "type": getattr(raw, "type", "")}
    slot = str(raw.get("slot") or raw.get("label") or "").strip().lower()
    if not slot:
        return None
    if slot.startswith("0x"):
        slot = slot[2:]
    slot = "".join(ch for ch in slot if ch in "0123456789abcdef")
    if not slot:
        return None
    try:
        offset = int(raw.get("offset") or 0)
    except (TypeError, ValueError):
        offset = 0
    return {
        "slot": slot[:64],
        "offset": max(0, offset),
        "type": str(raw.get("type") or "")[:40],
    }


def _proxy_from(raw: Any) -> tuple[str, str]:
    if isinstance(raw, dict):
        kind = _kind(raw.get("kind") or raw.get("name") or raw.get("type"))
        impl = _address(raw.get("implementation") or raw.get("address") or raw.get("resolvedAddress") or raw.get("target"))
        return kind, impl
    kind = _kind(getattr(raw, "kind", "") or getattr(raw, "name", "") or type(raw).__name__)
    impl = _address(
        getattr(raw, "implementation", "")
        or getattr(raw, "resolved_address", "")
        or getattr(raw, "address", "")
    )
    return kind, impl


def normalize_tool(blob: Any, source: str) -> dict[str, Any]:
    """One tool's JSON or object, reduced to functions, slots, and a proxy."""
    if blob is None:
        return {"functions": [], "storage": [], "proxy_kind": "", "implementation": ""}
    if not isinstance(blob, dict):
        blob = {
            "functions": getattr(blob, "functions", None) or [],
            "storage": getattr(blob, "storage", None) or [],
            "proxies": getattr(blob, "proxies", None) or getattr(blob, "proxy", None) or [],
        }
    functions = []
    for row in list(blob.get("functions") or blob.get("selectors") or [])[:_MAX_FUNCTIONS]:
        parsed = _fn_row(row, source)
        if parsed:
            functions.append(parsed)
    storage = []
    for row in list(blob.get("storage") or blob.get("slots") or [])[:_MAX_SLOTS]:
        parsed = _storage_row(row)
        if parsed:
            storage.append(parsed)
    kind = _kind(blob.get("proxy_kind") or blob.get("kind"))
    impl = _address(blob.get("implementation"))
    if blob.get("eip7702"):
        kind = kind or "eip7702"
        impl = impl or _address(blob.get("eip7702"))
    for row in list(blob.get("proxies") or []):
        found_kind, found_impl = _proxy_from(row)
        kind = kind or found_kind
        impl = impl or found_impl
    return {"functions": functions, "storage": storage, "proxy_kind": kind, "implementation": impl}


def union_reports(*reports: dict[str, Any]) -> dict[str, Any]:
    """Merge tool reports. evmole mutability wins. Selectors are unique."""
    by_sel: dict[str, dict[str, Any]] = {}
    storage: list[dict[str, Any]] = []
    seen_slots: set[tuple[str, int]] = set()
    kind = ""
    impl = ""
    for report in reports:
        if not report:
            continue
        for row in report.get("functions") or []:
            selector = str(row.get("selector") or "")
            if not selector:
                continue
            current = by_sel.get(selector)
            sources = list(row.get("sources") or [])
            prefer = "evmole" in sources
            if current is None:
                by_sel[selector] = {
                    "selector": selector,
                    "arguments": row.get("arguments") or "",
                    "mutability": row.get("mutability") or "",
                    "sources": sources,
                }
                continue
            current["sources"] = sorted(set(current["sources"]) | set(sources))
            if prefer or not current["arguments"]:
                if row.get("arguments"):
                    current["arguments"] = row["arguments"]
            if prefer or not current["mutability"]:
                if row.get("mutability"):
                    current["mutability"] = row["mutability"]
        for row in report.get("storage") or []:
            key = (str(row.get("slot") or ""), int(row.get("offset") or 0))
            if key in seen_slots or not key[0]:
                continue
            seen_slots.add(key)
            storage.append({"slot": key[0], "offset": key[1], "type": str(row.get("type") or "")[:40]})
        if not kind and report.get("proxy_kind"):
            kind = str(report["proxy_kind"])
        if not impl and report.get("implementation"):
            impl = str(report["implementation"])
    functions = [by_sel[key] for key in sorted(by_sel)]
    for row in functions:
        known = _KNOWN.get(row["selector"])
        if known and not row["arguments"]:
            row["arguments"] = known[1]
        if known and not row["mutability"]:
            row["mutability"] = known[2]
        row["name"] = known[0] if known else ""
    return {
        "functions": functions[:_MAX_FUNCTIONS],
        "storage": storage[:_MAX_SLOTS],
        "proxy_kind": kind,
        "implementation": impl,
    }


def prefix_report(bytecode: str) -> dict[str, Any]:
    """EIP-7702 designator and EIP-1167 clone. No other pattern matching."""
    raw = _hex(bytecode)
    report = {"functions": [], "storage": [], "proxy_kind": "", "implementation": ""}
    if raw.startswith("ef0100") and len(raw) >= 46:
        report["proxy_kind"] = "eip7702"
        report["implementation"] = _address(raw[6:46])
        return report
    start = raw.find(_CLONE)
    if start >= 0 and start <= 64:
        addr = raw[start + len(_CLONE):start + len(_CLONE) + 40]
        tail = raw[start + len(_CLONE) + 40:start + len(_CLONE) + 40 + len(_CLONE_TAIL)]
        if len(addr) == 40 and tail == _CLONE_TAIL:
            report["proxy_kind"] = "eip1167"
            report["implementation"] = _address(addr)
    return report


def _hex(bytecode: str) -> str:
    text = (bytecode or "").strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    return "".join(ch for ch in text if ch in "0123456789abcdef")


def evmole_available() -> bool:
    try:
        import evmole  # noqa: F401
    except Exception:  # noqa: BLE001 — optional dependency
        return False
    return True


def whatsabi_script() -> Path:
    return Path(__file__).resolve().parents[3] / "tools" / "whatsabi_surface.mjs"


def _call_evmole(bytecode: str) -> dict[str, Any]:
    import evmole

    code = bytecode if bytecode.startswith("0x") else "0x" + _hex(bytecode)
    info = None
    attempts = (
        {"selectors": True, "arguments": True, "state_mutability": True, "storage": True, "proxy": True},
        {"selectors": True, "arguments": True, "state_mutability": True, "storage": True},
        {"selectors": True, "arguments": True, "state_mutability": True},
    )
    for kwargs in attempts:
        try:
            info = evmole.contract_info(code, **kwargs)
            break
        except TypeError:
            continue
    if info is None:
        return {"functions": [], "storage": [], "proxy_kind": "", "implementation": ""}
    return normalize_tool(info, "evmole")


def _call_whatsabi(bytecode: str, timeout_s: int, runner: Optional[Callable[[str], str]]) -> dict[str, Any]:
    if runner is not None:
        raw = runner(bytecode)
    else:
        script = whatsabi_script()
        node = shutil.which("node")
        if not node or not script.is_file():
            return {"functions": [], "storage": [], "proxy_kind": "", "implementation": "", "skipped": True}
        code = bytecode if str(bytecode).startswith("0x") else "0x" + _hex(bytecode)
        try:
            proc = subprocess.run(
                [node, str(script), code],
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return {"functions": [], "storage": [], "proxy_kind": "", "implementation": "", "skipped": True}
        raw = proc.stdout or ""
    try:
        payload = json.loads(raw or "")
    except json.JSONDecodeError:
        return {"functions": [], "storage": [], "proxy_kind": "", "implementation": "", "skipped": True}
    if not isinstance(payload, dict) or payload.get("available") is False:
        return {"functions": [], "storage": [], "proxy_kind": "", "implementation": "", "skipped": True}
    parsed = normalize_tool(payload, "whatsabi")
    parsed["skipped"] = False
    return parsed


def recover_surface(
    bytecode: str,
    *,
    evmole_report: Any = None,
    whatsabi_report: Any = None,
    use_evmole: bool = True,
    use_whatsabi: bool = True,
    whatsabi_runner: Optional[Callable[[str], str]] = None,
    timeout_s: int = 15,
) -> dict[str, Any]:
    """Union evmole, whatsabi, and the prefix check. Never raises for a missing tool."""
    notes: list[str] = []
    parts: list[dict[str, Any]] = []
    evmole_ran = False
    whatsabi_ran = False
    if evmole_report is not None:
        parts.append(normalize_tool(evmole_report, "evmole"))
        evmole_ran = True
    elif use_evmole and _hex(bytecode) and evmole_available():
        try:
            parts.append(_call_evmole(bytecode))
            evmole_ran = True
        except Exception as exc:  # noqa: BLE001
            notes.append("evmole failed (%s)" % type(exc).__name__)
    elif use_evmole:
        notes.append("evmole is not installed")
    if whatsabi_report is not None:
        parts.append(normalize_tool(whatsabi_report, "whatsabi"))
        whatsabi_ran = True
    elif use_whatsabi and _hex(bytecode):
        parsed = _call_whatsabi(bytecode, max(3, min(30, int(timeout_s))), whatsabi_runner)
        if parsed.get("skipped"):
            notes.append("whatsabi is not installed")
        else:
            parts.append(parsed)
            whatsabi_ran = True
    prefix = prefix_report(bytecode)
    if prefix.get("proxy_kind"):
        parts.append(prefix)
    merged = union_reports(*parts)
    merged.update({
        "tools": {"evmole": evmole_ran, "whatsabi": whatsabi_ran, "prefix": bool(prefix.get("proxy_kind"))},
        "pins": PINS,
        "note": "; ".join(notes),
        "heat_contribution": 0,
    })
    scored = score_surface(merged)
    merged["surface_evidence"] = scored["points"]
    merged["show"] = scored["show"]
    merged["surface_overlap"] = scored["overlap"]
    merged["heat_contribution"] = scored["points"]
    return merged


def _value_mutator(surface: dict[str, Any]) -> bool:
    for row in surface.get("functions") or []:
        if row.get("selector") in _VALUE and row.get("mutability") in {"nonpayable", "payable"}:
            return True
    return False


def score_surface(surface: Optional[dict[str, Any]]) -> dict[str, Any]:
    """EIP-7702 delegation is 2. A clone that can move value is 2.

    An EIP-1967 resolution is recorded and shown. It does not add points,
    because an unverified upgradeable proxy is already `proxy_evidence`.
    """
    data = surface or {}
    kind = str(data.get("proxy_kind") or "")
    impl = str(data.get("implementation") or "")
    points = 0
    overlap = ""
    if kind == "eip7702" and impl:
        points = 2
    elif kind == "eip1167" and impl and _value_mutator(data):
        points = 2
    elif kind in {"eip1967", "eip1822", "beacon"} and impl:
        overlap = "proxy"
    points = min(SURFACE_CAP, points)
    selectors = [row for row in (data.get("functions") or []) if row.get("selector")]
    show = points > 0 or bool(impl) or any(
        row.get("mutability") in {"nonpayable", "payable"} for row in selectors
    )
    return {"points": points, "show": show, "overlap": overlap, "selectors": len(selectors)}


def actions_for_surface(surface: Optional[dict[str, Any]]) -> Optional[set[str]]:
    """Actions the invariant catalog may run. None means the catalog is unchanged.

    Donate stays, because it is an inbound transfer rather than a target call.
    A sequence whose action was not recovered is skipped, not failed.
    """
    if not surface or not (surface.get("functions") or []):
        return None
    found = {_selector(row.get("selector")) for row in surface["functions"]}
    allowed = {"donate"}
    for name, selectors in _ACTIONS.items():
        if found & selectors:
            allowed.add(name)
    return allowed


def interface_source(surface: dict[str, Any]) -> str:
    """A Solidity interface of recovered signatures. No function bodies."""
    lines = [
        "// SPDX-License-Identifier: MIT",
        "pragma solidity ^0.8.20;",
        "",
        "/// Selectors recovered from bytecode. The body is not reconstructed.",
        "interface RecoveredSurface {",
    ]
    emitted = 0
    for row in surface.get("functions") or []:
        name = str(row.get("name") or "")
        if not name:
            continue
        args = str(row.get("arguments") or "")
        mut = str(row.get("mutability") or "nonpayable")
        if mut not in _MUTABILITY:
            mut = "nonpayable"
        if mut == "pure":
            mut = "view"
        lines.append("    function %s(%s) external %s;" % (name, args, mut))
        emitted += 1
        if emitted >= _MAX_CALLS:
            break
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def harness_calls(surface: dict[str, Any]) -> list[str]:
    """Low-level calls of amount 1 for recovered value signatures.

    The strings are conservation checks. They are not a transaction and
    they are not a crafted sequence.
    """
    calls: list[str] = []
    for row in surface.get("functions") or []:
        if row.get("selector") not in _VALUE:
            continue
        if row.get("mutability") not in {"nonpayable", "payable"}:
            continue
        name = str(row.get("name") or "")
        args = str(row.get("arguments") or "")
        if not name:
            continue
        signature = "%s(%s)" % (name, args)
        literals = []
        for typ in [part for part in args.split(",") if part]:
            if typ == "address":
                literals.append("outsider")
            else:
                literals.append("%s(1)" % typ)
        if literals:
            encoded = 'abi.encodeWithSignature("%s", %s)' % (signature, ", ".join(literals))
        else:
            encoded = 'abi.encodeWithSignature("%s")' % signature
        calls.append(encoded)
        if len(calls) >= _MAX_CALLS:
            break
    return calls


def surface_test_source(surface: dict[str, Any]) -> str:
    """Extra Foundry function. Empty when there is nothing new to call."""
    calls = harness_calls(surface)
    if not calls:
        return ""
    body = "\n".join("        (bool ok%s, ) = TARGET.call(%s); ok%s;" % (i, call, i) for i, call in enumerate(calls))
    return """
    /// Recovered selectors. A balance increase is evidence. This does not broadcast.
    function test_recovered_surface_conservation() public {
        uint256 beforeBal = outsider.balance;
%s
        assert(outsider.balance <= beforeBal);
    }
""" % body


def write_surface_inputs(dest: Path, surface: dict[str, Any]) -> list[str]:
    """Write the union beside a local harness. The files are not broadcast."""
    root = Path(dest)
    root.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    corpus = root / "corpus" / "ityfuzz"
    corpus.mkdir(parents=True, exist_ok=True)
    selectors = [str(row.get("selector") or "") for row in surface.get("functions") or [] if row.get("selector")]
    ity = corpus / "selectors.txt"
    ity.write_text("\n".join(selectors) + ("\n" if selectors else ""), encoding="utf-8")
    written.append(str(ity))
    payload = {
        "functions": surface.get("functions") or [],
        "storage": surface.get("storage") or [],
        "proxy_kind": surface.get("proxy_kind") or "",
        "implementation": surface.get("implementation") or "",
        "tools": surface.get("tools") or {},
        "heat_contribution": int(surface.get("surface_evidence") or 0),
        "note": "local harness input; not a transaction",
    }
    path = root / "corpus" / "surface.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    written.append(str(path))
    sol = root / "src" / "RecoveredSelectors.sol"
    sol.parent.mkdir(parents=True, exist_ok=True)
    sol.write_text(interface_source(surface), encoding="utf-8")
    written.append(str(sol))
    return written
