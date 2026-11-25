"""Chain names and address forms.

Ethereum normalization stays in the store. This module only adds the
shared name and the Solana form, and it lets a later chain pass a
non-empty address through without an enum edit.
"""

from __future__ import annotations

from typing import Any

DEFAULT_CHAIN = "ethereum"
SUPPORTED_CHAINS = ("ethereum", "bsc", "arbitrum", "base", "optimism", "polygon", "solana")

_ALIASES = {
    "": "ethereum",
    "eth": "ethereum",
    "mainnet": "ethereum",
    "bnb": "bsc",
    "bnb-chain": "bsc",
    "binance": "bsc",
    "bsc": "bsc",
    "arb": "arbitrum",
    "arbitrum-one": "arbitrum",
    "arbitrum": "arbitrum",
    "base": "base",
    "op": "optimism",
    "optimism": "optimism",
    "matic": "polygon",
    "polygon": "polygon",
    "pol": "polygon",
}

_SOLANA_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def normalize_chain(value: object) -> str:
    """Blank and the ETH aliases stay ethereum. Known EVM aliases collapse.

    Any other non-empty name is kept, so a later chain does not need an edit.
    """
    text = str(value or "").strip().lower()
    if text in _ALIASES:
        return _ALIASES[text]
    return text or DEFAULT_CHAIN


def row_chain(row: dict[str, Any] | None) -> str:
    if not isinstance(row, dict):
        return DEFAULT_CHAIN
    return normalize_chain(row.get("chain"))


def normalize_solana_address(addr: str) -> str:
    """A 32-byte base58 account. Case is significant, so it is not lowercased."""
    text = (addr or "").strip()
    if not text or any(ch not in _SOLANA_ALPHABET for ch in text):
        raise ValueError("invalid Solana address")
    decoded = _b58decode(text)
    if len(decoded) != 32:
        raise ValueError("invalid Solana address")
    return text


def _b58decode(text: str) -> bytes:
    number = 0
    for ch in text:
        number = number * 58 + _SOLANA_ALPHABET.index(ch)
    pad = 0
    for ch in text:
        if ch != "1":
            break
        pad += 1
    if number == 0:
        body = b""
    else:
        body = number.to_bytes((number.bit_length() + 7) // 8, "big")
    return b"\x00" * pad + body
