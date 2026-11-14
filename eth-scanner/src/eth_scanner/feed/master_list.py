"""Load the versioned master candidate list.

Scan order is drain_probability descending, then tier ascending, then
estimated USD held descending, then DefiLlama ETH TVL descending.
Duplicate addresses in the base file keep the higher-priority row.

A later hand-ranked tranche can be dropped in beside the base file as
``hand_ranked_candidates.json`` (same row shape). Those rows are appended,
and a repeated address replaces the base row. The combined list is sorted
again. No rebuild of master_candidates.json is required.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

# Optional overlay. Absent until a hand-analyzed tranche is committed.
HAND_RANKED_FILENAME = "hand_ranked_candidates.json"


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
    # List prior in [0, 1]. This is not the 0–100 live drain score.
    drain_probability: float = 0.0
    contract_class: str = ""

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
            "drain_probability": self.drain_probability,
            "contract_class": self.contract_class,
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
    """Lower tuple sorts first: higher drain prior, then tier, USD, TVL."""
    tvl = float(row.defillama_eth_tvl or 0.0)
    return (
        -float(row.drain_probability or 0.0),
        row.tier,
        -float(row.est_usd_held or 0.0),
        -tvl,
        row.rank,
        row.address,
    )


def list_fingerprint(candidates: list[MasterCandidate]) -> str:
    """Identity of the ordered feed. A new ranking changes the hash and resets cursors."""
    blob = "\n".join(
        "%.6f|%s|%s|%.2f|%.2f|%s" % (
            float(c.drain_probability or 0.0),
            c.tier,
            c.address,
            float(c.est_usd_held or 0.0),
            float(c.defillama_eth_tvl or 0.0),
            c.rank,
        )
        for c in candidates
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


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
        drain_probability=_as_float(raw.get("drain_probability")),
        contract_class=str(raw.get("contract_class") or raw.get("category") or ""),
    )


def _read_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        raw_rows = payload.get("candidates") or payload.get("rows") or []
    elif isinstance(payload, list):
        raw_rows = payload
    else:
        raise ValueError("master candidate list must be a JSON array or {candidates:[]}")
    return [row for row in raw_rows if isinstance(row, dict)]


def _dedupe(raw_rows: list[dict[str, Any]]) -> dict[str, MasterCandidate]:
    best: dict[str, MasterCandidate] = {}
    for raw in raw_rows:
        row = _from_raw(raw)
        if row is None:
            continue
        prev = best.get(row.address)
        if prev is None or _priority(row) < _priority(prev):
            best[row.address] = row
    return best


def load_master_candidates(path: Optional[Path | str] = None) -> list[MasterCandidate]:
    """Unique addresses in scan order (drain probability, then tier, USD, TVL)."""
    src = Path(path) if path else default_master_list_path()
    best = _dedupe(_read_rows(src))
    overlay = src.parent / HAND_RANKED_FILENAME
    if overlay.is_file():
        # Hand rows are authoritative for an address they name, then re-sorted.
        for row in _dedupe(_read_rows(overlay)).values():
            best[row.address] = row
    ordered = list(best.values())
    ordered.sort(key=_priority)
    return ordered
