#!/usr/bin/env python3
"""Refine the master candidate list using cached RPC results.

Improvements:
- Skip addresses that only appear in token/underlying arrays (aTokens, etc.)
- Drop contracts whose major-token balances wildly exceed the protocol's ETH TVL
  (shared infrastructure / mis-attributed token contracts)
- Enrich below-floor contracts with Blockscout token lists + DefiLlama prices
- Optional Etherscan verified-source flag on the kept set
"""
from __future__ import annotations

import json
import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_master_candidates as b  # noqa: E402

TOKEN_KEYS = {
    "token", "tokens", "underlying", "underlyings", "asset", "assets",
    "reward", "rewards", "rewardtoken", "rewardtokens", "lptoken", "lptokens",
    "want", "outputtoken", "inputtoken", "governance", "ignored", "dummytoken",
    "dummytokens", "symbol", "rewardtokenaddress", "stakingtoken",
    "rewardtokenaddresses", "outputtokens", "inputtokens", "baseasset",
    "quoteasset", "gasmoken", "gastoken", "nativetoken", "ignoredtoken",
    "ignoredtokens", "blacklist", "whitelist_token", "coins", "coin",
    "underlyingtoken", "underlyingtokens", "collateraltoken", "borrowtoken",
    "receipt", "receipttoken", "receipttokens",
}
TOKEN_FILE_RE = re.compile(
    r"(registrytokens|tokenlist|tokenswithunderlying|tokens\.js|tokens\.json)$",
    re.I,
)
TVL_MULTIPLE = 4.0
SHARED_ABS_CAP = 15_000_000.0  # clearly outside the $9M protocol band if also > 1.5x TVL


def infer_label(text: str, pos: int) -> str:
    window = text[max(0, pos - 25000) : pos]
    matches = list(re.finditer(r"""([A-Za-z_][\w]*)\s*(?::|=)\s*\[""", window))
    for m in reversed(matches):
        depth = 1
        closed = False
        for ch in window[m.end() :]:
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    closed = True
                    break
        if not closed and depth >= 1:
            return m.group(1)
    m = re.search(
        r"""([A-Za-z_][\w]*)\s*(?::|=)\s*(?:['"]0x[a-fA-F0-9]{0,40})?$""",
        window[-240:],
    )
    return m.group(1) if m else ""


def extract_from_source_v2(src: str) -> list[tuple[str, str, str]]:
    text = b.strip_comments(src)
    n = len(text)
    regions: list[tuple[int, int, str]] = []
    for m in b.CHAIN_KEY_RE.finditer(text):
        chain = m.group("chain")
        cl = chain.lower()
        if cl in {"ethereum", "eth", "mainnet"}:
            zone = "ethereum"
        elif b.is_non_eth_chain(chain):
            zone = "other"
        else:
            continue
        j = m.end()
        while j < n and text[j] in " \t\r\n":
            j += 1
        if j < n and text[j] == "{":
            depth = 0
            k = j
            while k < n:
                ch = text[k]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        regions.append((j, k + 1, zone))
                        break
                k += 1
        else:
            k = j
            while k < n and text[k] not in ",\n}":
                k += 1
            regions.append((j, k, zone))

    def zone_for(pos: int) -> str:
        hit = None
        for a, c, z in regions:
            if a <= pos < c:
                if hit is None or (c - a) < (hit[1] - hit[0]):
                    hit = (a, c, z)
        return hit[2] if hit else "shared"

    found = []
    for m in b.ADDR_RE.finditer(text):
        addr = b.norm_addr(m.group(0))
        if addr in b.DENYLIST:
            continue
        label = infer_label(text, m.start())
        zone = zone_for(m.start())
        found.append((addr, label, zone))
    return found


def extract_protocol_addresses_v2(rec: dict) -> list[dict]:
    items = []
    seen: dict[str, dict] = {}

    def add(addr, label, source, zone="ethereum"):
        if not addr or addr in b.DENYLIST or len(addr) != 42:
            return
        rec_item = seen.get(addr)
        if rec_item is None:
            rec_item = {
                "address": addr,
                "label": label or "",
                "sources": [source],
                "zone": zone,
                "labels": [label] if label else [],
            }
            seen[addr] = rec_item
            items.append(rec_item)
        else:
            if source not in rec_item["sources"]:
                rec_item["sources"].append(source)
            if label and label not in rec_item["labels"]:
                rec_item["labels"].append(label)
            old = rec_item["label"] or ""
            if label:
                if not old:
                    rec_item["label"] = label
                elif b.OWNER_HINTS.search(label) and not b.OWNER_HINTS.search(old):
                    rec_item["label"] = label
            if zone == "ethereum":
                rec_item["zone"] = "ethereum"

    module_path = b.resolve_module_path(rec.get("module"), rec["slug"])
    if module_path:
        files = [module_path]
        seen_files = {module_path.resolve()}
        try:
            src0 = module_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            src0 = ""
        if src0:
            for p in b.local_requires(src0, module_path):
                if p.resolve() not in seen_files:
                    files.append(p)
                    seen_files.add(p.resolve())
        if module_path.parent != b.ADAPTERS and module_path.parent.is_dir():
            sibs = list(module_path.parent.glob("*.js")) + list(module_path.parent.glob("*.json"))
            for p in sibs[:20]:
                if p.resolve() not in seen_files and "helper" not in p.parts:
                    files.append(p)
                    seen_files.add(p.resolve())
        for fp in files:
            # skip obvious token-registry files
            if TOKEN_FILE_RE.search(fp.name):
                continue
            try:
                src = fp.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = (
                str(fp.relative_to(b.ADAPTERS))
                if b.ADAPTERS in fp.parents or fp.parent == b.ADAPTERS
                else fp.name
            )
            for addr, label, zone in extract_from_source_v2(src):
                if zone == "other":
                    continue
                add(addr, label, f"defillama-adapter:{rel}", zone)

    proto_addr = b.extract_eth_addr(rec.get("protocol_address"))
    if proto_addr:
        add(proto_addr, "protocol-token", "defillama-protocol-address", "ethereum")

    # Drop addresses that only ever appeared under token-like keys
    kept = []
    for it in items:
        labels = [x.lower() for x in (it.get("labels") or [it.get("label") or ""]) if x]
        sources = it.get("sources") or []
        only_proto = set(sources) == {"defillama-protocol-address"}
        has_owner = any(b.OWNER_HINTS.search(x) for x in labels) or any(
            k.lower() in {x.lower() for x in labels} for k in
            ("factory", "vault", "treasury", "owners", "holders", "escrow", "gateway", "pool", "pools")
        )
        only_token = bool(labels) and all(x.lower() in TOKEN_KEYS or x.lower().rstrip("s") in TOKEN_KEYS for x in labels) and not has_owner
        if only_proto or only_token:
            it["skip_as_token"] = True
        else:
            it["skip_as_token"] = False
        kept.append(it)
    return kept


def blockscout_tokenlist(addr: str) -> list[dict]:
    url = (
        "https://eth.blockscout.com/api?module=account&action=tokenlist&address="
        + addr
    )
    try:
        data = b.http_json(url, timeout=20, retries=2)
    except Exception:
        return []
    if not isinstance(data, dict) or data.get("status") not in ("1", 1, "OK") and data.get("message") not in ("OK",):
        # some responses still have result
        rows = data.get("result") if isinstance(data, dict) else None
        if not rows:
            return []
    rows = data.get("result") or []
    if isinstance(rows, str):
        return []
    out = []
    for r in rows:
        try:
            ca = b.norm_addr(r.get("contractAddress") or r.get("contractaddress") or "")
            dec = int(r.get("decimals") or 0)
            bal = int(r.get("balance") or 0)
        except Exception:
            continue
        if not ca or ca in b.DENYLIST or bal <= 0:
            continue
        # skip obvious spam (no decimals, empty symbol, weird names later)
        sym = r.get("symbol") or ""
        name = r.get("name") or ""
        if not sym or "http" in name.lower() or ".com" in name.lower() or ".xyz" in name.lower():
            continue
        out.append({"token": ca, "decimals": dec, "balance": bal, "symbol": sym, "name": name})
    return out


def llama_prices(keys: list[str]) -> dict[str, float]:
    prices = {}
    uniq = list(dict.fromkeys(keys))
    for chunk in b.chunked(uniq, 40):
        url = "https://coins.llama.fi/prices/current/" + ",".join(chunk)
        try:
            data = b.http_json(url, timeout=30, retries=3)
        except Exception as exc:
            b.log(f"price chunk failed: {exc}")
            continue
        coins = data.get("coins") or {}
        for k, v in coins.items():
            if v and v.get("price"):
                prices[k.lower()] = float(v["price"])
        time.sleep(0.05)
    return prices


def is_shared_or_misattributed(usd: float, proto_tvl: float) -> bool:
    tvl = max(float(proto_tvl or 0), 1.0)
    if usd > TVL_MULTIPLE * tvl and usd > 50_000:
        return True
    if usd > SHARED_ABS_CAP and usd > 1.5 * tvl:
        return True
    return False


def looks_token_only_v2(item: dict, usd: float) -> bool:
    if item.get("skip_as_token"):
        return True
    return b.looks_token_only(item, usd)


def etherscan_verified(addresses: list[str]) -> dict[str, bool]:
    """Return address -> is_verified. Never logs the API key."""
    out = {a: None for a in addresses}
    # Read fallback key from the owner's beigefield scanner config (already in repo).
    key = ""
    try:
        cfg = Path("/workspace/beigefield/eth-scanner/src/eth_scanner/config.py").read_text()
        m = re.search(r'TEST_ETHERSCAN_FALLBACK_KEY\s*=\s*"([A-Z0-9]+)"', cfg)
        if m:
            key = m.group(1)
    except Exception:
        key = ""
    if not key:
        b.log("no etherscan key available; skipping verified-source checks")
        return out
    cache_path = b.WORK / "etherscan_verified.json"
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text())
            for a, v in cached.items():
                if a in out and v is not None:
                    out[a] = v
        except Exception:
            pass
    remaining = [a for a in addresses if out.get(a) is None]
    b.log(f"etherscan getsourcecode for {len(remaining)} kept addresses ({len(addresses)-len(remaining)} cached)")
    url_base = "https://api.etherscan.io/v2/api"
    for i, addr in enumerate(remaining):
        q = (
            f"{url_base}?chainid=1&module=contract&action=getsourcecode"
            f"&address={addr}&apikey={key}"
        )
        try:
            data = b.http_json(q, timeout=20, retries=2)
            result = data.get("result")
            row = result[0] if isinstance(result, list) and result else {}
            src = (row.get("SourceCode") or "").strip()
            abi = row.get("ABI") or ""
            if src and "not verified" not in abi.lower():
                out[addr] = True
        except Exception as exc:
            if i < 3:
                b.log(f"etherscan check failed for one address: {type(exc).__name__}")
        time.sleep(0.35)
        if (i + 1) % 40 == 0:
            b.log(f"  etherscan {i+1}/{len(remaining)}")
            cache_path.write_text(json.dumps(out))
    cache_path.write_text(json.dumps(out))
    n_yes = sum(1 for v in out.values() if v is True)
    n_no = sum(1 for v in out.values() if v is False)
    b.log(f"etherscan verified: {n_yes} unverified: {n_no} unknown: {len(out)-n_yes-n_no}")
    return out


def main() -> None:
    b.WORK.mkdir(parents=True, exist_ok=True)
    b.ADAPTER_IDX = b._adapter_index()
    selected = json.loads((b.WORK / "selected_protocols.json").read_text())
    prices = json.loads((b.WORK / "summary.json").read_text()).get("prices") or b.fetch_prices()
    codes = {}
    # reconstruct codes from dropped+candidates? better from earlier unique list + rpc_balances keys
    balances_raw = json.loads((b.WORK / "rpc_balances.json").read_text())
    storage = json.loads((b.WORK / "rpc_storage.json").read_text())
    # codes: any address in balances is a contract; others we may need to re-query
    for a in balances_raw:
        codes[a] = "0x1"  # placeholder non-empty; we only need boolean
    # also load extracted old? we'll re-extract

    b.log("re-extracting addresses with token-array filter")
    rows = []
    unresolved_extract = []
    for rec in selected:
        addrs = extract_protocol_addresses_v2(rec)
        eth_addrs = [a for a in addrs if a["zone"] != "other"]
        if not eth_addrs or all(a.get("skip_as_token") for a in eth_addrs):
            if not any(a for a in eth_addrs if not a.get("skip_as_token")):
                unresolved_extract.append(
                    {
                        "slug": rec["slug"],
                        "name": rec["name"],
                        "reason": "no-ethereum-custody-address-in-adapter-or-metadata",
                        "module": rec.get("module"),
                        "defillama_eth_tvl": rec["defillama_eth_tvl"],
                    }
                )
        for a in eth_addrs:
            rows.append({**rec, **a})
    b.log(f"extracted rows={len(rows)} unique={len({r['address'] for r in rows})} no-addr={len(unresolved_extract)}")
    (b.WORK / "extracted_addresses_v2.json").write_text(json.dumps(rows, indent=2))

    unique = sorted({r["address"] for r in rows if not r.get("skip_as_token")})
    missing = [a for a in unique if a not in codes and a not in balances_raw]
    b.log(f"addresses needing new RPC: {len(missing)} (already have {len(balances_raw)} balance entries)")
    pool = b.RpcPool(b.RPCS)
    if missing:
        new_codes = b.rpc_get_code(pool, missing)
        codes.update(new_codes)
        contracts = [a for a, c in new_codes.items() if c and c not in ("0x", "0x0")]
        if contracts:
            storage.update(b.rpc_storage(pool, contracts))
            new_bal = b.rpc_balances(pool, contracts)
            for a, bal in new_bal.items():
                balances_raw[a] = {k: str(v) for k, v in bal.items()}
    # mark EOAs among unique that weren't in balances
    for a in unique:
        if a not in codes and a not in balances_raw:
            codes[a] = "0x"

    def bal_dict(addr: str) -> dict:
        raw = balances_raw.get(addr) or {}
        out = {}
        for k in b.TOKENS:
            try:
                out[k] = int(raw.get(k) or 0)
            except Exception:
                out[k] = 0
        return out

    def major_usd(addr: str) -> float:
        return b.usd_held(bal_dict(addr), prices)

    def is_contract(addr: str) -> bool:
        if addr in balances_raw:
            return True
        c = codes.get(addr) or "0x"
        return bool(c) and c not in ("0x", "0x0")

    # Blockscout enrich: owner-like or unlabeled contracts below floor, for protocols
    # that would otherwise be unresolved, plus any contract under $2k with an owner hint.
    proto_tvl = {s["slug"]: s["defillama_eth_tvl"] for s in selected}
    enrich_targets = []
    seen_e = set()
    # prefer higher TVL protocols first
    rows_sorted = sorted(rows, key=lambda r: -r["defillama_eth_tvl"])
    for item in rows_sorted:
        addr = item["address"]
        if item.get("skip_as_token") or addr in seen_e:
            continue
        if not is_contract(addr):
            continue
        usd = major_usd(addr)
        if usd >= b.MIN_USD:
            continue
        # skip obvious protocol tokens
        if looks_token_only_v2(item, usd):
            continue
        seen_e.add(addr)
        enrich_targets.append(addr)
        if len(enrich_targets) >= 700:
            break
    b.log(f"blockscout enrich targets: {len(enrich_targets)}")
    token_holdings: dict[str, list] = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(blockscout_tokenlist, a): a for a in enrich_targets}
        done = 0
        for fut in as_completed(futs):
            a = futs[fut]
            try:
                token_holdings[a] = fut.result()
            except Exception:
                token_holdings[a] = []
            done += 1
            if done % 50 == 0 or done == len(enrich_targets):
                b.log(f"  blockscout {done}/{len(enrich_targets)}")

    price_keys = []
    for holds in token_holdings.values():
        for h in holds:
            price_keys.append("ethereum:" + h["token"])
    b.log(f"pricing {len(set(price_keys))} extra tokens via llama coins")
    extra_prices = llama_prices(price_keys)

    def enriched_usd(addr: str) -> float:
        usd = major_usd(addr)
        seen_tokens = {meta["address"] for meta in b.TOKENS.values() if meta["address"]}
        # ETH already in major_usd
        extra = 0.0
        for h in token_holdings.get(addr) or []:
            if h["token"] in seen_tokens:
                continue  # already counted
            px = extra_prices.get(("ethereum:" + h["token"]).lower())
            if not px:
                continue
            dec = h["decimals"] if h["decimals"] is not None else 18
            try:
                units = h["balance"] / (10 ** dec)
            except Exception:
                continue
            extra += units * px
        return usd + extra

    # Build candidates
    candidates = []
    dropped = []
    proto_has_keep = set()
    for item in rows:
        addr = item["address"]
        contract = is_contract(addr)
        usd_major = major_usd(addr) if contract else 0.0
        usd = enriched_usd(addr) if (contract and addr in token_holdings) else usd_major
        token_only = looks_token_only_v2(item, usd)
        st = storage.get(addr) or {}
        reasons = list(item.get("reasons") or [])
        if st.get("impl") and "upgradeable-proxy" not in reasons:
            reasons.append("upgradeable-proxy")
        if st.get("admin") and "upgradeable-admin" not in reasons:
            reasons.append("upgradeable-admin")
        drop = None
        if not contract:
            drop = "eoa-or-empty-code"
        elif token_only:
            drop = "token-only-or-passthrough"
        elif is_shared_or_misattributed(usd, item["defillama_eth_tvl"]):
            drop = "shared-or-misattributed-exceeds-protocol-tvl"
        elif usd < b.MIN_USD:
            drop = "below-2000-usd-priced-tokens"
        rec = {
            "protocol": item["name"],
            "slug": item["slug"],
            "category": item["category"],
            "defillama_eth_tvl": round(item["defillama_eth_tvl"], 2),
            "audits": item["audits"],
            "address": addr,
            "label": item.get("label") or "",
            "verified_contract": bool(contract),
            "est_usd_held": round(usd, 2),
            "est_usd_major_tokens": round(usd_major, 2),
            "source": ";".join(item.get("sources") or []),
            "candidate_reason": ";".join(reasons),
            "tier": b.assign_tier(reasons),
            "in_original_draft": item.get("in_original_draft", False),
            "forked_from": item.get("forked_from"),
            "proxy_implementation": st.get("impl"),
            "proxy_admin": st.get("admin"),
        }
        if drop:
            rec["drop_reason"] = drop
            dropped.append(rec)
        else:
            candidates.append(rec)
            proto_has_keep.add(item["slug"])

    # Etherscan verified-source on unique kept addresses
    uniq_kept = sorted({c["address"] for c in candidates})
    verified_map = etherscan_verified(uniq_kept) if uniq_kept else {}
    for rec in candidates:
        ver = verified_map.get(rec["address"])
        rec["etherscan_verified"] = ver
        if ver is False:
            reasons = [r for r in rec["candidate_reason"].split(";") if r]
            if "unverified-source" not in reasons:
                reasons.append("unverified-source")
            rec["candidate_reason"] = ";".join(reasons)
            rec["tier"] = b.assign_tier(reasons)

    candidates.sort(
        key=lambda r: (r["tier"], -r["est_usd_held"], -r["defillama_eth_tvl"], r["slug"], r["address"])
    )
    for i, r in enumerate(candidates, 1):
        r["rank"] = i

    selected_slugs = {s["slug"]: s for s in selected}
    extract_map = {u["slug"]: u for u in unresolved_extract}
    unresolved = []
    for slug, rec in selected_slugs.items():
        if slug in proto_has_keep:
            continue
        dropped_for = [d for d in dropped if d["slug"] == slug]
        if slug in extract_map and not any(not d.get("drop_reason", "").startswith("token") for d in dropped_for) and not dropped_for:
            reason = extract_map[slug]["reason"]
        elif dropped_for:
            reasons = sorted({d["drop_reason"] for d in dropped_for})
            reason = "addresses-found-but-dropped:" + ",".join(reasons)
        else:
            reason = extract_map.get(slug, {}).get("reason") or "unresolved"
        unresolved.append(
            {
                "protocol": rec["name"],
                "slug": slug,
                "category": rec["category"],
                "defillama_eth_tvl": rec["defillama_eth_tvl"],
                "audits": rec["audits"],
                "in_original_draft": rec["in_original_draft"],
                "reasons": rec.get("reasons") or [],
                "unresolved_reason": reason,
                "dropped_address_count": len(dropped_for),
            }
        )
    unresolved.sort(key=lambda r: -r["defillama_eth_tvl"])

    # write
    compact = []
    for r in candidates:
        compact.append(
            {
                "protocol": r["protocol"],
                "slug": r["slug"],
                "category": r["category"],
                "defillama_eth_tvl": r["defillama_eth_tvl"],
                "audits": r["audits"],
                "address": r["address"],
                "label": r["label"],
                "verified_contract": r["verified_contract"],
                "est_usd_held": r["est_usd_held"],
                "source": r["source"],
                "rank": r["rank"],
                "candidate_reason": r["candidate_reason"],
                "tier": r["tier"],
                "in_original_draft": r["in_original_draft"],
                "forked_from": r["forked_from"],
                "proxy_implementation": r.get("proxy_implementation"),
                "proxy_admin": r.get("proxy_admin"),
                "etherscan_verified": r.get("etherscan_verified"),
            }
        )
    (b.ROOT / "master_candidates.json").write_text(json.dumps(compact, indent=2))
    import csv
    fields = [
        "rank", "tier", "protocol", "slug", "category", "defillama_eth_tvl",
        "audits", "address", "label", "verified_contract", "est_usd_held",
        "source", "candidate_reason", "in_original_draft", "forked_from",
        "proxy_implementation", "proxy_admin", "etherscan_verified",
    ]
    with open(b.ROOT / "master_candidates.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in compact:
            w.writerow({k: r.get(k) if r.get(k) is not None else "" for k in fields})
    (b.WORK / "dropped_v2.json").write_text(json.dumps(dropped, indent=2))
    (b.ROOT / "unresolved.json").write_text(json.dumps(unresolved, indent=2))
    bands = {"2k-100k": 0, "100k-1m": 0, "1m-9m": 0, "9m+": 0}
    for c in candidates:
        u = c["est_usd_held"]
        if u < 100_000:
            bands["2k-100k"] += 1
        elif u < 1_000_000:
            bands["100k-1m"] += 1
        elif u <= 9_000_000:
            bands["1m-9m"] += 1
        else:
            bands["9m+"] += 1
    summary = {
        "selected_protocols": len(selected),
        "original_draft": sum(1 for s in selected if s["in_original_draft"]),
        "extras": sum(1 for s in selected if not s["in_original_draft"]),
        "kept_addresses": len(candidates),
        "kept_protocols": len({c["slug"] for c in candidates}),
        "draft_protocols_kept": len({c["slug"] for c in candidates if c["in_original_draft"]}),
        "extra_protocols_kept": len({c["slug"] for c in candidates if not c["in_original_draft"]}),
        "unresolved_protocols": len(unresolved),
        "dropped_addresses": len(dropped),
        "usd_bands": bands,
        "tier_counts": {
            "1": sum(1 for c in candidates if c["tier"] == 1),
            "2": sum(1 for c in candidates if c["tier"] == 2),
            "3": sum(1 for c in candidates if c["tier"] == 3),
        },
        "etherscan_verified": sum(1 for c in candidates if c.get("etherscan_verified")),
        "etherscan_unverified": sum(1 for c in candidates if c.get("etherscan_verified") is False),
        "prices": prices,
    }
    (b.WORK / "summary_v2.json").write_text(json.dumps(summary, indent=2))
    b.log(f"SUMMARY {json.dumps(summary)}")
    b.log("top 25:")
    for c in candidates[:25]:
        b.log(
            f"  #{c['rank']:3d} t{c['tier']} ${c['est_usd_held']:10,.0f} tvl=${c['defillama_eth_tvl']:9,.0f} "
            f"{c['slug']:28s} {c['address']} {c['candidate_reason']}"
        )


if __name__ == "__main__":
    main()
