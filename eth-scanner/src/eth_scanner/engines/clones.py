"""Clone / fork-family fingerprinting against known-vulnerable code.

Strong *lead* only — never heat until a read-only corroboration confirms.
Bytecode SHA256 and source markers; no exploit payloads.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from typing import Any, Optional

# Curated markers for families that have been repeatedly exploited when forked
# with incomplete auth / unprotected initializers / share-price inflation.
# Defensive identification only — not a vulnerability proof by itself.
KNOWN_BAD_SOURCE_MARKERS: tuple[tuple[str, str, str], ...] = (
    # id, severity hint, regex (case-insensitive)
    ("compound-ctoken-fork", "high", r"\bCErc20(?:Immutable)?\b|\bCToken\b.*\bcomptroller\b"),
    ("uniswap-v2-pair-fork", "med", r"UniswapV2Pair|MINIMUM_LIQUIDITY\s*=\s*10\*\*3"),
    ("erc4626-inflation-prone", "high", r"function\s+deposit\s*\([^)]*\)[^{]*\{[^}]*totalSupply\s*\(\s*\)\s*==\s*0"),
    ("unprotected-initializer", "crit", r"function\s+initialize\s*\([^)]*\)[^{]*public(?![^{]*initializer)"),
    ("openzeppelin-upgradeable-missing-disable", "high", r"_disableInitializers\s*\("),  # presence is good; absence checked separately
    ("proxy-admin-takeover", "high", r"function\s+changeAdmin\s*\([^)]*\)[^{]*public(?![^{]*only)"),
)

# Empty set of exact bytecode hashes for unit tests / future curated list.
# Populate via ops as confirmed exploited clones are catalogued.
KNOWN_BAD_BYTECODE_HASHES: dict[str, dict[str, str]] = {
    # "sha256hex": {"id": "...", "note": "..."},
}


@dataclass
class CloneLead:
    id: str
    kind: str  # bytecode-hash | source-marker
    title: str
    evidence: str
    severity: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def fingerprint_source(source: str) -> str:
    return hashlib.sha256((source or "").encode("utf-8", errors="replace")).hexdigest()


def match_known_bad(
    *,
    bytecode_hash: Optional[str] = None,
    source: str = "",
    contract_name: Optional[str] = None,
) -> list[CloneLead]:
    leads: list[CloneLead] = []
    bh = (bytecode_hash or "").lower().removeprefix("0x")
    if bh and bh in KNOWN_BAD_BYTECODE_HASHES:
        meta = KNOWN_BAD_BYTECODE_HASHES[bh]
        leads.append(CloneLead(
            id="clone-bytecode-%s" % meta.get("id", bh[:12]),
            kind="bytecode-hash",
            title="Bytecode matches known-vulnerable family",
            evidence="bytecode_hash=%s note=%s" % (bh[:16], meta.get("note", "")),
            severity="high",
        ))

    src = source or ""
    name = (contract_name or "").lower()
    for cid, sev, pat in KNOWN_BAD_SOURCE_MARKERS:
        if cid == "openzeppelin-upgradeable-missing-disable":
            # Lead when initialize exists WITHOUT _disableInitializers in same source.
            if re.search(r"function\s+initialize\s*\(", src, re.I) and not re.search(
                r"_disableInitializers\s*\(", src
            ):
                leads.append(CloneLead(
                    id="clone-%s" % cid,
                    kind="source-marker",
                    title="Upgradeable initialize without _disableInitializers",
                    evidence="contract=%s missing _disableInitializers near initialize" % (contract_name or "?"),
                    severity=sev,
                ))
            continue
        if re.search(pat, src, re.I | re.S) or (name and re.search(pat, name, re.I)):
            leads.append(CloneLead(
                id="clone-%s" % cid,
                kind="source-marker",
                title="Source resembles known-exploited fork family (%s)" % cid,
                evidence="matched family=%s name=%s" % (cid, contract_name or "—"),
                severity=sev,
            ))
    return leads
