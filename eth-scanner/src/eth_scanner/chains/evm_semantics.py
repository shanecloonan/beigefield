"""Chain-specific facts that must not be read as Ethereum.

Arbitrum's ``eth_blockNumber`` is the L2 head. The block field
``l1BlockNumber`` is the L1 block that sequenced it. The NUMBER opcode
is that L1 value, and ``ArbSys.arbBlockNumber`` at ``0x64`` is the L2
value. A header without ``l1BlockNumber`` stays unknown.

Precompiles differ. BNB Chain does not have ArbSys. PancakeSwap and
Venus name matches are evidence only and add no heat.
"""

from __future__ import annotations

from typing import Any, Optional

from eth_scanner.chains.evm import evm_chain
from eth_scanner.chains.registry import normalize_chain

# Ethereum Istanbul/Byzantium range. 0x0a (point evaluation) is not assumed.
COMMON_PRECOMPILES = {
    "0x0000000000000000000000000000000000000001": "ecrecover",
    "0x0000000000000000000000000000000000000002": "sha256",
    "0x0000000000000000000000000000000000000003": "ripemd160",
    "0x0000000000000000000000000000000000000004": "identity",
    "0x0000000000000000000000000000000000000005": "modexp",
    "0x0000000000000000000000000000000000000006": "ecadd",
    "0x0000000000000000000000000000000000000007": "ecmul",
    "0x0000000000000000000000000000000000000008": "ecpairing",
    "0x0000000000000000000000000000000000000009": "blake2f",
}

# Addresses from the Arbitrum precompile reference. Disabled entries are omitted.
ARBITRUM_PRECOMPILES = {
    "0x0000000000000000000000000000000000000064": "ArbSys",
    "0x0000000000000000000000000000000000000065": "ArbInfo",
    "0x0000000000000000000000000000000000000066": "ArbAddressTable",
    "0x0000000000000000000000000000000000000068": "ArbFunctionTable",
    "0x0000000000000000000000000000000000000069": "ArbosTest",
    "0x000000000000000000000000000000000000006b": "ArbOwnerPublic",
    "0x000000000000000000000000000000000000006c": "ArbGasInfo",
    "0x000000000000000000000000000000000000006d": "ArbAggregator",
    "0x000000000000000000000000000000000000006e": "ArbRetryableTx",
    "0x000000000000000000000000000000000000006f": "ArbStatistics",
    "0x0000000000000000000000000000000000000070": "ArbOwner",
    "0x0000000000000000000000000000000000000071": "ArbWasm",
    "0x0000000000000000000000000000000000000072": "ArbWasmCache",
    "0x00000000000000000000000000000000000000ff": "ArbDebug",
}

# OP-stack L1 block precompile, present on Base.
BASE_PRECOMPILES = {
    "0x4200000000000000000000000000000000000015": "L1Block",
}

ARBSYS = "0x0000000000000000000000000000000000000064"


def precompiles(chain: str) -> dict[str, str]:
    name = normalize_chain(chain)
    evm_chain(name)
    found = dict(COMMON_PRECOMPILES)
    if name == "arbitrum":
        found.update(ARBITRUM_PRECOMPILES)
    elif name in {"base", "optimism"}:
        found.update(BASE_PRECOMPILES)
    return found


def is_precompile(chain: str, address: str) -> bool:
    return _norm(address) in precompiles(chain)


def interpret_block(chain: str, block: Any) -> dict[str, Any]:
    """Explain one header. Missing L1 data stays unknown. Heat is 0."""
    name = normalize_chain(chain)
    evm_chain(name)
    header = block if isinstance(block, dict) else {}
    if isinstance(header.get("result"), dict):
        header = header["result"]
    head = _hex_int(header.get("number"))
    report: dict[str, Any] = {
        "chain": name,
        "heat_contribution": 0,
        "head": head,
        "l1_block": None,
        "l1_source": "unknown",
        "degraded": head is None,
    }
    if name == "arbitrum":
        report["head_kind"] = "l2"
        l1 = _hex_int(header.get("l1BlockNumber"))
        report["l1_block"] = l1
        report["l1_source"] = "l1BlockNumber" if l1 is not None else "unknown"
        report["number_opcode"] = "l1"
        report["arb_block_number_precompile"] = ARBSYS
        report["note"] = (
            "eth_blockNumber is the L2 head. l1BlockNumber is the sequencing L1 block. "
            "The NUMBER opcode follows that L1 block. ArbSys.arbBlockNumber at 0x64 is the L2 block."
        )
        if l1 is None:
            report["degraded"] = True
        return report
    if name in {"base", "optimism"}:
        report["head_kind"] = "l2"
        report["l1_source"] = "L1Block-precompile"
        report["l1_precompile"] = "0x4200000000000000000000000000000000000015"
        report["note"] = (
            "eth_blockNumber is the L2 head. The L1 block is the OP-stack L1Block precompile, "
            "not the block number field."
        )
        return report
    report["head_kind"] = "chain"
    report["l1_source"] = "not-an-l2"
    report["note"] = "This chain's block number is its own head. It is not an L2 block."
    return report


def scan_bsc_forks(source: str) -> list[dict[str, Any]]:
    """Name-level PancakeSwap and Venus flags. They add no heat."""
    text = source or ""
    lowered = text.lower()
    found: list[dict[str, Any]] = []
    pancake = any(token in lowered for token in ("pancakepair", "pancakerouter", "pancakeFactory".lower(), "pancakelibrary"))
    if not pancake and "9975" in text and "getreserves" in lowered:
        pancake = True
    if pancake:
        found.append(_flag(
            "pancake-fork",
            "Source names a PancakeSwap pair, router, factory, or the 9975 fee constant.",
        ))
    venus = "venus" in lowered or "vbep20" in lowered or ("vtoken" in lowered and "borrow" in lowered)
    if venus:
        found.append(_flag(
            "venus-fork",
            "Source names Venus, VBep20, or a VToken borrow surface.",
        ))
    return found


def _flag(rule: str, detail: str) -> dict[str, Any]:
    return {
        "rule": rule,
        "detail": detail,
        "evidence_only": True,
        "defensive_only": True,
        "heat_contribution": 0,
    }


def _norm(address: str) -> str:
    text = (address or "").strip().lower()
    if text.startswith("0x") and len(text) < 42:
        text = "0x" + text[2:].rjust(40, "0")
    return text


def _hex_int(value: Any) -> Optional[int]:
    if isinstance(value, int):
        return value
    text = str(value or "").strip().lower()
    if not text.startswith("0x"):
        return None
    try:
        return int(text, 16)
    except ValueError:
        return None
