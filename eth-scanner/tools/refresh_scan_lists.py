"""Rebuild List 1 and List 2 from current evidence. Read-only.

Ethereum dollars are the contract's own native and major-token balances,
read now. When that balance is under $100, a DefiLlama TVL is used only
when this address is the protocol's listed address. Other chains use
DefiLlama's current chain TVL. Code checks are read-only. Ethereum
scanning does not gain a public RPC fallback.
"""

from __future__ import annotations

import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from eth_scanner.benchmark.defihacklabs import README_URL, parse_index
from eth_scanner.chains.evm import EVM_CHAINS
from eth_scanner.protocol_graph.risk import KNOWN_INCIDENT_MARKERS
from eth_scanner.chains.evm_discover import _address_for, _chain_usd, _evm, _hex, _protocols
from eth_scanner.feed.list_refresh import LIST1_COUNT, LIST2_COUNT, choose_lists
from eth_scanner.ingest.funds import probe_funds_batch
from eth_scanner.feed.lists import is_big_or_canonical_name
from eth_scanner.feed.master_list import HAND_RANKED_FILENAME, default_master_list_path, load_master_candidates

DATA = default_master_list_path().parent
ETH_CODE_RPC = "https://ethereum.publicnode.com"
HEAD_RANK = 200


def _http_json(url: str, payload: bytes | None = None) -> object:
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "beigefield-scanner"},
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _codes(url: str, addresses: list[str]) -> dict[str, bool]:
    if not addresses:
        return {}
    body = json.dumps([
        {"jsonrpc": "2.0", "id": i, "method": "eth_getCode", "params": [addr, "latest"]}
        for i, addr in enumerate(addresses)
    ]).encode()
    try:
        result = _http_json(url, body)
    except Exception:
        return {}
    found: dict[str, bool] = {}
    if not isinstance(result, list):
        return found
    for item in result:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        if index < 0 or index >= len(addresses):
            continue
        text = _hex(item.get("result"))
        found[addresses[index]] = bool(text) and text not in {"0x", "0x0"}
    return found


def _eth_index(protocols: list[dict]) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    by_slug: dict[str, float] = {}
    by_name: dict[str, float] = {}
    by_addr: dict[str, float] = {}
    for row in protocols:
        usd = _chain_usd(row, "Ethereum")
        if usd is None:
            continue
        slug = str(row.get("slug") or "").strip().lower()
        name = str(row.get("name") or "").strip().lower()
        if slug:
            by_slug[slug] = usd
        if name:
            by_name[name] = usd
        raw = str(row.get("address") or "")
        addr = _evm(raw.split(":", 1)[1] if ":" in raw else raw)
        if addr and (":" not in raw or raw.lower().startswith("ethereum:")):
            by_addr[addr] = usd
    return by_slug, by_name, by_addr


def _dollars(address: str, onchain: dict[str, float], by_addr: dict[str, float]) -> tuple[float, str] | None:
    held = onchain.get(address)
    if held is not None and held >= 100:
        return held, "onchain-balances"
    listed = by_addr.get(address)
    if listed is not None and listed >= 100:
        return listed, "defillama"
    return None


def _pool(protocols: list[dict], onchain: dict[str, float]) -> list[dict]:
    _by_slug, _by_name, by_addr = _eth_index(protocols)
    rows: list[dict] = []
    seen: set[str] = set()
    ordered = load_master_candidates()
    head = {row.address for row in ordered[:HEAD_RANK]}
    for row in ordered:
        seen.add(row.address)
        if row.address in head:
            continue
        measured = _dollars(row.address, onchain, by_addr)
        if measured is None:
            continue
        usd, source = measured
        blob = " ".join(part for part in (row.candidate_reason, row.category, row.contract_class, row.evidence_note) if part)
        rows.append({
            "address": row.address,
            "protocol": row.protocol,
            "slug": row.slug,
            "category": row.category or row.contract_class,
            "usd": usd,
            "chain": "ethereum",
            "verified": bool(row.verified_contract),
            "has_code": True if row.verified_contract else None,
            "reason": blob,
            "dollars_source": source,
            "not_recently_scanned": True,
            "big_name": is_big_or_canonical_name(row.protocol, row.slug),
            "prior": row,
        })
    list2 = DATA / "list2_candidates.json"
    if list2.is_file():
        for raw in json.loads(list2.read_text(encoding="utf-8")):
            address = str(raw.get("address") or "").lower()
            if address in seen:
                continue
            seen.add(address)
            protocol = str(raw.get("protocol") or "")
            slug = str(raw.get("slug") or protocol)
            measured = _dollars(address, onchain, by_addr)
            if measured is None:
                continue
            usd, source = measured
            rows.append({
                "address": address,
                "protocol": protocol,
                "slug": slug,
                "category": str(raw.get("contract_class") or ""),
                "usd": usd,
                "chain": "ethereum",
                "verified": False,
                "has_code": None,
                "reason": " ".join(str(raw.get(key) or "") for key in ("candidate_reason", "contract_class", "evidence_note")),
                "dollars_source": source,
                "not_recently_scanned": True,
                "big_name": is_big_or_canonical_name(protocol, slug),
            })
    manual = DATA / "lists" / "manual.json"
    if manual.is_file():
        doc = json.loads(manual.read_text(encoding="utf-8"))
        for key in ("list-1", "list-2"):
            for raw in doc.get(key) or []:
                if not isinstance(raw, dict):
                    continue
                address = str(raw.get("address") or "").lower()
                if not address or address in seen:
                    continue
                seen.add(address)
                measured = _dollars(address, onchain, by_addr)
                if measured is None:
                    continue
                usd, source = measured
                protocol = str(raw.get("tag") or "manual")
                rows.append({
                    "address": address,
                    "protocol": protocol,
                    "slug": protocol,
                    "category": str(raw.get("source") or ""),
                    "usd": usd,
                    "chain": "ethereum",
                    "verified": False,
                    "has_code": None,
                    "reason": " ".join(str(raw.get(name) or "") for name in ("tag", "source")),
                    "dollars_source": source,
                    "not_recently_scanned": True,
                    "big_name": False,
                })
    for chain in ("bsc", "arbitrum", "base"):
        llama = {"bsc": "Binance", "arbitrum": "Arbitrum", "base": "Base"}[chain]
        for row in protocols:
            address = _address_for(row, chain, llama)
            if not address or address in seen:
                continue
            usd = _chain_usd(row, llama)
            if usd is None:
                continue
            protocol = str(row.get("name") or "")
            slug = str(row.get("slug") or "")
            category = str(row.get("category") or "")
            rows.append({
                "address": address,
                "protocol": protocol,
                "slug": slug,
                "category": category,
                "usd": usd,
                "chain": chain,
                "verified": False,
                "has_code": None,
                "reason": category,
                "dollars_source": "defillama-%s" % chain,
                "not_recently_scanned": True,
                "big_name": is_big_or_canonical_name(protocol, slug),
            })
    return rows


def _incident_names() -> set[str]:
    try:
        req = urllib.request.Request(README_URL, headers={"User-Agent": "beigefield-scanner"})
        with urllib.request.urlopen(req, timeout=25) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return set()
    return {row["name"].lower() for row in parse_index(text) if len(row["name"]) >= 8}


def _mark_known_incidents(rows: list[dict], incidents: set[str]) -> int:
    """Drop names that match a public incident title. No writeup is kept."""
    marked = 0
    generic = {"unknown", "contract", "manual", "univ2-fork-unknown"}
    for row in rows:
        name = str(row.get("protocol") or "").lower().strip()
        if not name or name in generic:
            continue
        hit = any(re.search(r"\b%s\b" % re.escape(marker), name) for marker in KNOWN_INCIDENT_MARKERS)
        if not hit:
            hit = name in incidents or any(len(incident) >= 8 and incident in name for incident in incidents)
        if hit:
            row["reason"] = str(row.get("reason") or "") + " past-hack"
            marked += 1
    return marked


def _mark_code(rows: list[dict]) -> None:
    wanted = [row for row in rows if row.get("has_code") is None and float(row.get("usd") or 0) >= 100]
    by_chain: dict[str, list[str]] = {}
    for row in wanted:
        by_chain.setdefault(row["chain"], [])
        if row["address"] not in by_chain[row["chain"]]:
            by_chain[row["chain"]].append(row["address"])
    urls = {"ethereum": ETH_CODE_RPC}
    for chain, cfg in EVM_CHAINS.items():
        if cfg.public_rpcs:
            urls[chain] = cfg.public_rpcs[0]
    found: dict[tuple[str, str], bool] = {}
    jobs = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for chain, addresses in by_chain.items():
            url = urls.get(chain)
            if not url:
                continue
            for start in range(0, len(addresses), 25):
                chunk = addresses[start:start + 25]
                jobs.append((chain, chunk, pool.submit(_codes, url, chunk)))
        for chain, chunk, fut in jobs:
            try:
                result = fut.result()
            except Exception:
                result = {}
            for addr in chunk:
                if addr in result:
                    found[(chain, addr)] = result[addr]
    hits = misses = 0
    for row in rows:
        key = (row["chain"], row["address"])
        if key not in found:
            continue
        row["has_code"] = found[key]
        if found[key]:
            hits += 1
        else:
            misses += 1
    print("code_checks", {chain: len(addrs) for chain, addrs in by_chain.items()}, "with_code", hits, "empty", misses)


def _write(picked: dict) -> None:
    one = []
    for index, row in enumerate(picked["list-1"], start=1):
        prior = row.get("prior")
        one.append({
            "address": row["address"],
            "protocol": row["protocol"],
            "slug": row.get("slug") or "",
            "category": row.get("category") or "",
            "est_usd_held": row["usd"],
            "candidate_reason": row["candidate_reason"],
            "tier": int(getattr(prior, "tier", 3) or 3),
            "rank": index,
            "drain_probability": round(min(1.0, int(row["score"]) / 10.0), 4),
            "contract_class": row.get("category") or "contract",
            "evidence_note": row["candidate_reason"],
            "label": "",
            "source": "fresh-pick",
            "verified_contract": bool(row.get("verified") or row.get("has_code")),
            "defillama_eth_tvl": row["usd"] if row["chain"] == "ethereum" else None,
            "audits": getattr(prior, "audits", "") if prior else "",
            "forked_from": getattr(prior, "forked_from", None) if prior else None,
            "proxy_implementation": getattr(prior, "proxy_implementation", None) if prior else None,
            "proxy_admin": getattr(prior, "proxy_admin", None) if prior else None,
        })
    two = []
    for row in picked["list-2"]:
        two.append({
            "address": row["address"],
            "protocol": row["protocol"],
            "contract_class": row.get("category") or "",
            "funds_usd": row["usd"],
            "drain_probability": round(min(1.0, int(row["score"]) / 10.0), 4),
            "candidate_reason": row["candidate_reason"],
            "evidence_note": row["candidate_reason"],
            "source": "fresh-pick",
            "already_on_master": False,
        })
    (DATA / "master_candidates.json").write_text(json.dumps(one, indent=2), encoding="utf-8")
    (DATA / "list2_candidates.json").write_text(json.dumps(two, indent=2), encoding="utf-8")
    (DATA / "lists" / "manual.json").write_text(json.dumps({"list-1": [], "list-2": []}, indent=2), encoding="utf-8")
    (DATA / HAND_RANKED_FILENAME).write_text("[]\n", encoding="utf-8")


def main() -> None:
    protocols = _protocols(None)
    ordered = load_master_candidates()
    addresses = [row.address for row in ordered]
    list2 = DATA / "list2_candidates.json"
    if list2.is_file():
        for raw in json.loads(list2.read_text(encoding="utf-8")):
            addresses.append(str(raw.get("address") or "").lower())
    manual = DATA / "lists" / "manual.json"
    if manual.is_file():
        doc = json.loads(manual.read_text(encoding="utf-8"))
        for key in ("list-1", "list-2"):
            for raw in doc.get(key) or []:
                if isinstance(raw, dict):
                    addresses.append(str(raw.get("address") or "").lower())
    snaps = probe_funds_batch([addr for addr in addresses if addr.startswith("0x")])
    onchain = {
        addr: float(snap.total_usd)
        for addr, snap in snaps.items()
        if snap.status == "ok" and snap.total_usd is not None
    }
    print("probed", len(snaps), "priced", len(onchain), "over100", sum(1 for value in onchain.values() if value >= 100))
    rows = _pool(protocols, onchain)
    incidents = _incident_names()
    print("incidents", len(incidents), "marked", _mark_known_incidents(rows, incidents))
    _mark_code(rows)
    print("pool", len(rows), "stored", sum(1 for row in rows if row["dollars_source"] == "stored-funds"))
    picked = choose_lists(rows, list1_count=LIST1_COUNT, list2_count=LIST2_COUNT)
    print("eligible", picked["eligible"], "list1", len(picked["list-1"]), "list2", len(picked["list-2"]))
    print("short", picked["list1_short"], picked["list2_short"])
    chains = {}
    for key in ("list-1", "list-2"):
        for row in picked[key]:
            chains[row["chain"]] = chains.get(row["chain"], 0) + 1
    print("chains", chains)
    _write(picked)


if __name__ == "__main__":
    main()
