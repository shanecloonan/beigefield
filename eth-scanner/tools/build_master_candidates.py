#!/usr/bin/env python3
"""Build a curated, defensive ETH invariant-scanner master candidate list.

Read-only: extracts custodial contract addresses from public DefiLlama
adapters / metadata, then verifies code and balances via public RPC.
Never sends a transaction. Does not generate exploit or attack code.
"""
from __future__ import annotations

import csv
import json
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Iterable

# Committed feed: eth-scanner/data/master_candidates.{json,csv}.
# A full rebuild also needs draft.json, protocols.json, and DefiLlama adapters
# (see ADAPTERS / HACKS_PATH). This script only reads public metadata and RPC.
ROOT = Path(__file__).resolve().parents[1] / "data"
WORK = ROOT / "work"
ADAPTERS = Path("/tmp/llama/DefiLlama-Adapters/projects")
HACKS_PATH = Path("/tmp/llama/hacks.json")
NOW = time.time()
NEW_LISTING_DAYS = 180
def _list1_bounds() -> tuple[float, float]:
    """List 1 min/max live in data/lists.json. This builder does not keep its own floor."""
    payload = json.loads((ROOT / "lists.json").read_text(encoding="utf-8"))
    for row in payload.get("lists") or []:
        if row.get("id") == "list-1":
            return float(row["min_funds_usd"]), float(row["max_funds_usd"])
    raise RuntimeError("list-1 bounds missing from data/lists.json")


MIN_USD, MAX_PROTOCOL_TVL = _list1_bounds()


def _discovery_floor() -> float:
    """Random/discovery intake floor. Env wins. Default $100. List 1 min stays MIN_USD."""
    raw = os.environ.get("ETH_SCANNER_DISCOVERY_MIN_USD", "100")
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return 100.0
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

RPCS = [
    "https://ethereum-rpc.publicnode.com",
    "https://ethereum.publicnode.com",
    "https://eth.drpc.org",
    "https://1rpc.io/eth",
    "https://rpc.flashbots.net",
    "https://rpc.mevblocker.io",
    "https://eth.blockrazor.xyz",
    "https://eth-pokt.nodies.app",
    "https://eth-mainnet.public.blastapi.io",
    "https://mainnet.gateway.tenderly.co",
    "https://gateway.tenderly.co/public/mainnet",
    "https://virginia.rpc.blxrbdn.com",
    "https://0xrpc.io/eth",
]

# Tokens used for est_usd_held (user-specified + ETH).
TOKENS = {
    "ETH": {"address": None, "decimals": 18},
    "WETH": {"address": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2", "decimals": 18},
    "USDC": {"address": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", "decimals": 6},
    "USDT": {"address": "0xdac17f958d2ee523a2206206994597c13d831ec7", "decimals": 6},
    "DAI": {"address": "0x6b175474e89094c44da98b954eedeac495271d0f", "decimals": 18},
    "WBTC": {"address": "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599", "decimals": 8},
    "WSTETH": {"address": "0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0", "decimals": 18},
}

# Infrastructure / well-known token contracts — never treat as custody targets.
DENYLIST = {
    "0x0000000000000000000000000000000000000000",
    "0x000000000000000000000000000000000000dead",
    "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",  # WETH
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",  # USDC
    "0xdac17f958d2ee523a2206206994597c13d831ec7",  # USDT
    "0x6b175474e89094c44da98b954eedeac495271d0f",  # DAI
    "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599",  # WBTC
    "0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0",  # wstETH
    "0xae7ab96520de3a18e5e111b5eaab095312d7fe84",  # stETH
    "0xbe9895146f7af43049ca1c1ae358b0541ea49704",  # cbETH
    "0xae78736cd615f374d3085123a210448e74fc6393",  # rETH
    "0xcd5fe23c85820f7b72d0926fc9b05b43e359b7ee",  # weETH
    "0x4c9edd5852cd905f086c759e8383e09bff1e68b3",  # USDe
    "0x9d39a5de30e57443bff2a8307a4256c8797a3497",  # sUSDe
    "0x83f20f44975d03b1b09e64809b757c47f943beea",  # sDAI
    "0xdC035D45d973E3EC169d2276DDab16f1e407384F".lower(),  # USDS
    "0x853d955acef822db058eb8505911ed77f175b99e",  # FRAX
    "0xf939e0a03fb07f59a73314e7376c54d564830140",  # crvUSD
    "0x5f98805a4e8be255a32880fdec7f6728c91aff21",  # LUSD
    "0x4c9ed19c6c5dd9182c2d3894e33914602a41412d",  # USD0 sometimes
    "0xa0b73e1ff0b80914ab6fe0444e65848c4c34450b",  # CRO
    "0xca11bde05977b3631167028862be2a173976ca11",  # Multicall3
    "0x5c69bee701ef814a2b6a3edd4b1652cb9cc5aa6f",  # UniV2 factory
    "0x1f98431c8ad98523631ae4a59f267346ea31f984",  # UniV3 factory
    "0x7a250d5630b4cf539739df2c5dacb4c659f2488d",  # UniV2 router
    "0xe592427a0aece92de3edee1f18e0157c05861564",  # UniV3 router
    "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45",  # SwapRouter02
    "0x000000000004444c5dc75cb358380d2ef3aaa370",  # UniV4 pool manager (pass-through-ish)
    "0xba12222222228d8ba445958a75a0704d566bf2c8",  # Balancer vault — actually DOES custody; keep? User wants custody. REMOVE from denylist.
}

# Balancer vault actually holds funds — do not denylist it.
DENYLIST.discard("0xba12222222228d8ba445958a75a0704d566bf2c8")
# Uni V2/V3 factories and routers typically do not custody user funds.
# UniV4 pool manager does custody — remove from denylist if we added it.
DENYLIST.discard("0x000000000004444c5dc75cb358380d2ef3aaa370")

NON_ETH_CHAINS = {
    "bsc", "binance", "polygon", "matic", "arbitrum", "optimism", "base", "avalanche",
    "avax", "fantom", "ftm", "gnosis", "xdai", "linea", "scroll", "zksync", "era",
    "polygon_zkevm", "polygonzkevm", "sonic", "mantle", "blast", "mode", "manta",
    "celo", "moonbeam", "moonriver", "harmony", "cronos", "kava", "metis", "aurora",
    "boba", "heco", "okexchain", "okxchain", "klaytn", "kaia", "oasis", "telos",
    "evmos", "canto", "fuse", "syscoin", "milkomeda", "dogechain", "smartbch",
    "arbitrum_nova", "arbitrumnova", "zora", "fraxtal", "bob", "worldchain",
    "unichain", "ink", "berachain", "hyperliquid", "hyperliquid_l1", "hyperevm",
    "tron", "solana", "near", "aptos", "sui", "bitcoin", "litecoin", "ripple",
    "stellar", "cosmos", "osmosis", "injective", "thorchain", "cardano", "polkadot",
    "kusama", "algorand", "tezos", "eos", "waves", "ton", "toncoin", "starknet",
    "fuel", "mezo", "sei", "soneium", "swellchain", "taiko", "scroll_alpha",
    "opbnb", "xlayer", "xdai", "rootstock", "rsk", "btr", "bitlayer", "merlin",
    "core", "coredao", "zeta", "zetachain", "kcc", "okc", "iotex", "wan", "wanchain",
    "hymy", "filecoin", "flare", "songbird", "acala", "karura", "manta_atlantic",
    "lisk", "abstract", "apechain", "corn", "hemi", "plume", "sophon", "katana",
    "plasma", "etherlink", "gravity", "superseed", "shape", "ronin", "chiliz",
    "flow", "immutablezkevm", "immutable_zkevm", "polygon_cdk", "xdc", "wan",
    "heco", "elastos", "thundercore", "meter", "sxnetwork", "velas", "godwoken",
    "conflux", "ultron", "callisto", "energi", "shiden", "astar", "shibarium",
    "pulse", "pulsechain", "ethpow", "ethw", "classic", "etc", "goerli", "sepolia",
    "holesky", "hoodi", "devnet", "testnet", "wemix", "kroma", "pgn", "redstone",
    "zklink", "cyber", "degen", "ham", "rari", "mint", "race", "viction", "tomochain",
    "joc", "japanopenchain", "lightlink", "reya", "endurance", "educhain",
    "neon_evm", "neon", "oasis_sapphire", "sapphire", "oasis_emerald",
    "bittorrent", "bittorrent_chain", "doge", "litecoin", "bch", "bsv",
    "sanko", "beam", "immutablex", "immutable", "loopring", "dydx", "aevo",
    "blast_sepolia", "basecamp", "camp", "megaeth", "monad", "somnia",
    "story", "storyprotocol", "ape", "matchain", "swell", "bobanetwork",
    "cronos_zkevm", "cronoszkevm", "sei_evm", "seievm", "aurora_mainnet",
}

SKIP_EXTRA_CATS = {
    "CEX", "Chain", "NFT Marketplace", "Luck Games", "Gaming",
    "Charity Fundraising", "Bug Bounty", "SoFi", "AI Agents",
    "Governance Incentives", "DCA Tools", "DEX Aggregator",
    "Prediction Market", "CeDeFi",
}

COMPLEX_CATS = {
    "Restaking": "complex:restaking",
    "Liquid Restaking": "complex:restaking",
    "Bridge": "complex:bridge",
    "Cross Chain Bridge": "complex:bridge",
    "Canonical Bridge": "complex:bridge",
    "Leveraged Farming": "complex:leveraged-farming",
    "Algo-Stables": "complex:algo-stable",
    "Partially Algorithmic Stablecoin": "complex:algo-stable",
    "Reserve Currency": "complex:rebasing",
    "Options": "complex:options-perps",
    "Options Vault": "complex:options-perps",
    "Derivatives": "complex:options-perps",
    "Synthetics": "complex:options-perps",
    "Interest Rate Derivatives": "complex:options-perps",
    "Basis Trading": "complex:options-perps",
    "Uncollateralized Lending": "complex:uncollateralized-lending",
    "Risk Curators": "complex:allocator",
    "Onchain Capital Allocator": "complex:allocator",
    "Liquidity Manager": "complex:allocator",
    "Liquidity Automation": "complex:allocator",
    "Decentralized BTC": "complex:decentralized-btc",
    "Anchor BTC": "complex:decentralized-btc",
    "Privacy": "complex:privacy",
}

OWNER_HINTS = re.compile(
    r"(owner|owners|holder|holders|vault|vaults|pool|pools|market|markets|"
    r"treasury|treasuries|escrow|bridge|gateway|staking|staker|farm|farms|"
    r"gauge|gauges|cdp|manager|managers|strategy|strategies|lending|"
    r"collateral|custod|locker|lockers|reserve|reserves|bank|banks|"
    r"controller|vessel|trove|stability|booster|proxy|poolmanager|"
    r"pool_manager|wethgateway|lendingpool|comet|unitroller|comptroller|"
    r"pot|jug|end|vow|clip|dog|spotter|adapter|pocket|silo|harbor|"
    r"cove|buffer|cashier|safe|multisig|timelock|deposit|deposits|"
    r"withdraw|splitter|allocator|curator|fund|module|hook|pair|pairs|"
    r"paircode|amm|yieldvault|savings|silo|positionmanager|account|"
    r"diamond|cutfacet|premium|cover|nexus|capital|poolid|morpho|"
    r"bundler|permissioned|mellow|symbiotic|eigen|restake|exchange|"
    r"clearing|margin|engine|perp|option|spread|ibtoken|ctoken|atoken|"
    r"debt|borrow|supply|collateral)",
    re.I,
)
TOKEN_HINTS = re.compile(
    r"(token|tokens|underlying|underlyings|asset|assets|want|lptoken|"
    r"rewardtoken|reward|rewards|outputtoken|inputtoken|governance|"
    r"symbol|gecko|coingecko|gasToken|nativeToken|ignoredtoken|"
    r"blacklist|whitelist_token|dummyToken)",
    re.I,
)
ADDR_RE = re.compile(r"0x[a-fA-F0-9]{40}")
CHAIN_KEY_RE = re.compile(
    r"""(?<![.\w$])(?P<q>['"]?)(?P<chain>[A-Za-z][A-Za-z0-9_]*)(?P=q)\s*:""",
)
REQUIRE_RE = re.compile(
    r"""require\(\s*['"](\.[^'"]+)['"]\s*\)""",
)
COMMENT_RE = re.compile(r"//.*?$|/\*.*?\*/", re.S | re.M)

EIP1967_IMPL = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
EIP1967_ADMIN = "0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103"
MULTICALL3 = "0xca11bde05977b3631167028862be2a173976ca11"
AGGREGATE3_SEL = "82ad56cb"
BALANCE_OF_SEL = "70a08231"
GET_ETH_BALANCE_SEL = "4d2301cc"


def log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def http_json(url: str, data: bytes | None = None, timeout: float = 30.0, retries: int = 3) -> Any:
    headers = {
        "User-Agent": UA,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": "https://defillama.com",
    }
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp)
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.4 * (i + 1))
    raise last  # type: ignore[misc]


def norm_addr(a: str) -> str:
    return a.lower()


def is_eth_addr(a: str | None) -> bool:
    if not a or not isinstance(a, str):
        return False
    a = a.strip()
    if ":" in a:
        chain, _, rest = a.partition(":")
        if chain.lower() not in {"ethereum", "eth", "mainnet"}:
            return False
        a = rest
    return bool(re.fullmatch(r"0x[a-fA-F0-9]{40}", a))


def extract_eth_addr(a: str | None) -> str | None:
    if not a or not isinstance(a, str):
        return None
    a = a.strip()
    if ":" in a:
        chain, _, rest = a.partition(":")
        if chain.lower() not in {"ethereum", "eth", "mainnet"}:
            return None
        a = rest
    if re.fullmatch(r"0x[a-fA-F0-9]{40}", a):
        return norm_addr(a)
    return None


def eth_tvl(p: dict) -> float | None:
    v = (p.get("chainTvls") or {}).get("Ethereum")
    if isinstance(v, (int, float)):
        return float(v)
    return None


def load_inputs() -> tuple[list, list, dict, dict, list]:
    with open(ROOT / "draft.json") as f:
        draft = json.load(f)
    with open(ROOT / "protocols.json") as f:
        protocols = json.load(f)
    by_slug = {p["slug"]: p for p in protocols}
    by_id = {str(p["id"]): p for p in protocols}
    hacks = []
    if HACKS_PATH.exists():
        with open(HACKS_PATH) as f:
            hacks = json.load(f)
    return draft, protocols, by_slug, by_id, hacks


def fork_parent_name(p: dict, by_id: dict) -> str | None:
    ids = p.get("forkedFromIds") or []
    names = []
    for i in ids:
        parent = by_id.get(str(i))
        if parent:
            names.append(parent.get("name") or f"id:{i}")
        else:
            names.append(f"id:{i}")
    raw = p.get("forkedFrom")
    if raw and not ids:
        if isinstance(raw, list):
            for x in raw:
                parent = by_id.get(str(x))
                names.append(parent["name"] if parent else str(x))
        else:
            names.append(str(raw))
    return ", ".join(names) if names else None


def hack_index(hacks: list, by_id: dict, by_slug: dict) -> dict[str, list]:
    """Map protocol slug -> list of hack summaries."""
    by_name = {p["name"].lower(): p for p in by_slug.values()}
    out: dict[str, list] = defaultdict(list)
    for h in hacks:
        p = None
        did = h.get("defillamaId")
        if did not in (None, "", 0, "0"):
            p = by_id.get(str(did))
        if not p:
            p = by_name.get((h.get("name") or "").lower())
        if not p:
            continue
        chains = h.get("chain") or []
        if isinstance(chains, str):
            chains = [chains]
        # Keep ETH hacks, plus hacks with no chain listed, plus protocol-level
        # incidents (redeploys still holding ETH TVL).
        chain_l = {str(c).lower() for c in chains}
        if chain_l and "ethereum" not in chain_l and "mainnet" not in chain_l:
            # Still attach if the protocol currently has ETH TVL; it may have
            # redeployed or continued on Ethereum.
            if not eth_tvl(p):
                continue
        out[p["slug"]].append(
            {
                "name": h.get("name"),
                "date": h.get("date"),
                "amount": h.get("amount"),
                "technique": h.get("technique"),
                "classification": h.get("classification"),
            }
        )
    return out


def reasons_for(p: dict, in_draft: bool, by_id: dict, hacks_by_slug: dict) -> list[str]:
    reasons = []
    audits = str(p.get("audits") or "0")
    if audits == "0":
        reasons.append("no-audit")
    if p["slug"] in hacks_by_slug:
        reasons.append("past-hack")
    fp = fork_parent_name(p, by_id)
    if fp:
        reasons.append(f"fork:{fp}")
    cat = p.get("category") or ""
    if cat in COMPLEX_CATS:
        reasons.append(COMPLEX_CATS[cat])
    listed = p.get("listedAt")
    if isinstance(listed, (int, float)) and listed > 0:
        age_days = (NOW - listed) / 86400.0
        if 0 <= age_days <= NEW_LISTING_DAYS:
            reasons.append("new-listing")
    return reasons


def should_add_extra(p: dict, reasons: list[str]) -> bool:
    ev = eth_tvl(p)
    if ev is None or ev < MIN_USD or ev > MAX_PROTOCOL_TVL:
        return False
    cat = p.get("category") or ""
    if cat in SKIP_EXTRA_CATS:
        return False
    # Money-holding extras: special reasons or money-adjacent categories.
    if reasons:
        return True
    # Money-holding categories that were previously filtered out of the 655
    # but still custody funds (even if audited / not a fork).
    extra_money_cats = {
        "Cross Chain Bridge", "Canonical Bridge", "Options Vault",
        "Uncollateralized Lending", "NFT Lending", "Risk Curators",
        "Onchain Capital Allocator", "Liquidity Manager", "Liquidity Automation",
        "Partially Algorithmic Stablecoin", "Interest Rate Derivatives",
        "Decentralized BTC", "Anchor BTC", "Privacy", "Token Locker",
        "Yield Lottery", "NFT Automated Strategies", "Liquidations",
        "Treasury Manager", "NFT Lending",
        # Same cats as the original 655, in case a protocol was dropped
        # only as a "big name":
        "Lending", "Dexs", "Yield", "Yield Aggregator", "CDP", "Bridge",
        "Options", "Derivatives", "Algo-Stables", "Liquid Staking",
        "Liquid Restaking", "Restaking", "Leveraged Farming", "Synthetics",
        "Indexes", "Insurance", "Farm", "RWA", "Staking Pool", "Payments",
        "Basis Trading", "Reserve Currency", "Launchpad", "Services",
    }
    return cat in extra_money_cats


def select_protocols(draft, protocols, by_slug, by_id, hacks_by_slug) -> list[dict]:
    selected = []
    seen = set()
    for d in draft:
        p = by_slug.get(d["slug"]) or {}
        ev = d.get("eth_tvl")
        if ev is None:
            ev = eth_tvl(p) or 0
        rec = {
            "name": d.get("name") or p.get("name"),
            "slug": d["slug"],
            "category": d.get("cat") or p.get("category"),
            "defillama_eth_tvl": float(ev or 0),
            "audits": str(d.get("audits") if d.get("audits") is not None else p.get("audits") or "0"),
            "module": p.get("module"),
            "protocol_address": d.get("address") or p.get("address"),
            "url": d.get("url") or p.get("url"),
            "listedAt": p.get("listedAt"),
            "in_original_draft": True,
            "forked_from": fork_parent_name(p, by_id) if p else None,
        }
        rec["reasons"] = reasons_for(p or rec, True, by_id, hacks_by_slug)
        selected.append(rec)
        seen.add(d["slug"])
    extras = 0
    for p in protocols:
        if p.get("slug") in seen:
            continue
        ev = eth_tvl(p)
        if ev is None:
            continue
        reasons = reasons_for(p, False, by_id, hacks_by_slug)
        if not should_add_extra(p, reasons):
            continue
        rec = {
            "name": p.get("name"),
            "slug": p["slug"],
            "category": p.get("category"),
            "defillama_eth_tvl": ev,
            "audits": str(p.get("audits") or "0"),
            "module": p.get("module"),
            "protocol_address": p.get("address"),
            "url": p.get("url"),
            "listedAt": p.get("listedAt"),
            "in_original_draft": False,
            "forked_from": fork_parent_name(p, by_id),
            "reasons": reasons or ["expanded-money-holding"],
        }
        selected.append(rec)
        extras += 1
    log(f"selected protocols: {len(selected)} (draft {len(draft)} + extras {extras})")
    return selected


# -------------------- adapter address extraction --------------------

def _adapter_index() -> dict[str, Path]:
    idx = {}
    if not ADAPTERS.exists():
        return idx
    for p in ADAPTERS.iterdir():
        idx[p.name.lower()] = p
    return idx


ADAPTER_IDX: dict[str, Path] = {}


def resolve_module_path(module: str | None, slug: str) -> Path | None:
    if not module or module in ("false", "true", True, False):
        return None
    module = str(module)
    exact = ADAPTERS / module
    if exact.exists():
        return exact
    parts = module.split("/")
    first = ADAPTER_IDX.get(parts[0].lower())
    if first:
        if len(parts) == 1:
            return first
        rest = first.joinpath(*parts[1:])
        if rest.exists():
            return rest
        if first.is_dir() and (first / "index.js").exists():
            return first / "index.js"
    alt = ADAPTER_IDX.get(slug.lower())
    if alt:
        if alt.is_dir() and (alt / "index.js").exists():
            return alt / "index.js"
        if alt.is_file():
            return alt
    return None


def local_requires(src: str, src_path: Path) -> list[Path]:
    out = []
    for m in REQUIRE_RE.finditer(src):
        rel = m.group(1)
        # stay inside the project folder; skip helper/
        if "helper" in Path(rel).parts:
            continue
        cand = (src_path.parent / rel)
        for ext in ("", ".js", ".json", "/index.js"):
            p = Path(str(cand) + ext) if ext and not cand.suffix else cand
            if ext == "/index.js" and cand.suffix:
                continue
            if p.exists() and p.is_file():
                out.append(p)
                break
    return out


def strip_comments(src: str) -> str:
    return COMMENT_RE.sub(lambda m: " " * (m.end() - m.start()), src)


def is_non_eth_chain(name: str) -> bool:
    n = name.lower().replace("-", "_")
    if n in {"ethereum", "eth", "mainnet", "canonical", "tvl", "staking",
             "pool2", "borrowed", "ownTokens", "vesting", "methodology",
             "misrepresentedTokens", "deadFrom", "hallmarks", "doublecounted",
             "timetravel", "start", "incentives", "treasury"}:
        return False
    if n in NON_ETH_CHAINS:
        return True
    # camelCase chain names like polygonZkevm
    compact = n.replace("_", "")
    if compact in {c.replace("_", "") for c in NON_ETH_CHAINS}:
        return True
    return False


def extract_from_source(src: str) -> list[tuple[str, str, str]]:
    """Return (address, label, zone) with zone in {ethereum, shared, other}."""
    text = strip_comments(src)
    n = len(text)
    # Precompute chain-keyed regions via brace matching.
    regions: list[tuple[int, int, str]] = []  # start, end, zone
    for m in CHAIN_KEY_RE.finditer(text):
        chain = m.group("chain")
        # Only treat as a chain key if followed by { or an address-ish value
        rest = text[m.end():m.end() + 80].lstrip()
        zone = None
        cl = chain.lower()
        if cl in {"ethereum", "eth", "mainnet"}:
            zone = "ethereum"
        elif is_non_eth_chain(chain):
            zone = "other"
        else:
            continue
        # find next non-space
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
            # single-line assignment, take until comma/newline/brace
            k = j
            while k < n and text[k] not in ",\n}":
                k += 1
            regions.append((j, k, zone))

    def zone_for(pos: int) -> str:
        # innermost region
        hit = None
        for a, b, z in regions:
            if a <= pos < b:
                if hit is None or (b - a) < (hit[1] - hit[0]):
                    hit = (a, b, z)
        return hit[2] if hit else "shared"

    found = []
    for m in ADDR_RE.finditer(text):
        addr = norm_addr(m.group(0))
        if addr in DENYLIST:
            continue
        # label: look behind ~80 chars for an identifier
        start = max(0, m.start() - 120)
        prefix = text[start:m.start()]
        label = ""
        km = re.search(
            r"""([A-Za-z_][A-Za-z0-9_]*)\s*['"]?\s*(?::|=)\s*\[?\s*(?:['"]0x[a-fA-F0-9]{0,40})?$""",
            prefix,
        )
        if km:
            label = km.group(1)
        else:
            # owners: [ ..., '0x'
            km = re.search(r"""([A-Za-z_][A-Za-z0-9_]*)\s*:\s*\[[^\]]*$""", prefix)
            if km:
                label = km.group(1)
        zone = zone_for(m.start())
        found.append((addr, label, zone))
    return found


def extract_protocol_addresses(rec: dict) -> list[dict]:
    """Extract candidate addresses for one protocol."""
    items = []  # addr -> meta
    seen = {}

    def add(addr, label, source, zone="ethereum"):
        if not addr or addr in DENYLIST:
            return
        if len(addr) != 42:
            return
        rec_item = seen.get(addr)
        if rec_item is None:
            rec_item = {
                "address": addr,
                "label": label or "",
                "sources": [source],
                "zone": zone,
            }
            seen[addr] = rec_item
            items.append(rec_item)
        else:
            if source not in rec_item["sources"]:
                rec_item["sources"].append(source)
            # Prefer an owner/vault label over a token/empty label.
            old = rec_item["label"] or ""
            if label:
                if not old:
                    rec_item["label"] = label
                elif OWNER_HINTS.search(label) and not OWNER_HINTS.search(old):
                    rec_item["label"] = label
            if zone == "ethereum":
                rec_item["zone"] = "ethereum"

    module_path = resolve_module_path(rec.get("module"), rec["slug"])
    if module_path:
        files = [module_path]
        seen_files = {module_path.resolve()}
        # one-level local requires + same-folder js if small project
        try:
            src0 = module_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            src0 = ""
        if src0:
            for p in local_requires(src0, module_path):
                if p.resolve() not in seen_files:
                    files.append(p)
                    seen_files.add(p.resolve())
        # also sibling files in the same project dir (capped)
        if module_path.parent != ADAPTERS and module_path.parent.is_dir():
            sibs = list(module_path.parent.glob("*.js")) + list(module_path.parent.glob("*.json"))
            for p in sibs[:20]:
                if p.resolve() not in seen_files and "helper" not in p.parts:
                    files.append(p)
                    seen_files.add(p.resolve())
        for fp in files:
            try:
                src = fp.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = str(fp.relative_to(ADAPTERS)) if ADAPTERS in fp.parents or fp.parent == ADAPTERS else fp.name
            for addr, label, zone in extract_from_source(src):
                if zone == "other":
                    continue
                add(addr, label, f"defillama-adapter:{rel}", zone)

    proto_addr = extract_eth_addr(rec.get("protocol_address"))
    if proto_addr:
        # This DefiLlama field is usually the governance / protocol token.
        add(proto_addr, "protocol-token", "defillama-protocol-address", "ethereum")

    # If an address is only the protocol token and never appeared in an
    # adapter owner/vault context, keep it for now and drop later if it
    # looks token-only or is under the funds floor.
    return items


def extract_all(selected: list[dict]) -> list[dict]:
    rows = []
    unresolved_extract = []
    for rec in selected:
        addrs = extract_protocol_addresses(rec)
        eth_addrs = [a for a in addrs if a["zone"] != "other"]
        if not eth_addrs:
            unresolved_extract.append(
                {
                    "slug": rec["slug"],
                    "name": rec["name"],
                    "reason": "no-ethereum-address-in-adapter-or-metadata",
                    "module": rec.get("module"),
                    "defillama_eth_tvl": rec["defillama_eth_tvl"],
                }
            )
        for a in eth_addrs:
            rows.append({**rec, **a})
    log(f"extracted address rows: {len(rows)} from {len(selected)} protocols; "
        f"no-address protocols: {len(unresolved_extract)}")
    (WORK / "extracted_addresses.json").write_text(json.dumps(rows, indent=2))
    (WORK / "unresolved_extract.json").write_text(json.dumps(unresolved_extract, indent=2))
    return rows, unresolved_extract


# -------------------- RPC --------------------

class RpcPool:
    def __init__(self, urls: list[str]):
        self.urls = list(urls)
        self.i = 0
        self.lock_i = 0

    def next_url(self) -> str:
        url = self.urls[self.i % len(self.urls)]
        self.i += 1
        return url

    def call_batch(self, calls: list[dict], timeout: float = 40.0) -> list[Any]:
        """calls are {method, params}. Returns list of results (or None)."""
        payload = [
            {"jsonrpc": "2.0", "id": i, "method": c["method"], "params": c["params"]}
            for i, c in enumerate(calls)
        ]
        data = json.dumps(payload).encode()
        last_err = None
        for attempt in range(len(self.urls)):
            url = self.next_url()
            try:
                req = urllib.request.Request(
                    url,
                    data=data,
                    headers={
                        "User-Agent": UA,
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "Origin": "https://etherscan.io",
                    },
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    raw = json.load(resp)
                if isinstance(raw, dict):
                    # some providers wrap errors
                    last_err = raw.get("error") or raw
                    continue
                by_id = {item.get("id"): item for item in raw if isinstance(item, dict)}
                out = []
                for i in range(len(calls)):
                    item = by_id.get(i) or {}
                    out.append(item.get("result"))
                return out
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                time.sleep(0.15)
        log(f"rpc batch failed after rotation: {last_err}")
        return [None] * len(calls)


def pad32_addr(addr: str) -> str:
    return addr.lower().replace("0x", "").rjust(64, "0")


def encode_balance_of(holder: str) -> str:
    return "0x" + BALANCE_OF_SEL + pad32_addr(holder)


def encode_get_eth_balance(holder: str) -> str:
    return "0x" + GET_ETH_BALANCE_SEL + pad32_addr(holder)


def encode_aggregate3(calls: list[tuple[str, str]]) -> str:
    """calls: list of (target, calldata_hex). allowFailure=True."""
    from eth_abi import encode

    tuples = []
    for target, data in calls:
        if data.startswith("0x"):
            data_b = bytes.fromhex(data[2:])
        else:
            data_b = bytes.fromhex(data)
        tuples.append((target, True, data_b))
    encoded = encode(["(address,bool,bytes)[]"], [tuples])
    return "0x" + AGGREGATE3_SEL + encoded.hex()


def decode_aggregate3(result: str) -> list[tuple[bool, bytes]]:
    from eth_abi import decode

    if not result or result in ("0x", "0x0"):
        return []
    raw = bytes.fromhex(result[2:])
    decoded = decode(["(bool,bytes)[]"], raw)[0]
    return [(ok, data) for ok, data in decoded]


def chunked(seq: list, n: int) -> Iterable[list]:
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def fetch_prices() -> dict[str, float]:
    coins = ["coingecko:ethereum"]
    for name, meta in TOKENS.items():
        if meta["address"]:
            coins.append("ethereum:" + meta["address"])
    url = "https://coins.llama.fi/prices/current/" + ",".join(coins)
    data = http_json(url, timeout=30)
    prices = data.get("coins") or {}
    out = {}
    eth = prices.get("coingecko:ethereum") or {}
    out["ETH"] = float(eth.get("price") or 0)
    for name, meta in TOKENS.items():
        if not meta["address"]:
            continue
        key = "ethereum:" + meta["address"]
        rec = prices.get(key) or {}
        out[name] = float(rec.get("price") or 0)
    if not out.get("WETH"):
        out["WETH"] = out.get("ETH") or 0
    log(f"prices: {out}")
    return out


def rpc_get_code(pool: RpcPool, addresses: list[str]) -> dict[str, str]:
    result = {}
    addrs = list(dict.fromkeys(addresses))
    log(f"eth_getCode for {len(addrs)} unique addresses")
    batches = list(chunked(addrs, 80))

    def run(batch):
        calls = [{"method": "eth_getCode", "params": [a, "latest"]} for a in batch]
        res = pool.call_batch(calls)
        return list(zip(batch, res))

    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(run, b) for b in batches]
        for fut in as_completed(futs):
            for addr, code in fut.result():
                result[addr] = code or "0x"
    contracts = sum(1 for v in result.values() if v and v not in ("0x", "0x0"))
    log(f"contracts with code: {contracts} / {len(addrs)}")
    return result


def rpc_storage(pool: RpcPool, addresses: list[str]) -> dict[str, dict]:
    result = {a: {"impl": None, "admin": None} for a in addresses}
    if not addresses:
        return result
    log(f"eip-1967 storage for {len(addresses)} contracts")
    pairs = []
    for a in addresses:
        pairs.append((a, "impl", EIP1967_IMPL))
        pairs.append((a, "admin", EIP1967_ADMIN))

    def run(batch):
        calls = [
            {"method": "eth_getStorageAt", "params": [a, slot, "latest"]}
            for a, _k, slot in batch
        ]
        res = pool.call_batch(calls)
        return list(zip(batch, res))

    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(run, b) for b in chunked(pairs, 80)]
        for fut in as_completed(futs):
            for (addr, key, _slot), val in fut.result():
                if not val or val == "0x":
                    continue
                # last 20 bytes
                try:
                    addr20 = "0x" + val[-40:]
                except Exception:
                    continue
                if addr20 != "0x0000000000000000000000000000000000000000":
                    result[addr][key] = addr20
    n_proxy = sum(1 for v in result.values() if v["impl"])
    n_admin = sum(1 for v in result.values() if v["admin"])
    log(f"eip-1967 proxies: {n_proxy}, with admin slot: {n_admin}")
    return result


def rpc_balances(pool: RpcPool, addresses: list[str]) -> dict[str, dict]:
    """ETH + major token balances via Multicall3."""
    out = {a: {k: 0 for k in TOKENS} for a in addresses}
    if not addresses:
        return out
    token_list = [(n, m) for n, m in TOKENS.items() if m["address"]]
    log(f"balances for {len(addresses)} contracts via multicall3")

    def one_chunk(chunk: list[str]) -> list[tuple[str, dict]]:
        calls = []
        index = []  # (addr, token_name)
        for a in chunk:
            calls.append((MULTICALL3, encode_get_eth_balance(a)))
            index.append((a, "ETH"))
            for name, meta in token_list:
                calls.append((meta["address"], encode_balance_of(a)))
                index.append((a, name))
        data = encode_aggregate3(calls)
        res_list = pool.call_batch(
            [{"method": "eth_call", "params": [{"to": MULTICALL3, "data": data}, "latest"]}]
        )
        raw = res_list[0] if res_list else None
        balances = {a: {k: 0 for k in TOKENS} for a in chunk}
        if not raw:
            return list(balances.items())
        try:
            decoded = decode_aggregate3(raw)
        except Exception as exc:  # noqa: BLE001
            log(f"multicall decode failed: {exc}")
            return list(balances.items())
        for i, (ok, ret) in enumerate(decoded):
            if i >= len(index):
                break
            addr, name = index[i]
            if not ok or not ret:
                continue
            try:
                val = int.from_bytes(ret[-32:], "big") if len(ret) >= 32 else int.from_bytes(ret, "big")
            except Exception:
                continue
            balances[addr][name] = val
        return list(balances.items())

    chunks = list(chunked(addresses, 35))
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(one_chunk, c) for c in chunks]
        done = 0
        for fut in as_completed(futs):
            for addr, bal in fut.result():
                out[addr] = bal
            done += 1
            if done % 10 == 0 or done == len(chunks):
                log(f"  balance chunks {done}/{len(chunks)}")
    return out


def usd_held(bal: dict, prices: dict) -> float:
    total = 0.0
    for name, raw in bal.items():
        meta = TOKENS[name]
        units = raw / (10 ** meta["decimals"])
        total += units * (prices.get(name) or 0.0)
    return total


def looks_token_only(item: dict, bal_usd: float) -> bool:
    sources = item.get("sources") or []
    label = (item.get("label") or "").lower()
    if label in {"protocol-token", "token", "tokens", "reward", "rewardtoken", "governance"}:
        # Drop if the only source is the DefiLlama token address field,
        # or token-hint label without an owner hint and modest balances.
        only_proto = sources == ["defillama-protocol-address"] or set(sources) == {
            "defillama-protocol-address"
        }
        if only_proto:
            return True
        if TOKEN_HINTS.search(label) and not OWNER_HINTS.search(label) and bal_usd < 50_000:
            return True
    if TOKEN_HINTS.search(label) and not OWNER_HINTS.search(label):
        # adapter listed it under tokens: [...]
        if any("adapter" in s for s in sources) and not OWNER_HINTS.search(label):
            return True
    return False


def sourcify_verified(addresses: list[str]) -> set[str]:
    verified = set()
    if not addresses:
        return verified
    log(f"sourcify check for {len(addresses)} addresses")
    for batch in chunked(addresses, 25):
        q = "addresses=" + ",".join(batch) + "&chainIds=1"
        url = "https://sourcify.dev/server/check-by-addresses?" + q
        try:
            data = http_json(url, timeout=25, retries=2)
        except Exception as exc:  # noqa: BLE001
            log(f"sourcify batch failed: {exc}")
            continue
        rows = data if isinstance(data, list) else []
        for row in rows:
            status = (row.get("status") or row.get("chainIds") or "")
            addr = norm_addr(row.get("address") or "")
            # API returns {address, status: 'perfect'|'partial'|'false'}
            st = row.get("status")
            if addr and st and st not in ("false", False, "null", None, ""):
                verified.add(addr)
            # newer format: chainIds: [{chainId, status}]
            cids = row.get("chainIds")
            if addr and isinstance(cids, list):
                for c in cids:
                    if str(c.get("chainId") or c.get("chainid") or "") in {"1", "0x1"}:
                        if c.get("status") not in ("false", False, None, ""):
                            verified.add(addr)
        time.sleep(0.05)
    log(f"sourcify verified: {len(verified)}")
    return verified


def assign_tier(reasons: list[str]) -> int:
    rset = reasons
    high = {"no-audit", "past-hack", "unverified-source"}
    mid_prefixes = ("fork:", "complex:", "new-listing", "upgradeable-admin", "upgradeable-proxy")
    if any(r in high for r in rset):
        return 1
    if any(r.startswith(p) if p.endswith(":") else r == p or r.startswith(p) for r in rset for p in mid_prefixes):
        return 2
    return 3


def build_output(selected, rows, codes, storage, balances, prices, unresolved_extract):
    # Join unique address+slug
    candidates = []
    dropped = []
    proto_has_keep = set()
    for item in rows:
        addr = item["address"]
        code = codes.get(addr) or "0x"
        is_contract = bool(code) and code not in ("0x", "0x0")
        bal = balances.get(addr) or {k: 0 for k in TOKENS}
        usd = usd_held(bal, prices) if is_contract else 0.0
        token_only = looks_token_only(item, usd)
        st = storage.get(addr) or {}
        reasons = list(item.get("reasons") or [])
        if st.get("impl"):
            if "upgradeable-proxy" not in reasons:
                reasons.append("upgradeable-proxy")
        if st.get("admin"):
            if "upgradeable-admin" not in reasons:
                reasons.append("upgradeable-admin")

        drop_reason = None
        if not is_contract:
            drop_reason = "eoa-or-empty-code"
        elif token_only:
            drop_reason = "token-only-or-passthrough"
        elif usd < _discovery_floor():
            drop_reason = "below-discovery-floor"
        elif usd < MIN_USD:
            # Kept out of List 1. The discovery lane still scans this band.
            drop_reason = "discovery-band-below-list1"

        rec = {
            "protocol": item["name"],
            "slug": item["slug"],
            "category": item["category"],
            "defillama_eth_tvl": round(item["defillama_eth_tvl"], 2),
            "audits": item["audits"],
            "address": addr,
            "label": item.get("label") or "",
            "verified_contract": bool(is_contract),
            "est_usd_held": round(usd, 2),
            "source": ";".join(item.get("sources") or []),
            "candidate_reason": ";".join(reasons),
            "tier": assign_tier(reasons),
            "in_original_draft": item.get("in_original_draft", False),
            "forked_from": item.get("forked_from"),
            "proxy_implementation": st.get("impl"),
            "proxy_admin": st.get("admin"),
            "balances_raw": {k: str(v) for k, v in bal.items()} if is_contract else {},
        }
        if drop_reason:
            rec["drop_reason"] = drop_reason
            if drop_reason == "discovery-band-below-list1":
                rec["discovery_lane"] = True
            dropped.append(rec)
        else:
            candidates.append(rec)
            proto_has_keep.add(item["slug"])

    # Rank: tier asc, then est_usd_held desc, then protocol TVL desc
    candidates.sort(
        key=lambda r: (r["tier"], -r["est_usd_held"], -r["defillama_eth_tvl"], r["slug"], r["address"])
    )
    for i, r in enumerate(candidates, 1):
        r["rank"] = i

    # Unresolved protocols: selected but no kept address
    selected_slugs = {s["slug"]: s for s in selected}
    unresolved = []
    extract_map = {u["slug"]: u for u in unresolved_extract}
    for slug, rec in selected_slugs.items():
        if slug in proto_has_keep:
            continue
        dropped_for = [d for d in dropped if d["slug"] == slug]
        if slug in extract_map and not dropped_for:
            reason = extract_map[slug]["reason"]
        elif dropped_for:
            reasons = sorted({d["drop_reason"] for d in dropped_for})
            reason = "addresses-found-but-dropped:" + ",".join(reasons)
        else:
            reason = "unresolved"
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
    return candidates, dropped, unresolved


def write_outputs(candidates, dropped, unresolved, selected, prices):
    # JSON: strip balances_raw from main file? keep a compact version
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
                "proxy_implementation": r["proxy_implementation"],
                "proxy_admin": r["proxy_admin"],
            }
        )
    (ROOT / "master_candidates.json").write_text(json.dumps(compact, indent=2))
    fields = [
        "rank", "tier", "protocol", "slug", "category", "defillama_eth_tvl",
        "audits", "address", "label", "verified_contract", "est_usd_held",
        "source", "candidate_reason", "in_original_draft", "forked_from",
        "proxy_implementation", "proxy_admin",
    ]
    with open(ROOT / "master_candidates.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in compact:
            w.writerow({k: r.get(k) if r.get(k) is not None else "" for k in fields})
    (WORK / "dropped.json").write_text(json.dumps(dropped, indent=2))
    (ROOT / "unresolved.json").write_text(json.dumps(unresolved, indent=2))
    summary = {
        "generated_at_unix": int(NOW),
        "prices": prices,
        "selected_protocols": len(selected),
        "original_draft": sum(1 for s in selected if s["in_original_draft"]),
        "extras": sum(1 for s in selected if not s["in_original_draft"]),
        "kept_addresses": len(candidates),
        "kept_protocols": len({c["slug"] for c in candidates}),
        "unresolved_protocols": len(unresolved),
        "dropped_addresses": len(dropped),
        "min_usd": MIN_USD,
        "max_protocol_tvl": MAX_PROTOCOL_TVL,
        "new_listing_days": NEW_LISTING_DAYS,
        "tokens_priced": list(TOKENS),
    }
    (WORK / "summary.json").write_text(json.dumps(summary, indent=2))
    log(f"wrote {ROOT/'master_candidates.json'} ({len(candidates)} addresses) and csv")
    return summary


def main() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    global ADAPTER_IDX
    ADAPTER_IDX = _adapter_index()
    log(f"adapter index: {len(ADAPTER_IDX)} entries")

    draft, protocols, by_slug, by_id, hacks = load_inputs()
    hacks_by_slug = hack_index(hacks, by_id, by_slug)
    log(f"hacks matched to some protocol: {len(hacks_by_slug)}")
    selected = select_protocols(draft, protocols, by_slug, by_id, hacks_by_slug)
    (WORK / "selected_protocols.json").write_text(json.dumps(selected, indent=2))

    rows, unresolved_extract = extract_all(selected)
    unique_addrs = sorted({r["address"] for r in rows})
    log(f"unique addresses to probe: {len(unique_addrs)}")

    prices = fetch_prices()
    pool = RpcPool(RPCS)
    codes = rpc_get_code(pool, unique_addrs)
    contracts = [a for a, c in codes.items() if c and c not in ("0x", "0x0")]
    # Skip denylisted already; still skip EOAs for storage/balances
    storage = rpc_storage(pool, contracts)
    balances = rpc_balances(pool, contracts)

    (WORK / "rpc_codes_count.json").write_text(
        json.dumps({"unique": len(unique_addrs), "contracts": len(contracts)})
    )
    (WORK / "rpc_balances.json").write_text(
        json.dumps({a: {k: str(v) for k, v in b.items()} for a, b in balances.items()})
    )
    (WORK / "rpc_storage.json").write_text(json.dumps(storage))

    # Sourcify on contracts that will likely survive? Do all contracts, it's ok.
    # To save time, only those with some ETH or later after usd filter.
    # We'll annotate after first pass if needed. Compute usd first in build,
    # then optional sourcify on kept + borderline. Do sourcify on contracts
    # with any ETH/token raw > 0 to limit volume.
    nonzero = []
    for a, bal in balances.items():
        if any(v > 0 for v in bal.values()):
            nonzero.append(a)
    # Sourcify is incomplete vs Etherscan; a miss is not proof of unverified
    # source. Record coverage for the report and only attach a positive match.
    verified = sourcify_verified(nonzero)
    (WORK / "sourcify_verified.json").write_text(json.dumps(sorted(verified)))
    candidates, dropped, unresolved = build_output(
        selected, rows, codes, storage, balances, prices, unresolved_extract
    )
    for rec in candidates:
        rec["sourcify_verified"] = rec["address"] in verified
    # unverified-source is filled later via Etherscan on the kept set, if possible

    summary = write_outputs(candidates, dropped, unresolved, selected, prices)
    # print brief stats
    bands = {"2k-100k": 0, "100k-1m": 0, "1m-9m": 0, "9m+": 0}
    for c in candidates:
        u = c["est_usd_held"]
        if u < 100_000:
            bands["2k-100k"] += 1
        elif u < 1_000_000:
            bands["100k-1m"] += 1
        elif u <= MAX_PROTOCOL_TVL:
            bands["1m-9m"] += 1
        else:
            bands["9m+"] += 1
    log(f"SUMMARY {json.dumps({**summary, 'usd_bands': bands})}")
    log("top 10:")
    for c in candidates[:10]:
        log(f"  #{c['rank']} t{c['tier']} ${c['est_usd_held']:.0f} {c['slug']} {c['address']} {c['candidate_reason']}")


if __name__ == "__main__":
    main()
