"""EVM chain config. Ethereum stays chain id 1 and ETH_RPC_URL.

BNB Chain, Arbitrum One, Base, Optimism, and Polygon reuse the same
pipeline. Each chain reads its own env (BSC_RPC_URL, ARBITRUM_RPC_URL,
BASE_RPC_URL, OPTIMISM_RPC_URL, POLYGON_RPC_URL). When that variable is
unset, the key in ETH_RPC_URL is reused on that chain's Alchemy host.
When there is no Alchemy key, a free public endpoint is used and a 429
is retried once. Ethereum does not gain a public fallback and does not
get its URL rewritten.

Alchemy serves every chain here: eth-mainnet, bnb-mainnet, arb-mainnet,
base-mainnet, opt-mainnet, and polygon-mainnet. They share the $10/month
cap. This module never prints a URL or a key.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Optional

from eth_scanner.chains.registry import normalize_chain

# Same address on Ethereum, BNB Chain, Arbitrum, and Base.
MULTICALL3 = "0xca11bde05977b3631167028862be2a173976ca11"


@dataclass(frozen=True)
class EvmChain:
    name: str
    chain_id: int
    native_symbol: str
    native_price_id: str
    rpc_env: str
    public_rpcs: tuple[str, ...]
    alchemy_host: str
    tokens: tuple[tuple[str, str, str, int], ...]


def _token(symbol: str, address: str, price_id: str, decimals: int) -> tuple[str, str, str, int]:
    return (symbol, address.lower(), price_id, decimals)


EVM_CHAINS: dict[str, EvmChain] = {
    "ethereum": EvmChain(
        name="ethereum",
        chain_id=1,
        native_symbol="ETH",
        native_price_id="ethereum",
        rpc_env="ETH_RPC_URL",
        public_rpcs=(),
        alchemy_host="eth-mainnet.g.alchemy.com",
        tokens=(
            _token("WETH", "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2", "ethereum", 18),
            _token("USDC", "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", "usd-coin", 6),
            _token("USDT", "0xdac17f958d2ee523a2206206994597c13d831ec7", "tether", 6),
        ),
    ),
    "bsc": EvmChain(
        name="bsc",
        chain_id=56,
        native_symbol="BNB",
        native_price_id="binancecoin",
        rpc_env="BSC_RPC_URL",
        public_rpcs=(
            "https://bsc-dataseed.binance.org",
            "https://bsc-dataseed1.defibit.io",
        ),
        alchemy_host="bnb-mainnet.g.alchemy.com",
        tokens=(
            _token("WBNB", "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c", "binancecoin", 18),
            _token("USDT", "0x55d398326f99059ff775485246999027b3197955", "tether", 18),
            _token("USDC", "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d", "usd-coin", 18),
        ),
    ),
    "arbitrum": EvmChain(
        name="arbitrum",
        chain_id=42161,
        native_symbol="ETH",
        native_price_id="ethereum",
        rpc_env="ARBITRUM_RPC_URL",
        public_rpcs=("https://arb1.arbitrum.io/rpc",),
        alchemy_host="arb-mainnet.g.alchemy.com",
        tokens=(
            _token("WETH", "0x82af49447d8a07e3bd95bd0d56f35241523fbab1", "ethereum", 18),
            _token("USDC", "0xaf88d065e77c8cc2239327c5edb3a432268e5831", "usd-coin", 6),
            _token("USDT", "0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9", "tether", 6),
        ),
    ),
    "base": EvmChain(
        name="base",
        chain_id=8453,
        native_symbol="ETH",
        native_price_id="ethereum",
        rpc_env="BASE_RPC_URL",
        public_rpcs=("https://mainnet.base.org",),
        alchemy_host="base-mainnet.g.alchemy.com",
        tokens=(
            _token("WETH", "0x4200000000000000000000000000000000000006", "ethereum", 18),
            _token("USDC", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "usd-coin", 6),
        ),
    ),
    "optimism": EvmChain(
        name="optimism",
        chain_id=10,
        native_symbol="ETH",
        native_price_id="ethereum",
        rpc_env="OPTIMISM_RPC_URL",
        public_rpcs=(
            "https://mainnet.optimism.io",
            "https://optimism.publicnode.com",
        ),
        alchemy_host="opt-mainnet.g.alchemy.com",
        tokens=(
            _token("WETH", "0x4200000000000000000000000000000000000006", "ethereum", 18),
            _token("USDC", "0x0b2c639c533813f4aa9d7837caf62653d097ff85", "usd-coin", 6),
            _token("USDT", "0x94b008aa00579c1307b0ef2c499ad98a8ce58e58", "tether", 6),
        ),
    ),
    "polygon": EvmChain(
        name="polygon",
        chain_id=137,
        native_symbol="POL",
        native_price_id="polygon-ecosystem-token",
        rpc_env="POLYGON_RPC_URL",
        public_rpcs=(
            "https://polygon-rpc.com",
            "https://polygon-bor-rpc.publicnode.com",
        ),
        alchemy_host="polygon-mainnet.g.alchemy.com",
        tokens=(
            _token("WPOL", "0x0d500b1d8e8ef31e21c99d1db9a6444d3adf1270", "polygon-ecosystem-token", 18),
            _token("USDC", "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359", "usd-coin", 6),
            _token("USDT", "0xc2132d05d31c914a87c6611c10748aeb04b58e8f", "tether", 6),
        ),
    ),
}

# Read-only probes. A recognized error means the method exists.
# "method not found" means it does not. A 429 stays unknown.
FEATURE_PROBES: tuple[tuple[str, list[Any]], ...] = (
    ("debug_traceTransaction", ["0x" + "11" * 32]),
    ("trace_filter", [{"fromBlock": "0x1", "toBlock": "0x1"}]),
    ("eth_getProof", ["0x" + "00" * 20, [], "latest"]),
)


def is_evm_chain(value: object) -> bool:
    return normalize_chain(value) in EVM_CHAINS


def target_store_key(chain: str, address: str) -> str:
    """Memory-store key. Ethereum and Solana stay the bare address.

    Other EVM chains use chain:address so both rows can sit in one dict.
    Supabase stores the same pair as the (chain, address) primary key.
    """
    name = normalize_chain(chain)
    if name in {"ethereum", "solana"}:
        return address
    return "%s:%s" % (name, address)


def evm_chain(value: object) -> EvmChain:
    name = normalize_chain(value)
    cfg = EVM_CHAINS.get(name)
    if cfg is None:
        raise KeyError("not an EVM chain: %s" % name)
    return cfg


def alchemy_api_key() -> str:
    """Key from ALCHEMY_API_KEY or from an Alchemy ETH_RPC_URL. Empty if neither.

    The value is for building a URL. Callers must not log it.
    """
    explicit = (os.environ.get("ALCHEMY_API_KEY") or "").strip()
    if explicit and all(ch not in explicit for ch in "/?# \n\t"):
        return explicit
    raw = (os.environ.get("ETH_RPC_URL") or "").strip()
    if "alchemy.com" not in raw.lower() or "/v2/" not in raw:
        return ""
    key = raw.split("/v2/", 1)[1].split("/", 1)[0].split("?", 1)[0].strip()
    if not key or any(ch in key for ch in " \n\t"):
        return ""
    return key


def rpc_endpoints(value: object) -> list[dict[str, str]]:
    """Ordered URLs. Ethereum is only ETH_RPC_URL. Other chains fall through."""
    cfg = evm_chain(value)
    found: list[dict[str, str]] = []
    configured = (os.environ.get(cfg.rpc_env) or "").strip()
    if configured:
        found.append({"source": "configured", "url": configured})
    elif cfg.name != "ethereum":
        key = alchemy_api_key()
        if key and cfg.alchemy_host:
            found.append({
                "source": "alchemy",
                "url": "https://%s/v2/%s" % (cfg.alchemy_host, key),
            })
    if cfg.name != "ethereum":
        for public in cfg.public_rpcs:
            if all(item["url"] != public for item in found):
                found.append({"source": "public", "url": public})
    return found


def rpc_choice(value: object) -> dict[str, Any]:
    """Which URL a caller may use. Ethereum with no ETH_RPC_URL stays unset."""
    cfg = evm_chain(value)
    endpoints = rpc_endpoints(cfg.name)
    if not endpoints:
        return {"chain": cfg.name, "source": "unset", "env": cfg.rpc_env, "url": ""}
    first = endpoints[0]
    return {"chain": cfg.name, "source": first["source"], "env": cfg.rpc_env, "url": first["url"]}


def describe(value: object) -> dict[str, Any]:
    """Public config. The RPC URL is omitted so a key cannot leak into a log."""
    cfg = evm_chain(value)
    choice = rpc_choice(cfg.name)
    return {
        "chain": cfg.name,
        "chain_id": cfg.chain_id,
        "native_symbol": cfg.native_symbol,
        "native_price_id": cfg.native_price_id,
        "rpc_env": cfg.rpc_env,
        "rpc_source": choice["source"],
        "explorer": "etherscan-v2",
        "explorer_chainid": cfg.chain_id,
        "alchemy_host": cfg.alchemy_host,
        "tokens": [row[0] for row in cfg.tokens],
        "heat_contribution": 0,
    }


def describe_all() -> list[dict[str, Any]]:
    return [describe(name) for name in ("ethereum", "bsc", "arbitrum", "base", "optimism", "polygon")]


def explorer_chainid(value: object) -> int:
    return evm_chain(value).chain_id


def classify_method_error(error: BaseException) -> str:
    """A recognized failure means the method exists. A missing method does not.

    Rate limits and auth or filter rejections stay unknown. They are not
    evidence that the endpoint can trace.
    """
    text = str(error).lower()
    if (
        "429" in text
        or "rate limit" in text
        or "too many requests" in text
        or "401" in text
        or "403" in text
        or "auth" in text
        or "rejected" in text
        or "filter" in text
    ):
        return "unknown"
    if (
        "method not found" in text
        or "method not available" in text
        or "not supported" in text
        or "-32601" in text
        or "does not exist" in text
    ):
        return "unsupported"
    return "supported"


def _chain_id_of(result: Any) -> Optional[int]:
    if isinstance(result, dict):
        result = result.get("result", result)
    if isinstance(result, int):
        return result
    text = str(result or "").strip().lower()
    if text.startswith("0x"):
        try:
            return int(text, 16)
        except ValueError:
            return None
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def detect_features(value: object, rpc: Callable[[str, list[Any]], Any]) -> dict[str, Any]:
    """Ask one RPC which trace and proof methods it accepts. Read-only."""
    cfg = evm_chain(value)
    report: dict[str, Any] = {
        "chain": cfg.name,
        "chain_id": cfg.chain_id,
        "heat_contribution": 0,
        "methods": {},
        "degraded": False,
    }
    try:
        observed = _chain_id_of(rpc("eth_chainId", []))
    except Exception as exc:  # noqa: BLE001
        report["methods"]["eth_chainId"] = classify_method_error(exc)
        report["degraded"] = True
        return report
    report["observed_chain_id"] = observed
    report["methods"]["eth_chainId"] = "supported" if observed == cfg.chain_id else "mismatch"
    if observed != cfg.chain_id:
        report["degraded"] = True
    for method, params in FEATURE_PROBES:
        try:
            rpc(method, params)
            status = "supported"
        except Exception as exc:  # noqa: BLE001
            status = classify_method_error(exc)
        report["methods"][method] = status
        if status == "unknown":
            report["degraded"] = True
    return report


def call_with_backoff(
    value: object,
    method: str,
    params: list[Any],
    *,
    rpc: Callable[[str, str, list[Any]], Any],
    pause: Callable[[float], None] = lambda _seconds: None,
) -> Any:
    """Try the configured URL, then public URLs. One pause after HTTP 429.

    Ethereum never receives the public list. ``rpc`` is ``(url, method, params)``.
    """
    cfg = evm_chain(value)
    urls = [item["url"] for item in rpc_endpoints(cfg.name)]
    if not urls:
        raise RuntimeError("%s RPC is unset" % cfg.rpc_env)
    last: Optional[BaseException] = None
    for url in urls:
        for attempt in range(2):
            try:
                return rpc(url, method, params)
            except Exception as exc:  # noqa: BLE001
                last = exc
                if classify_method_error(exc) == "unknown" and attempt == 0:
                    pause(1.0)
                    continue
                break
    raise RuntimeError("%s failed" % method) from last
