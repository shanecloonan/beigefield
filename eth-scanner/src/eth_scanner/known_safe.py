"""Curated known-safe libraries / protocols — score zero on standard surfaces.

Match by Etherscan verified contract name, source markers, or implementation
address. Defensive only: never treats known-safe as a verdict of safety for
custom business logic layered on top.
"""

from __future__ import annotations

import re
from typing import Any, Optional

# Lowercase substrings / exact names that identify audited library shells.
SAFE_NAME_MARKERS = frozenset({
    "openzeppelin", "oz/", "@openzeppelin",
    "solmate", "solady",
    "erc20permit", "erc20votes", "erc721", "erc1155",
    "ownable", "ownable2step", "accesscontrol", "pausable",
    "reentrancyguard", "initializable", "uupsUpgradeable".lower(),
    "transparentUpgradeableProxy".lower(), "erc1967proxy",
    "clones", "multicall",
})

SAFE_CONTRACT_NAMES = frozenset({
    "erc20", "erc20burnable", "erc20capped", "erc20votes", "erc20wrapper",
    "erc721", "erc721enumerable", "erc721uriStorage".lower(),
    "erc1155", "ownable", "ownable2step", "accesscontrol",
    "timelockcontroller", "governor", "governorcountingSimple".lower(),
    "proxyadmin", "transparentUpgradeableProxy".lower(),
    "erc1967proxy", "beaconproxy", "upgradeablebeacon",
    # Well-known protocol tokens / gauges that are not custom custody bugs.
    "linktoken", "sand", "hex", "frxusd", "frxeth", "sfrxeth",
    "weth9", "weth", "wsteth", "steth", "dai", "usdc", "usdt",
    "liquiditygauge", "liquiditygaugev2", "liquiditygaugev3",
    "liquiditygaugev4", "liquiditygaugev5", "liquiditygaugev6",
    "curve.fi liquidity gauge", "vyper_contract",
    "uniswapv2pair", "uniswapv2factory", "uniswapv2router02",
    "uniswapv3pool", "uniswapv3factory", "swaprouter", "swaprouter02",
    "nonfungiblepositionmanager",
})

# Mainnet implementations / tokens that should never heat from code-shape alone.
SAFE_ADDRESSES = frozenset({
    # LINK
    "0x514910771af9ca656af840dff83e8264ecf986ca",
    # SAND
    "0x3845badade8e6dff049820680d1f14bd3903a5d0",
    # HEX
    "0x2b591e99afe9f32eaa6214f7b7629768c40eeb39",
    # FrxUSD
    "0xcacd6fd266af91b8aed52accc382b4e165586e29",
    # Curve.fi alUSDavUSD Liquidity Gauge Deposit
    "0x1270787da38849fc5f3148357f3b8f6e69ab3858",
    # WETH
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
    # wstETH
    "0x7f39c581f595b53a5c1df47d1b2b8b17df4c43fa",
    # USDC
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
    # USDT
    "0xdac17f958d2ee523a2206206994597c13d831ec7",
    # DAI
    "0x6b175474e89094c44da98b954eedeac495271d0f",
})

_OZ_IMPORT = re.compile(
    r"@openzeppelin/|openzeppelin-contracts|contracts/access/Ownable|"
    r"contracts/token/ERC20|contracts/proxy/|solmate/|solady/",
    re.I,
)


def is_known_safe(
    *,
    address: str = "",
    contract_name: Optional[str] = None,
    source: str = "",
    implementation: Optional[str] = None,
) -> tuple[bool, list[str]]:
    """Return (safe, reasons). Safe contracts get zero code-shape heat."""
    reasons: list[str] = []
    addr = (address or "").strip().lower()
    impl = (implementation or "").strip().lower()
    if addr in SAFE_ADDRESSES:
        reasons.append("curated-address:%s" % addr)
    if impl in SAFE_ADDRESSES:
        reasons.append("curated-implementation:%s" % impl)

    name = (contract_name or "").strip().lower().replace(" ", "")
    if name and name in SAFE_CONTRACT_NAMES:
        reasons.append("contract-name:%s" % name)
    for marker in SAFE_NAME_MARKERS:
        if name and marker.replace("/", "") in name:
            reasons.append("name-marker:%s" % marker)
            break

    src = source or ""
    if src and _OZ_IMPORT.search(src[:8000]):
        # Only treat as known-safe shell when the *primary* surface looks like
        # a bare token/proxy — still record the marker for demotion helpers.
        reasons.append("openzeppelin-or-solmate-import")

    # Pure ERC-20 / Ownable shells with no custom custody verbs → safe.
    if name in {"erc20", "linktoken", "sand", "hex", "frxusd", "weth9", "dai"}:
        if "curated-address" not in ",".join(reasons) and addr:
            reasons.append("well-known-token-name")

    return (bool(reasons and (
        any(r.startswith("curated-") for r in reasons)
        or any(r.startswith("contract-name:") for r in reasons)
        or name in SAFE_CONTRACT_NAMES
    )), reasons)


def filter_standard_movers(
    movers: list[str],
    *,
    known_safe: bool,
) -> list[str]:
    """Drop standard ERC-20 / Ownable surfaces when known-safe."""
    if not known_safe:
        return movers
    standard = {
        "transfer", "transferfrom", "approve", "mint", "burn", "burnfrom",
        "increaseallowance", "decreaseallowance", "permit",
        "transferownership", "renounceownership", "pause", "unpause",
    }
    return [m for m in movers if m.lower() not in standard]


def known_safe_summary(meta: dict[str, Any]) -> dict[str, Any]:
    ok, reasons = is_known_safe(
        address=str(meta.get("address") or ""),
        contract_name=meta.get("contract_name"),
        source=str(meta.get("source") or ""),
        implementation=meta.get("implementation"),
    )
    return {"known_safe": ok, "reasons": reasons}
