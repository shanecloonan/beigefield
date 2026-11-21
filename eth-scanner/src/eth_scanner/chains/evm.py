"""EVM chain config. Ethereum stays chain id 1 and ETH_RPC_URL.

BNB Chain, Arbitrum One, and Base reuse the same pipeline. Their RPC
comes from BSC_RPC_URL, ARBITRUM_RPC_URL, or BASE_RPC_URL. When that
variable is unset, a free public endpoint is used and a 429 is retried
once. Ethereum does not gain a new public fallback here.

Shane's capped Alchemy key also serves bnb-mainnet.g.alchemy.com,
arb-mainnet.g.alchemy.com, and base-mainnet.g.alchemy.com. Those hosts
share the existing $50/month cap. This module never prints a URL.
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
    """Ethereum and Solana stay keyed by the address. Other EVM chains do not.

    The Supabase primary key is still the address alone, so a second EVM
    chain cannot overwrite an Ethereum row. The memory store keeps both.
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


def rpc_choice(value: object) -> dict[str, Any]:
    """Which URL a caller may use. Ethereum with no ETH_RPC_URL stays unset."""
    cfg = evm_chain(value)
    configured = (os.environ.get(cfg.rpc_env) or "").strip()
    if configured:
        return {"chain": cfg.name, "source": "configured", "env": cfg.rpc_env, "url": configured}
    if cfg.name == "ethereum" or not cfg.public_rpcs:
        return {"chain": cfg.name, "source": "unset", "env": cfg.rpc_env, "url": ""}
    return {"chain": cfg.name, "source": "public", "env": cfg.rpc_env, "url": cfg.public_rpcs[0]}


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
    return [describe(name) for name in ("ethereum", "bsc", "arbitrum", "base")]


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
    urls: list[str] = []
    configured = (os.environ.get(cfg.rpc_env) or "").strip()
    if configured:
        urls.append(configured)
    if cfg.name != "ethereum":
        for public in cfg.public_rpcs:
            if public not in urls:
                urls.append(public)
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
