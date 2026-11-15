"""Pick one verified mainnet contract for the random phase. Read-only.

Etherscan v2 has no list-verified-contracts action, and internal-transaction
listing is API Pro. This draws a recent block, takes contracts that emitted
an ERC-20/721 Transfer, and keeps the first address whose source is verified.
Calls go through ``EtherscanClient`` so they share the per-key pacer and the
daily ledger. Nothing here broadcasts a transaction.
"""

from __future__ import annotations

import random
from typing import Any, Optional

from eth_scanner.ingest.etherscan import EtherscanClient, IngestError, parse_source_result
from eth_scanner.ingest.quota import DailyBudgetExhausted

# keccak256("Transfer(address,address,uint256)")
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
DEFAULT_LOOKBACK = 7_200
DEFAULT_MIN_AGE = 20
DEFAULT_MAX_BLOCKS = 2
DEFAULT_MAX_SOURCE_CHECKS = 4


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, int):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(text, 16) if text.startswith("0x") else int(text)
    except (TypeError, ValueError):
        return None


def block_number(client: EtherscanClient) -> int:
    result = client._get({"module": "proxy", "action": "eth_blockNumber"})
    number = _as_int(result)
    if number is None or number <= 0:
        raise IngestError("etherscan did not return a block number")
    return number


def transfer_emitters(client: EtherscanClient, block: int) -> list[str]:
    result = client._get({
        "module": "logs",
        "action": "getLogs",
        "fromBlock": str(block),
        "toBlock": str(block),
        "topic0": TRANSFER_TOPIC,
    })
    rows = result if isinstance(result, list) else []
    seen: set[str] = set()
    out: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        addr = str(row.get("address") or "").strip().lower()
        if len(addr) == 42 and addr.startswith("0x") and addr not in seen:
            seen.add(addr)
            out.append(addr)
    return out


def verified_name(client: EtherscanClient, address: str) -> Optional[str]:
    raw = client._get({"module": "contract", "action": "getsourcecode", "address": address})
    art = parse_source_result(address, raw)
    if art.kind != "source" or not (art.content or "").strip():
        return None
    return art.contract_name or ""


def sample_verified_contract(
    client: EtherscanClient,
    *,
    skip: Optional[set[str]] = None,
    rng: Optional[random.Random] = None,
    lookback_blocks: int = DEFAULT_LOOKBACK,
    min_age_blocks: int = DEFAULT_MIN_AGE,
    max_blocks: int = DEFAULT_MAX_BLOCKS,
    max_source_checks: int = DEFAULT_MAX_SOURCE_CHECKS,
) -> Optional[str]:
    """Return one verified address, or None when this draw finds none.

    ``DailyBudgetExhausted`` propagates so the scan loop can stop.
    """
    skip = {a.lower() for a in (skip or set())}
    rng = rng or random.Random()
    head = block_number(client)
    newest = max(1, head - max(0, int(min_age_blocks)))
    oldest = max(1, newest - max(1, int(lookback_blocks)))
    checks = 0
    for _ in range(max(1, int(max_blocks))):
        if checks >= max_source_checks:
            break
        block = rng.randint(oldest, newest)
        try:
            emitters = transfer_emitters(client, block)
        except DailyBudgetExhausted:
            raise
        except IngestError:
            continue
        rng.shuffle(emitters)
        for addr in emitters:
            if addr in skip:
                continue
            if checks >= max_source_checks:
                break
            checks += 1
            try:
                name = verified_name(client, addr)
            except DailyBudgetExhausted:
                raise
            except IngestError:
                continue
            if name is None:
                continue
            return addr
    return None
