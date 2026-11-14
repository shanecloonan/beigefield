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
import re
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
    evidence_note: str = ""

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
            "evidence_note": self.evidence_note,
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


def _drain_prior(value: Any) -> float:
    """Accept a 0–1 prior or a 0–100 hand score. Both sort on the 0–1 scale."""
    score = _as_float(value)
    if score > 1.0:
        score = score / 100.0
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return score


def _slug_for(raw: dict[str, Any], protocol: str) -> str:
    slug = str(raw.get("slug") or "").strip()
    if slug:
        return slug
    return re.sub(r"[^a-z0-9]+", "-", protocol.lower()).strip("-")


def _from_raw(raw: dict[str, Any]) -> Optional[MasterCandidate]:
    addr = str(raw.get("address") or "").strip().lower()
    if not addr.startswith("0x"):
        addr = "0x" + addr if addr else ""
    if len(addr) != 42 or any(c not in "0123456789abcdef" for c in addr[2:]):
        return None
    tier = _as_int(raw.get("tier"), 99) if raw.get("tier") not in (None, "") else 99
    if tier < 1:
        tier = 99
    protocol = str(raw.get("protocol") or "")
    held = raw.get("est_usd_held")
    if held in (None, ""):
        held = raw.get("funds_usd")
    return MasterCandidate(
        address=addr,
        protocol=protocol,
        slug=_slug_for(raw, protocol),
        category=str(raw.get("category") or ""),
        est_usd_held=_as_float(held),
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
        drain_probability=_drain_prior(raw.get("drain_probability")),
        contract_class=str(raw.get("contract_class") or raw.get("category") or ""),
        evidence_note=str(raw.get("evidence_note") or ""),
    )


def _with_hand_review(base: MasterCandidate, hand: MasterCandidate) -> MasterCandidate:
    """Hand review wins. Fields the hand row leaves blank stay from the base row."""
    return MasterCandidate(
        address=hand.address,
        protocol=hand.protocol or base.protocol,
        slug=hand.slug or base.slug,
        category=hand.category or base.category,
        est_usd_held=hand.est_usd_held if hand.est_usd_held else base.est_usd_held,
        candidate_reason=hand.candidate_reason or base.candidate_reason,
        tier=base.tier if hand.tier >= 99 else hand.tier,
        rank=base.rank if hand.rank >= 10**9 else hand.rank,
        label=hand.label or base.label,
        source=hand.source or base.source,
        verified_contract=hand.verified_contract or base.verified_contract,
        defillama_eth_tvl=hand.defillama_eth_tvl or base.defillama_eth_tvl,
        audits=hand.audits or base.audits,
        forked_from=hand.forked_from or base.forked_from,
        proxy_implementation=hand.proxy_implementation or base.proxy_implementation,
        proxy_admin=hand.proxy_admin or base.proxy_admin,
        drain_probability=hand.drain_probability,
        contract_class=hand.contract_class or base.contract_class,
        evidence_note=hand.evidence_note or base.evidence_note,
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
        # Any later tranche uses the same filename and the same merge.
        for row in _dedupe(_read_rows(overlay)).values():
            prev = best.get(row.address)
            best[row.address] = row if prev is None else _with_hand_review(prev, row)
    ordered = list(best.values())
    ordered.sort(key=_priority)
    return ordered
