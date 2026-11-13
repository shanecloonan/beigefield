"""Clone / fork-family fingerprinting against known-vulnerable code.

Strong *lead* only — never heat until a read-only corroboration confirms.
Fingerprints: bytecode hash, normalized function selectors + skeleton hash,
fuzzy source markers, curated DeFiHackLabs / public-audit dataset.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

from eth_scanner.research.keccak import selector4

# Built-in markers (always available even if dataset file missing).
KNOWN_BAD_SOURCE_MARKERS: tuple[tuple[str, str, str], ...] = (
    ("compound-ctoken-fork", "high", r"\bCErc20(?:Immutable)?\b|\bCToken\b.*\bcomptroller\b"),
    ("uniswap-v2-pair-fork", "med", r"UniswapV2Pair|MINIMUM_LIQUIDITY\s*=\s*10\*\*3"),
    ("erc4626-inflation-prone", "high", r"function\s+deposit\s*\([^)]*\)[^{]*\{[^}]*totalSupply\s*\(\s*\)\s*==\s*0"),
    ("unprotected-initializer", "crit", r"function\s+initialize\s*\([^)]*\)[^{]*public(?![^{]*initializer)"),
    ("openzeppelin-upgradeable-missing-disable", "high", r"_disableInitializers\s*\("),
    ("proxy-admin-takeover", "high", r"function\s+changeAdmin\s*\([^)]*\)[^{]*public(?![^{]*only)"),
)

KNOWN_BAD_BYTECODE_HASHES: dict[str, dict[str, str]] = {}

_FN_RX = re.compile(
    r"function\s+(\w+)\s*\(([^)]*)\)",
    re.M,
)


@dataclass
class CloneLead:
    id: str
    kind: str  # bytecode-hash | source-marker | selector-skeleton | dataset
    title: str
    evidence: str
    severity: str = "medium"
    dataset_id: str = ""
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def fingerprint_source(source: str) -> str:
    return hashlib.sha256((source or "").encode("utf-8", errors="replace")).hexdigest()


def extract_selectors(source: str) -> list[str]:
    """Normalized 4-byte selectors from Solidity function signatures in source."""
    out: list[str] = []
    for m in _FN_RX.finditer(source or ""):
        name = m.group(1)
        if name in {"if", "while", "for", "catch", "receive", "fallback"}:
            continue
        args = _normalize_args(m.group(2) or "")
        sig = "%s(%s)" % (name, args)
        try:
            sel = selector4(sig)
        except Exception:  # noqa: BLE001
            continue
        if sel and sel not in out:
            out.append(sel.lower().removeprefix("0x"))
    return out


def skeleton_hash(selectors: list[str]) -> str:
    ordered = sorted({s.lower().removeprefix("0x") for s in selectors if s})
    blob = ",".join(ordered)
    return hashlib.sha256(blob.encode()).hexdigest()


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
            dataset_id=str(meta.get("id") or ""),
            score=1.0,
        ))

    src = source or ""
    name = (contract_name or "").lower()
    for cid, sev, pat in KNOWN_BAD_SOURCE_MARKERS:
        if cid == "openzeppelin-upgradeable-missing-disable":
            if re.search(r"function\s+initialize\s*\(", src, re.I) and not re.search(
                r"_disableInitializers\s*\(", src
            ):
                leads.append(CloneLead(
                    id="clone-%s" % cid,
                    kind="source-marker",
                    title="Upgradeable initialize without _disableInitializers",
                    evidence="contract=%s missing _disableInitializers near initialize" % (contract_name or "?"),
                    severity=sev,
                    score=0.7,
                ))
            continue
        if re.search(pat, src, re.I | re.S) or (name and re.search(pat, name, re.I)):
            leads.append(CloneLead(
                id="clone-%s" % cid,
                kind="source-marker",
                title="Source resembles known-exploited fork family (%s)" % cid,
                evidence="matched family=%s name=%s" % (cid, contract_name or "—"),
                severity=sev,
                score=0.65,
            ))

    selectors = extract_selectors(src)
    skel = skeleton_hash(selectors) if selectors else ""
    dataset = _load_dataset()
    for entry in dataset:
        score, why = _score_entry(entry, src, selectors, skel)
        if score < 0.55:
            continue
        eid = str(entry.get("id") or "entry")
        leads.append(CloneLead(
            id="clone-dataset-%s" % eid,
            kind="dataset",
            title=str(entry.get("title") or eid),
            evidence="dataset=%s score=%.2f %s" % (eid, score, why),
            severity=str(entry.get("severity") or "high"),
            dataset_id=eid,
            score=score,
        ))

    # Deduplicate by id keeping highest score.
    best: dict[str, CloneLead] = {}
    for lead in leads:
        prev = best.get(lead.id)
        if prev is None or lead.score >= prev.score:
            best[lead.id] = lead
    return list(best.values())


def _normalize_args(raw: str) -> str:
    parts: list[str] = []
    for piece in (raw or "").split(","):
        piece = piece.strip()
        if not piece:
            continue
        toks = piece.split()
        if not toks:
            continue
        # drop location / name — keep type (+ array suffix)
        typ = toks[0]
        for t in toks[1:]:
            if t in {"memory", "calldata", "storage", "payable", "indexed"}:
                continue
            if re.fullmatch(r"[A-Za-z_]\w*", t) and not t.startswith("uint") and not t.startswith("bytes"):
                # likely name
                continue
            if t.startswith("[") or t.endswith("]"):
                typ += t
        parts.append(typ)
    return ",".join(parts)


def _load_dataset() -> list[dict[str, Any]]:
    # clones.py → engines → eth_scanner → src → eth-scanner/
    here = Path(__file__).resolve()
    candidates = [
        here.parents[3] / "data" / "known_vulnerable_clones.json",
        here.parents[2] / "data" / "known_vulnerable_clones.json",
        Path.cwd() / "eth-scanner" / "data" / "known_vulnerable_clones.json",
        Path.cwd() / "data" / "known_vulnerable_clones.json",
    ]
    for path in candidates:
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                entries = data.get("entries") if isinstance(data, dict) else data
                if isinstance(entries, list):
                    return [e for e in entries if isinstance(e, dict)]
            except (OSError, json.JSONDecodeError):
                continue
    return []


def _score_entry(
    entry: dict[str, Any],
    source: str,
    selectors: list[str],
    skel: str,
) -> tuple[float, str]:
    score = 0.0
    bits: list[str] = []
    markers = [str(m).lower() for m in (entry.get("source_markers") or []) if m]
    src_l = (source or "").lower()
    if markers:
        hits = sum(1 for m in markers if m.lower() in src_l)
        frac = hits / max(1, len(markers))
        score += 0.55 * frac
        bits.append("markers=%d/%d" % (hits, len(markers)))
    want = [str(s).lower().removeprefix("0x") for s in (entry.get("selector_skeleton") or []) if s]
    if want and selectors:
        have = set(selectors)
        hit = sum(1 for s in want if s in have)
        frac = hit / max(1, len(want))
        score += 0.45 * frac
        bits.append("selectors=%d/%d" % (hit, len(want)))
    if skel and entry.get("skeleton_hash") and skel == str(entry.get("skeleton_hash")):
        score = max(score, 0.95)
        bits.append("skeleton_hash_exact")
    return score, " ".join(bits)
