"""Recall leads for share-balance, spot-price, and reentrancy shapes.

These are shape leads for the incident benchmark. They do not add heat,
and they do not run on a source that has no pool, vault, or market function.
No path is constructed and no transaction is sent.
"""

from __future__ import annotations

import re

from eth_scanner.heuristics.invariant_pass import functions, strip_comments

_PROTOCOL = re.compile(
    r"\bfunction\s+(?:"
    r"deposit|withdraw|redeem|borrow|liquidate|liquidationCall|"
    r"swap|buy|sell|skim|sync|harvest|stake|unstake|donate"
    r")\s*\(",
    re.I,
)
_ENTRY = re.compile(
    r"^(?:deposit|withdraw|redeem|borrow|liquidate|swap|buy|sell|skim|harvest|donate|stake|unstake)$",
    re.I,
)
_SHARE_FN = re.compile(r"^(?:deposit|mint|stake|donate)$", re.I)
_BALANCE_HERE = re.compile(r"balanceOf\s*\(\s*address\s*\(\s*this\s*\)\s*\)")
_MINTS = re.compile(r"\b_mint\s*\(|\btotalSupply\b|\bshares\b")
_OFFSET = re.compile(
    r"decimalsOffset|_decimalsOffset|VIRTUAL_SHARES|virtualShares|VIRTUAL_ASSETS|\+\s*1e\d|\+\s*10\s*\*\*",
)
_TWAP = re.compile(r"\b(?:observe|consult|latestRoundData|updatedAt)\s*\(")
_SPOT = re.compile(r"\bgetReserves\s*\(")
_DIVISION = re.compile(r"/")
_VALUE = re.compile(r"\.transfer\s*\(|safeTransfer(?:From)?\s*\(|\.call\s*\{")
_EXTERNAL = re.compile(
    r"\.(?:call|delegatecall|staticcall)\b|\.send\s*\(|safeTransfer(?:From)?\s*\(|\.transfer\s*\(",
)
_WRITE = re.compile(
    r"\b(?:totalSupply|totalAssets|totalShares|totalDebt|totalBorrows|_balances|balances)\b"
    r"(?:\s*\[[^\];]{0,80}\])?\s*(?:\+=|-=|=(?!=))|"
    r"\b[A-Za-z_]\w*\s*\[[^\];]{0,80}\]\s*(?:\+=|-=|=(?!=))",
)
_CALL_NAME = re.compile(r"(?<!\.)\b([A-Za-z_]\w*)\s*\(")
_SKIP_CALLS = frozenset({
    "require", "assert", "revert", "if", "for", "while", "return", "emit",
    "super", "keccak256", "sha256", "ecrecover", "abi", "add", "sub", "mul", "div",
})
_PRICE_VIEW = re.compile(
    r"getReserves\s*\(|balanceOf\s*\(\s*address\s*\(\s*this\s*\)|slot0\s*\(|get_virtual_price\s*\(",
)


def benchmark_lead_names(source: str) -> list[str]:
    """Share-balance, spot-price, and reentrancy shapes. Names only. Heat stays 0."""
    text = source or ""
    clean = strip_comments(text, "solidity")
    if not _PROTOCOL.search(clean):
        return []
    parsed = functions(text, clean, "solidity")
    names: list[str] = []
    if _share_balance(parsed):
        names.append("share-balance")
    if _spot_price(clean, parsed):
        names.append("spot-price")
    if _reentrancy(parsed):
        names.append("reentrancy")
    return names


def has_benchmark_lead(source: str) -> bool:
    """True when a share, spot-price, or reentrancy shape is present. Heat stays 0."""
    return bool(benchmark_lead_names(source))


def _body_with_one_callee(fn: dict, by_name: dict[str, dict]) -> str:
    body = str(fn.get("body") or "")
    for name in _CALL_NAME.findall(body):
        if name in _SKIP_CALLS or name not in by_name or name == fn.get("name"):
            continue
        body += "\n" + str(by_name[name].get("body") or "")
        break
    return body


def _share_balance(parsed: list[dict]) -> bool:
    by_name = {str(fn.get("name") or ""): fn for fn in parsed}
    for fn in parsed:
        if not _SHARE_FN.match(str(fn.get("name") or "")):
            continue
        body = _body_with_one_callee(fn, by_name)
        if not _BALANCE_HERE.search(body) or not _MINTS.search(body):
            continue
        if _OFFSET.search(body):
            continue
        return True
    return False


def _spot_price(clean: str, parsed: list[dict]) -> bool:
    if _TWAP.search(clean):
        return False
    by_name = {str(fn.get("name") or ""): fn for fn in parsed}
    for fn in parsed:
        if not _ENTRY.match(str(fn.get("name") or "")):
            continue
        body = _body_with_one_callee(fn, by_name)
        if _SPOT.search(body) and _DIVISION.search(body) and _VALUE.search(body):
            return True
    return False


def _events(fn: dict, by_name: dict[str, dict], depth: int, stack: set[str]) -> list[str]:
    name = str(fn.get("name") or "")
    if depth > 1 or name in stack:
        return []
    stack.add(name)
    events: list[str] = []
    for stmt in str(fn.get("body") or "").split(";"):
        for callee in _CALL_NAME.findall(stmt):
            if callee in _SKIP_CALLS or callee not in by_name or callee == name:
                continue
            events.extend(_events(by_name[callee], by_name, depth + 1, stack))
            break
        if _EXTERNAL.search(stmt):
            events.append("call")
        if _WRITE.search(stmt):
            events.append("write")
    return events


def _call_before_write(parsed: list[dict]) -> bool:
    by_name = {str(fn.get("name") or ""): fn for fn in parsed}
    for fn in parsed:
        if not _ENTRY.match(str(fn.get("name") or "")):
            continue
        seen_call = False
        for event in _events(fn, by_name, 0, set()):
            if event == "call":
                seen_call = True
            elif event == "write" and seen_call:
                return True
    return False


def _price_view(parsed: list[dict]) -> bool:
    for fn in parsed:
        vis = str(fn.get("vis") or "")
        if "view" not in vis and "pure" not in vis:
            continue
        body = str(fn.get("body") or "")
        if _PRICE_VIEW.search(body) and re.search(r"\breturn\b", body):
            return True
    return False


def _reentrancy(parsed: list[dict]) -> bool:
    if _call_before_write(parsed):
        return True
    if not _price_view(parsed):
        return False
    by_name = {str(fn.get("name") or ""): fn for fn in parsed}
    for fn in parsed:
        if not _ENTRY.match(str(fn.get("name") or "")):
            continue
        if "call" in _events(fn, by_name, 0, set()):
            return True
    return False
