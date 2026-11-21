"""Chain adapters. Ethereum stays the default. New chains register beside it."""

from eth_scanner.chains.registry import (
    DEFAULT_CHAIN,
    SUPPORTED_CHAINS,
    normalize_chain,
    normalize_solana_address,
    row_chain,
)

__all__ = [
    "DEFAULT_CHAIN",
    "SUPPORTED_CHAINS",
    "normalize_chain",
    "normalize_solana_address",
    "row_chain",
]
