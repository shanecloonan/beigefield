"""Nearest-neighbor retrieval over function statement graphs.

Identifiers are renamed, so a clone with different names still matches.
A second graph ignores statement order and links statements that share a
name, so a reordered body can still match. The score is a lead. It does
not add heat and it does not decide whether a detector runs.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Optional

from eth_scanner.heuristics.invariant_pass import functions, strip_comments

_TOKEN = re.compile(
    r"0x[0-9a-fA-F]+|\d+|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|"
    r"[A-Za-z_][A-Za-z0-9_]*|==|!=|<=|>=|&&|\|\||[^\s]"
)
_KEEP = frozenset({
    "if", "else", "for", "while", "do", "return", "require", "assert",
    "revert", "true", "false", "external", "public", "internal", "private",
    "view", "pure", "payable", "memory", "storage", "calldata", "uint",
    "uint256", "address", "bool", "bytes", "string", "int", "mapping",
    "new", "delete", "emit", "assembly",
    "transfer", "transferFrom", "safeTransfer", "safeTransferFrom",
    "call", "delegatecall", "staticcall", "send",
    "approve", "mint", "burn", "latestAnswer", "latestRoundData",
})
_SHAPES = (
    (
        "shape:external-transfer-from",
        "function pull(address token, address account, uint256 amount) external {\n"
        "    IERC20(token).transferFrom(account, address(this), amount);\n"
        "}",
    ),
    (
        "shape:price-then-move",
        "function settle(address feed, address token, address account, uint256 amount) external {\n"
        "    uint256 price = IFeed(feed).latestAnswer();\n"
        "    uint256 out = amount * price;\n"
        "    IERC20(token).transfer(account, out);\n"
        "}",
    ),
    (
        "shape:variable-delegatecall",
        "function forward(address target, bytes data) external {\n"
        "    (bool ok,) = target.delegatecall(data);\n"
        "    require(ok);\n"
        "}",
    ),
)
_THRESHOLD = 0.72


def _stable(text: str) -> int:
    value = 2166136261
    for ch in text:
        value ^= ord(ch)
        value = (value * 16777619) & 0xFFFFFFFF
    return value


def _tokens(body: str) -> list[str]:
    out: list[str] = []
    for raw in _TOKEN.findall(strip_comments(body or "", "solidity")):
        if raw.startswith(("'", '"')):
            out.append("STR")
        elif raw.startswith("0x"):
            out.append("HEX")
        elif raw.isdigit():
            out.append("NUM")
        else:
            out.append(raw)
    return out


def _alpha(toks: list[str]) -> list[str]:
    names: dict[str, str] = {}
    out: list[str] = []
    for tok in toks:
        if tok[:1].isalpha() and tok not in _KEEP:
            name = names.get(tok)
            if name is None:
                name = "v%d" % len(names)
                names[tok] = name
            out.append(name)
        else:
            out.append(tok)
    return out


def _statements(toks: list[str]) -> list[list[str]]:
    cur: list[str] = []
    out: list[list[str]] = []
    for tok in toks:
        if tok in {";", "{", "}"}:
            if cur:
                out.append(cur)
                cur = []
        else:
            cur.append(tok)
    if cur:
        out.append(cur)
    return [row for row in out if any(tok[:1].isalpha() or tok in _KEEP for tok in row)]


def _label(stmt: list[str]) -> tuple[str, ...]:
    kept = tuple(tok for tok in stmt if tok in _KEEP)
    return kept or ("stmt",)


def _ngrams(toks: list[str], n: int = 3) -> set[tuple[str, ...]]:
    if len(toks) < n:
        return {tuple(toks)} if toks else set()
    return {tuple(toks[i:i + n]) for i in range(len(toks) - n + 1)}


def _blocks(toks: list[str], window: int = 5) -> set[tuple[str, ...]]:
    if len(toks) < window:
        return {tuple(toks)} if toks else set()
    out: set[tuple[str, ...]] = set()
    rolling = 0
    for i, tok in enumerate(toks):
        rolling = ((rolling * 33) + _stable(tok)) & 0xFFFFFFFF
        if i >= window - 1 and rolling % 8 == 7:
            out.add(tuple(toks[i - window + 1:i + 1]))
    return out or {tuple(toks[:window])}


def _edges(stmts: list[list[str]]) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    seq = [(i, i + 1) for i in range(len(stmts) - 1)]
    names = []
    for stmt in stmts:
        names.append({tok for tok in stmt if tok[:1] == "v"})
    share = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            if names[i] & names[j]:
                share.append((i, j))
    return seq, share


def _wl(labels: list[tuple[str, ...]], edges: list[tuple[int, int]]) -> Counter[str]:
    color: dict[int, Any] = {i: labels[i] for i in range(len(labels))}
    nbrs: dict[int, list[int]] = {i: [] for i in color}
    for left, right in edges:
        nbrs[left].append(right)
        nbrs[right].append(left)
    for _ in range(2):
        color = {
            i: (color[i], tuple(sorted(color[j] for j in nbrs[i])))
            for i in color
        }
    return Counter(repr(color[i]) for i in color)


def _jaccard(left: set[Any], right: set[Any]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _cosine(left: Counter[str], right: Counter[str]) -> float:
    keys = set(left) | set(right)
    if not keys:
        return 1.0
    dot = sum(left[k] * right[k] for k in keys)
    left_n = sum(v * v for v in left.values()) ** 0.5
    right_n = sum(v * v for v in right.values()) ** 0.5
    if left_n == 0 or right_n == 0:
        return 0.0
    return dot / (left_n * right_n)


def _fingerprint(name: str, body: str, entry_id: str) -> Optional[dict[str, Any]]:
    alpha = _alpha(_tokens(body))
    stmts = _statements(alpha)
    if len(alpha) < 6 or not stmts:
        return None
    labels = [_label(stmt) for stmt in stmts]
    seq, share = _edges(stmts)
    return {
        "id": entry_id,
        "function": name or "",
        "ngrams": _ngrams(alpha),
        "blocks": _blocks(alpha),
        "labels": set(labels),
        "wl_seq": _wl(labels, seq),
        "wl_share": _wl(labels, share),
    }


def _pair(left: dict[str, Any], right: dict[str, Any]) -> float:
    ordered = (
        0.5 * _jaccard(left["ngrams"], right["ngrams"])
        + 0.3 * _cosine(left["wl_seq"], right["wl_seq"])
        + 0.2 * _jaccard(left["blocks"], right["blocks"])
    )
    shared = (
        0.45 * _jaccard(left["labels"], right["labels"])
        + 0.55 * _cosine(left["wl_share"], right["wl_share"])
    )
    return round(max(ordered, shared), 4)


def _functions_of(source: str) -> list[dict[str, Any]]:
    clean = strip_comments(source or "", "solidity")
    return functions(source or "", clean, "solidity")


def index_sources(entries: list[dict[str, Any]], *, builtin: bool = True) -> dict[str, Any]:
    """Index function bodies. `entries` are `{id, source}` from confirmed findings or saved texts."""
    rows: list[dict[str, Any]] = []
    incoming = list(entries or [])
    if builtin:
        incoming = [{"id": item[0], "source": item[1]} for item in _SHAPES] + incoming
    seen: set[tuple[str, str]] = set()
    for entry in incoming:
        entry_id = str(entry.get("id") or entry.get("address") or "finding")
        text = str(entry.get("source") or entry.get("evidence") or "")
        for fn in _functions_of(text):
            fp = _fingerprint(str(fn.get("name") or ""), str(fn.get("body") or ""), entry_id)
            if fp is None:
                continue
            key = (fp["id"], fp["function"])
            if key in seen:
                continue
            seen.add(key)
            rows.append(fp)
    return {"functions": rows, "heat_contribution": 0}


def search(source: str, index: Optional[dict[str, Any]] = None, *, limit: int = 5) -> dict[str, Any]:
    """Return nearest indexed functions. The score ranks a lead and adds no heat."""
    catalog = index if index is not None else index_sources([])
    hits: list[dict[str, Any]] = []
    for fn in _functions_of(source or ""):
        query = _fingerprint(str(fn.get("name") or ""), str(fn.get("body") or ""), "query")
        if query is None:
            continue
        best: Optional[dict[str, Any]] = None
        for row in catalog.get("functions") or []:
            if row.get("id") == "query":
                continue
            score = _pair(query, row)
            if best is None or score > float(best["score"]):
                best = {
                    "function": query["function"],
                    "neighbor": row.get("id") or "",
                    "neighbor_function": row.get("function") or "",
                    "score": score,
                    "heat_contribution": 0,
                }
        if best is not None and float(best["score"]) >= _THRESHOLD:
            hits.append(best)
    hits.sort(key=lambda row: (-float(row["score"]), str(row["function"])))
    return {
        "status": "ok" if hits else "no-neighbor",
        "candidates": hits[: max(1, limit)],
        "heat_contribution": 0,
        "note": "A similarity score is a lead. Detectors still run on the whole contract, and the score adds no heat.",
    }
