"""Load the versioned master candidate list.

Order is tier ascending, then estimated USD held descending, then rank.
Duplicate addresses keep the higher-priority row. Read-only file IO.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


def default_master_list_path() -> Path:
    env = (os.environ.get("ETH_SCANNER_MASTER_LIST") or "").strip()
    if env:
        return Path(env)
    # eth-scanner/src/eth_scanner/feed/master_list.py → eth-scanner/data/
    here = Path(__file__).resolve()
    return here.parents[3] / "data" / "master_candidates.json"


@dataclass(frozen=True)
class MasterCandidate:
    address: str
    protocol: str
    slug: str
    category: str
    est_usd_held: float
    candidate_reason: str
    tier: int
    rank: int
    label: str = ""
    source: str = ""
    verified_contract: bool = False
    defillama_eth_tvl: Optional[float] = None
    audits: str = ""
    forked_from: Optional[str] = None
    proxy_implementation: Optional[str] = None
    proxy_admin: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "protocol": self.protocol,
            "slug": self.slug,
            "category": self.category,
            "est_usd_held": self.est_usd_held,
            "candidate_reason": self.candidate_reason,
            "tier": self.tier,
            "rank": self.rank,
            "label": self.label,
            "source": self.source,
            "verified_contract": self.verified_contract,
            "defillama_eth_tvl": self.defillama_eth_tvl,
            "audits": self.audits,
            "forked_from": self.forked_from,
            "proxy_implementation": self.proxy_implementation,
            "proxy_admin": self.proxy_admin,
        }


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _priority(row: MasterCandidate) -> tuple:
    """Lower tuple sorts first: tier, then more USD, then rank, then address."""
    return (row.tier, -row.est_usd_held, row.rank, row.address)


def _from_raw(raw: dict[str, Any]) -> Optional[MasterCandidate]:
    addr = str(raw.get("address") or "").strip().lower()
    if not addr.startswith("0x"):
        addr = "0x" + addr if addr else ""
    if len(addr) != 42 or any(c not in "0123456789abcdef" for c in addr[2:]):
        return None
    tier = _as_int(raw.get("tier"), 99)
    if tier < 1:
        tier = 99
    return MasterCandidate(
        address=addr,
        protocol=str(raw.get("protocol") or ""),
        slug=str(raw.get("slug") or ""),
        category=str(raw.get("category") or ""),
        est_usd_held=_as_float(raw.get("est_usd_held")),
        candidate_reason=str(raw.get("candidate_reason") or ""),
        tier=tier,
        rank=_as_int(raw.get("rank"), 10**9),
        label=str(raw.get("label") or ""),
        source=str(raw.get("source") or ""),
        verified_contract=bool(raw.get("verified_contract") or raw.get("etherscan_verified")),
        defillama_eth_tvl=_as_float(raw.get("defillama_eth_tvl"), default=0.0) or None,
        audits=str(raw.get("audits") or ""),
        forked_from=(str(raw["forked_from"]) if raw.get("forked_from") else None),
        proxy_implementation=(
            str(raw["proxy_implementation"]) if raw.get("proxy_implementation") else None
        ),
        proxy_admin=(str(raw["proxy_admin"]) if raw.get("proxy_admin") else None),
    )


def load_master_candidates(path: Optional[Path | str] = None) -> list[MasterCandidate]:
    """Unique Ethereum addresses in scan order (tier, then USD)."""
    src = Path(path) if path else default_master_list_path()
    payload = json.loads(src.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        raw_rows = payload.get("candidates") or payload.get("rows") or []
    elif isinstance(payload, list):
        raw_rows = payload
    else:
        raise ValueError("master candidate list must be a JSON array or {candidates:[]}")

    best: dict[str, MasterCandidate] = {}
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        row = _from_raw(raw)
        if row is None:
            continue
        prev = best.get(row.address)
        if prev is None or _priority(row) < _priority(prev):
            best[row.address] = row
    ordered = list(best.values())
    ordered.sort(key=_priority)
    return ordered
