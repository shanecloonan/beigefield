"""Recall against public incident metadata. No writeups and no attack code.

DeFiLlama's hack list names a protocol, a date, and a chain. The protocol
list names an address. Joining those two is the affected-contract set.
A row is pre-incident only when the account still has code, is not a
minimal proxy, and the EIP-1967 implementation slot is empty, so the
runtime is the code that was deployed. Verified source for that runtime
comes from Sourcify. Detector leads are the catch. They add no heat.

The protocol address is the address DefiLlama lists. It is not always
the contract that was exploited. Rows that are proxies, or that have no
verified source, stay out of the recall denominator.

Scored rows are reported in three buckets: an off-chain label (key,
phishing, DNS, rug), a listed address whose source is a token, and a
listed address whose source is a protocol contract. Off-chain labels
stay out of the recall denominator. ``legacy`` is the previous ratio
over every scored row, including those labels.
"""

from __future__ import annotations

import json
import re
import urllib.request
from typing import Any, Callable, Optional

from eth_scanner.research.detectors import run_custom_detectors

HACKS_URL = "https://api.llama.fi/hacks"
PROTOCOLS_URL = "https://api.llama.fi/protocols"
SOURCIFY = "https://sourcify.dev/server/v2/contract/{chain_id}/{address}?fields=stdJsonInput"
IMPL_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
# This benchmark asks a public node whether code is still there. The
# scanner's Ethereum path still has no public RPC fallback.
ETH_CODE_RPC = "https://ethereum.publicnode.com"
CHAIN_ID = {"ethereum": 1, "bsc": 56, "arbitrum": 42161, "base": 8453}
_LLAMA_CHAIN = {
    "ethereum": "ethereum",
    "eth": "ethereum",
    "bsc": "bsc",
    "bnb": "bsc",
    "binance": "bsc",
    "arbitrum": "arbitrum",
    "base": "base",
    "solana": "solana",
}


def _evm(text: str) -> Optional[str]:
    raw = (text or "").strip().lower()
    if ":" in raw:
        raw = raw.split(":", 1)[1]
    if len(raw) == 42 and raw.startswith("0x"):
        try:
            int(raw[2:], 16)
        except ValueError:
            return None
        return raw
    return None


def _chain_name(value: Any) -> str:
    text = str(value or "").strip().lower()
    return _LLAMA_CHAIN.get(text, "")


# DefiLlama classes that are not a bug in the verified source.
_OFFCHAIN_CLASSIFICATION = frozenset({
    "key compromise",
    "frontend & infrastructure",
    "social engineering",
    "rugpull",
    "rug pull",
})
_OFFCHAIN_TECHNIQUE = re.compile(
    r"private key|phishing|dns hijack|validator key|hot wallet|"
    r"key leaked|seed phrase|social engineer|deployer key|backdoor",
    re.I,
)
# A pool, vault, or market names one of these. A governance token does not.
_PROTOCOL_SURFACE = re.compile(
    r"\bfunction\s+(?:"
    r"deposit|withdraw|redeem|borrow|liquidate|liquidationCall|"
    r"swap|buy|sell|skim|sync|harvest|stake|unstake|donate"
    r")\s*\(",
    re.I,
)
_TOKEN_TRANSFER = re.compile(r"\bfunction\s+transfer\s*\(", re.I)
_TOKEN_APPROVE = re.compile(r"\bfunction\s+(?:approve|transferFrom)\s*\(", re.I)
_BUCKETS = (
    ("off_chain", "off-chain label", False),
    ("token", "listed address is a token", True),
    ("protocol", "scored source is a protocol contract", True),
)


def is_offchain_label(classification: str = "", technique: str = "") -> bool:
    """True for a stolen key, phishing, DNS, or rug label. Not a source bug."""
    kind = (classification or "").strip().lower()
    if kind in _OFFCHAIN_CLASSIFICATION:
        return True
    return bool(_OFFCHAIN_TECHNIQUE.search(technique or ""))


def is_token_source(source: str) -> bool:
    """True when the bundle has an ERC-20 surface and no pool or vault function."""
    text = source or ""
    from eth_scanner.heuristics.invariant_pass import strip_comments
    text = strip_comments(text, "solidity")
    if _PROTOCOL_SURFACE.search(text):
        return False
    return bool(_TOKEN_TRANSFER.search(text) and _TOKEN_APPROVE.search(text))


def assign_bucket(row: dict[str, Any], source: str = "") -> str:
    """off_chain, token, or protocol. Off-chain wins even when the file is a token."""
    if is_offchain_label(str(row.get("classification") or ""), str(row.get("technique") or "")):
        return "off_chain"
    if is_token_source(source):
        return "token"
    return "protocol"


def _row_bucket(row: dict[str, Any]) -> str:
    bucket = str(row.get("bucket") or "")
    if bucket in {"off_chain", "token", "protocol"}:
        return bucket
    return assign_bucket(row, "")


def _ratio(group: list[dict[str, Any]]) -> dict[str, Any]:
    hot = sum(1 for row in group if row.get("hot"))
    scored = len(group)
    return {
        "scored": scored,
        "hot": hot,
        "recall": (hot / scored) if scored else None,
    }


def resolve_incidents(hacks: list[dict[str, Any]], protocols: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Join hack metadata to the protocol's listed address. Descriptions are dropped."""
    by_id: dict[str, dict[str, Any]] = {}
    for row in protocols:
        if isinstance(row, dict) and row.get("id") is not None:
            by_id[str(row.get("id"))] = row
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for hack in hacks:
        if not isinstance(hack, dict):
            continue
        protocol = by_id.get(str(hack.get("defillamaId") or ""))
        if protocol is None:
            continue
        chains = hack.get("chain") or []
        chain = _chain_name(chains[0] if isinstance(chains, list) and chains else "")
        address = _evm(str(protocol.get("address") or ""))
        if chain not in CHAIN_ID or not address:
            continue
        key = (chain, address, str(hack.get("date") or ""))
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "name": str(hack.get("name") or protocol.get("name") or "")[:80],
            "date": hack.get("date"),
            "chain": chain,
            "address": address,
            "classification": str(hack.get("classification") or "")[:80],
            "technique": str(hack.get("technique") or "")[:80],
            "source": "defillama-protocol-address",
            "pre_incident": False,
            "scored": False,
            "hot": False,
            "heat_contribution": 0,
        })
    return out


def score_source(address: str, source: str) -> bool:
    """True when a custom detector leads. The lead adds no heat."""
    if not (source or "").strip():
        return False
    findings = run_custom_detectors(address=address, source=source[:200_000])
    return bool(findings)


def recall_report(rows: list[dict[str, Any]], *, incidents: int = 0) -> dict[str, Any]:
    scored = [row for row in rows if row.get("pre_incident") and row.get("scored")]
    legacy = _ratio(scored)
    kept = [row for row in scored if _row_bucket(row) != "off_chain"]
    current = _ratio(kept)
    buckets: dict[str, Any] = {}
    for key, label, in_denominator in _BUCKETS:
        group = [row for row in scored if _row_bucket(row) == key]
        entry = _ratio(group)
        entry["label"] = label
        entry["in_denominator"] = in_denominator
        buckets[key] = entry
    return {
        "metadata_only": True,
        "heat_contribution": 0,
        "incidents": incidents,
        "resolved": len(rows),
        "pre_incident": sum(1 for row in rows if row.get("pre_incident")),
        "scored": current["scored"],
        "hot": current["hot"],
        "recall": current["recall"],
        "legacy": {
            "scored": legacy["scored"],
            "hot": legacy["hot"],
            "recall": legacy["recall"],
            "note": "Every scored immutable source, including off-chain labels.",
        },
        "buckets": buckets,
        "by_chain": _by_chain(rows),
        "note": (
            "Recall is detector leads on immutable verified runtimes, "
            "excluding off-chain labels (key, phishing, DNS, rug). "
            "Token and protocol buckets stay in the denominator. "
            "legacy is the previous all-rows ratio. "
            "Proxy and unverified rows are not in either denominator. Heat is 0."
        ),
    }


def _by_chain(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        chain = str(row.get("chain") or "")
        counts[chain] = counts.get(chain, 0) + 1
    return counts


def _http_json(url: str, payload: Optional[bytes] = None) -> Any:
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "beigefield-scanner"},
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _batch(url: str, calls: list[tuple[str, str]]) -> dict[str, str]:
    """calls are (address, method-tag). Returns address+tag -> hex result."""
    body = json.dumps([
        {"jsonrpc": "2.0", "id": i, "method": method, "params": params}
        for i, (method, params) in enumerate(calls)
    ]).encode()
    try:
        result = _http_json(url, body)
    except Exception:
        return {}
    if not isinstance(result, list):
        return {}
    found: dict[str, str] = {}
    for item in result:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        if 0 <= index < len(calls):
            found[str(index)] = str(item.get("result") or "")
    return found


def _has_code(text: str) -> bool:
    raw = (text or "").strip().lower()
    return raw not in {"", "0x", "0x0"}


def _is_proxy_slot(text: str) -> bool:
    raw = (text or "").strip().lower().removeprefix("0x")
    return bool(raw) and set(raw) != {"0"}


def _is_clone(code: str) -> bool:
    return "363d3d373d3d3d363d73" in (code or "").lower()


def mark_immutable(rows: list[dict[str, Any]], *, rpc_for: Callable[[str], str]) -> None:
    """Set pre_incident from a read-only code and implementation-slot check."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row["chain"] not in CHAIN_ID:
            continue
        grouped.setdefault(row["chain"], []).append(row)
    for chain, group in grouped.items():
        url = rpc_for(chain)
        if not url:
            continue
        for start in range(0, len(group), 20):
            chunk = group[start:start + 20]
            calls: list[tuple[str, list[Any]]] = []
            for row in chunk:
                calls.append(("eth_getCode", [row["address"], "latest"]))
                calls.append(("eth_getStorageAt", [row["address"], IMPL_SLOT, "latest"]))
            found = _batch(url, calls)
            for index, row in enumerate(chunk):
                code = found.get(str(index * 2), "")
                slot = found.get(str(index * 2 + 1), "")
                row["pre_incident"] = _has_code(code) and not _is_proxy_slot(slot) and not _is_clone(code)


def _source_from_sourcify(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    std = payload.get("stdJsonInput")
    if not isinstance(std, dict):
        return ""
    sources = std.get("sources")
    if not isinstance(sources, dict):
        return ""
    parts: list[str] = []
    for item in sources.values():
        if isinstance(item, dict) and isinstance(item.get("content"), str):
            parts.append(item["content"])
    return "\n".join(parts)


def mark_scored(rows: list[dict[str, Any]], *, fetch_source: Callable[[str, str], str]) -> None:
    from concurrent.futures import ThreadPoolExecutor

    pending = [row for row in rows if row.get("pre_incident") and row["chain"] in CHAIN_ID]

    def _one(row: dict[str, Any]) -> tuple[dict[str, Any], str]:
        try:
            return row, fetch_source(row["chain"], row["address"])
        except Exception:
            return row, ""

    if not pending:
        return
    with ThreadPoolExecutor(max_workers=6) as pool:
        fetched = list(pool.map(_one, pending))
    for row, source in fetched:
        if not source.strip():
            continue
        row["scored"] = True
        row["bucket"] = assign_bucket(row, source)
        row["hot"] = score_source(row["address"], source)


def _labeled_safe() -> dict[str, Any]:
    """Same detector on the curated safe rows. A lead here is a false positive."""
    try:
        from eth_scanner.benchmark.eval import load_labeled
        entries = list((load_labeled().get("entries") or []))
    except OSError:
        entries = []
    safe = [row for row in entries if isinstance(row, dict) and row.get("label") == "safe"]
    scored = 0
    hot = 0
    for row in safe:
        address = _evm(str(row.get("address") or ""))
        if not address:
            continue
        source = fetch_sourcify("ethereum", address)
        if not source.strip():
            continue
        scored += 1
        if score_source(address, source):
            hot += 1
    return {
        "entries": len(safe),
        "scored": scored,
        "false_positives": hot,
        "false_positive_rate": (hot / scored) if scored else None,
    }


def fetch_sourcify(chain: str, address: str) -> str:
    chain_id = CHAIN_ID.get(chain)
    if not chain_id:
        return ""
    url = SOURCIFY.format(chain_id=chain_id, address=address)
    try:
        return _source_from_sourcify(_http_json(url))
    except Exception:
        return ""


def live_report() -> dict[str, Any]:
    from eth_scanner.chains.evm import EVM_CHAINS

    hacks = _http_json(HACKS_URL)
    protocols = _http_json(PROTOCOLS_URL)
    if not isinstance(hacks, list):
        hacks = []
    if not isinstance(protocols, list):
        protocols = []
    rows = resolve_incidents([row for row in hacks if isinstance(row, dict)], [row for row in protocols if isinstance(row, dict)])

    def rpc_for(chain: str) -> str:
        if chain == "ethereum":
            return ETH_CODE_RPC
        cfg = EVM_CHAINS.get(chain)
        return cfg.public_rpcs[0] if cfg and cfg.public_rpcs else ""

    mark_immutable(rows, rpc_for=rpc_for)
    mark_scored(rows, fetch_source=fetch_sourcify)
    report = recall_report(rows, incidents=len(hacks))
    report["labeled_safe"] = _labeled_safe()
    scored_rows = [row for row in rows if row.get("scored")]
    scored_rows.sort(key=lambda row: (not row.get("hot"), row.get("chain") or "", row.get("name") or ""))
    report["examples"] = [
        {
            "name": row["name"],
            "chain": row["chain"],
            "address": row["address"],
            "hot": bool(row.get("hot")),
            "bucket": _row_bucket(row),
        }
        for row in scored_rows[:8]
    ]
    return report
