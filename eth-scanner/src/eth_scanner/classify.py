"""Classify a master-list contract so live checks and engines can specialize.

Uses verified source, name, DefiLlama category, and forked_from. Selectors are
optional 4-byte hints. Confidence is high, med, or low. Unknown stays generic.
"""

from __future__ import annotations

from typing import Optional

CLASSES = (
    "erc4626-vault",
    "compound-lending",
    "aave-lending",
    "uniswap-amm",
    "custom-amm",
    "cdp",
    "bridge",
    "staking-lst",
    "options-vault",
    "privacy-pool",
    "allocator",
    "other",
)

# Slither detector focus per class. Unknown uses the full default set.
ENGINE_CONFIG = {
    "erc4626-vault": {"slither_detect": "erc20-interface,reentrancy-eth,arbitrary-send-eth,unprotected-upgrade", "fuzz_template": "vault"},
    "allocator": {"slither_detect": "arbitrary-send-eth,reentrancy-eth,unprotected-upgrade", "fuzz_template": "vault"},
    "options-vault": {"slither_detect": "reentrancy-eth,arbitrary-send-eth,locked-ether", "fuzz_template": "vault"},
    "compound-lending": {"slither_detect": "reentrancy-eth,oracle-price,unprotected-upgrade", "fuzz_template": "lending"},
    "aave-lending": {"slither_detect": "reentrancy-eth,oracle-price,unprotected-upgrade", "fuzz_template": "lending"},
    "uniswap-amm": {"slither_detect": "reentrancy-eth,incorrect-equality,locked-ether", "fuzz_template": "amm"},
    "custom-amm": {"slither_detect": "reentrancy-eth,incorrect-equality,locked-ether", "fuzz_template": "amm"},
    "cdp": {"slither_detect": "oracle-price,reentrancy-eth,arbitrary-send-eth", "fuzz_template": "cdp"},
    "bridge": {"slither_detect": "arbitrary-send-eth,unprotected-upgrade,suicidal", "fuzz_template": "bridge"},
    "staking-lst": {"slither_detect": "reentrancy-eth,arbitrary-send-eth,locked-ether", "fuzz_template": "staking"},
    "privacy-pool": {"slither_detect": "reentrancy-eth,suicidal", "fuzz_template": "generic"},
    "other": {"slither_detect": "all", "fuzz_template": "generic"},
}


def engine_config_for_class(contract_class: str) -> dict[str, str]:
    return dict(ENGINE_CONFIG.get(contract_class) or ENGINE_CONFIG["other"])


def classify_contract(
    *,
    name: str = "",
    source: str = "",
    category: str = "",
    forked_from: str = "",
    selectors: Optional[list[str]] = None,
) -> tuple[str, str]:
    blob = " ".join([
        name or "",
        (source or "")[:12000],
        category or "",
        forked_from or "",
        " ".join(selectors or []),
    ]).lower()
    name_l = (name or "").lower().replace(" ", "")
    fork = (forked_from or "").lower()
    cat = (category or "").lower()

    def hit(*needles: str) -> bool:
        return any(n.lower() in blob for n in needles)

    # Order matters: more specific families before generic vaults.
    if hit("bentobox", "dodo", "clipper", "pmm") or "dodo" in fork:
        return "custom-amm", "high" if hit("bentobox", "dodo", "clipper") else "med"
    if hit("uniswapv4", "univ4", "beforeSwap", "afterSwap".lower()) or "v4" in fork and "uni" in fork:
        return "uniswap-amm", "high" if "hook" in blob or "poolmanager" in blob else "med"
    if hit("uniswapv3", "univ3", "slot0", "liquidity()") or "uniswap v3" in fork or "uniswap-v3" in fork:
        return "uniswap-amm", "high"
    if hit("uniswapv2", "getreserves", "klast") or "uniswap v2" in fork or "uniswap-v2" in fork:
        return "uniswap-amm", "high" if "getreserves" in blob else "med"
    if hit("comptroller", "ctoken", "borrowrate", "exchangerateStored".lower()) or "compound" in fork:
        return "compound-lending", "high" if hit("comptroller", "ctoken") else "med"
    if hit("pooladdressesprovider", "lendingpool", "aave") or "aave" in fork:
        return "aave-lending", "high" if "aave" in blob else "med"
    if hit("privacy", "shielded", "zk-pool", "semaphore") or "privacy" in cat:
        return "privacy-pool", "med"
    if hit("ribbon", "theta vault", "opentradecall", "option") or "options" in cat or "perps" in cat:
        return "options-vault", "high" if hit("ribbon", "theta") else "med"
    if hit("bridge", "escrow", "messenger", "inbox") or "bridge" in cat or "canonical bridge" in cat:
        return "bridge", "high" if hit("escrow", "bridge") else "med"
    if hit("cdp", "collateralratio", "vaultmanager") or cat in {"cdp", "algo-stables", "stablecoin"}:
        return "cdp", "med"
    if hit("eigen", "restake", "lst", "withdrawalqueue") or "liquid staking" in cat or "restaking" in cat:
        return "staking-lst", "high" if hit("eigen", "lst", "steth") else "med"
    if hit("staking", "rewardrate", "totalstaked") or cat == "staking":
        return "staking-lst", "med"
    if hit("allocator", "curator", "rolemanager") or "allocator" in cat:
        return "allocator", "med"
    if hit("erc4626", "totalassets", "converttoassets", "previewredeem") or "yield" in cat or "vault" in name_l:
        conf = "high" if hit("totalassets", "converttoassets") else "med"
        return "erc4626-vault", conf
    if "lending" in cat:
        return "compound-lending", "low"
    if "dex" in cat or "amm" in cat:
        return "custom-amm", "low"
    return "other", "low"
