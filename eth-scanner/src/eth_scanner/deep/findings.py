"""Normalized engine findings + dedupe + cross-engine agreement.

Aligns with lib/eth-scanner/desk/findings.ts vocabulary. Defensive only:
evidence is sanitized (no calldata / attack sequences). Heat policy:
a single-engine generic detector never adds heat; agreement raises
confidence and marks clusters as heat-eligible only when paired later
with funds + failed-invariant / privileged evidence (Lane A gate).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Optional


FUNDS_AT_RISK_CLASSES = frozenset({
    "reentrancy",
    "access-control",
    "arithmetic",
    "rounding",
    "oracle-manipulation",
    "staleness",
    "unchecked-call",
    "token-integration",
    "signature-replay",
    "delegatecall-storage",
    "bridge-message",
    "dos-locked-funds",
    "mev-slippage",
    "selfdestruct-ether",
    "randomness",
    "invariant-violation",
    "other",
})

# Detectors that are too generic / noisy to contribute heat alone.
GENERIC_RULES = frozenset({
    "naming-convention",
    "solc-version",
    "pragma",
    "unused-state",
    "unused-return",
    "low-level-calls",
    "external-function",
    "constable-states",
    "too-many-digits",
    "boolean-equal",
    "timestamp",
    "block-timestamp",
    "assembly",
    "cache-array-length",
    "costly-operations-loop",
})

_CLASS_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"reentr|swc-107|erc777", re.I), "reentrancy"),
    (re.compile(r"delegatecall|storage[-_ ]?collision|uninitiali[sz]ed|swc-112|swc-109", re.I), "delegatecall-storage"),
    (re.compile(r"signature|ecrecover|replay|malleab|swc-117|permit", re.I), "signature-replay"),
    (re.compile(r"bridge|chain[-_ ]?id|encode[-_ ]?packed|swc-133", re.I), "bridge-message"),
    (re.compile(r"oracle|price[-_ ]?manip|flash[-_ ]?loan|spot[-_ ]?price|twap", re.I), "oracle-manipulation"),
    (re.compile(r"stale|heartbeat|updatedat", re.I), "staleness"),
    (re.compile(r"tx[-_.]?origin|access|owner|onlyowner|unprotected|arbitrary[-_ ]?send|suicidal|missing[-_ ]?auth|swc-105|swc-106|privilege", re.I), "access-control"),
    (re.compile(r"unchecked[-_ ]?(transfer|call|send|lowlevel)|unused[-_ ]?return|swc-104", re.I), "unchecked-call"),
    (re.compile(r"fee[-_ ]?on[-_ ]?transfer|approve|allowance|weird[-_ ]?token|rebasing", re.I), "token-integration"),
    (re.compile(r"overflow|underflow|downcast|arithmetic|swc-101", re.I), "arithmetic"),
    (re.compile(r"divide[-_ ]?before[-_ ]?multiply|precision|rounding|share[-_ ]?inflation", re.I), "rounding"),
    (re.compile(r"slippage|deadline|front[-_ ]?run|sandwich|mev", re.I), "mev-slippage"),
    (re.compile(r"selfdestruct|forced[-_ ]?ether|swc-132", re.I), "selfdestruct-ether"),
    (re.compile(r"random|blockhash|weak[-_ ]?prng|swc-120", re.I), "randomness"),
    (re.compile(r"locked[-_ ]?ether|dos|denial|unbounded|swc-113|swc-128", re.I), "dos-locked-funds"),
    (re.compile(r"invariant|property|solvency|conservation", re.I), "invariant-violation"),
]

MAX_EVIDENCE = 600


@dataclass
class EngineFinding:
    id: str
    engine: str
    rule: str
    title: str
    severity: str  # critical|high|medium|low|info
    confidence: str  # high|medium|low
    funds_class: str
    file: Optional[str] = None
    line: Optional[int] = None
    contract: Optional[str] = None
    function: Optional[str] = None
    evidence: str = ""
    defensive_only: bool = True
    generic: bool = False
    agreement_count: int = 1
    agreement_engines: list[str] = field(default_factory=list)
    cluster_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def sanitize_evidence(raw: Any) -> str:
    s = re.sub(r"\s+", " ", str(raw or "")).strip()
    s = re.sub(r"0x[0-9a-fA-F]{72,}", "0x…[calldata elided]", s)
    if len(s) > MAX_EVIDENCE:
        s = s[: MAX_EVIDENCE - 1] + "…"
    return s


def normalize_severity(raw: Any) -> str:
    s = str(raw or "").strip().lower()
    return {
        "critical": "critical",
        "high": "high",
        "medium": "medium",
        "med": "medium",
        "low": "low",
        "informational": "info",
        "info": "info",
        "optimization": "info",
        "note": "info",
        "warning": "medium",
        "crit": "critical",
    }.get(s, "info")


def normalize_confidence(raw: Any) -> str:
    s = str(raw or "").strip().lower()
    if s in {"high", "medium", "med", "low"}:
        return "medium" if s == "med" else s
    return "low"


def classify_finding(*hints: Optional[str]) -> str:
    text = " ".join(h for h in hints if h)
    for pat, cls in _CLASS_RULES:
        if pat.search(text):
            return cls
    return "other"


def is_generic_rule(rule: str) -> bool:
    r = (rule or "").strip().lower()
    if r in GENERIC_RULES:
        return True
    if any(g in r for g in ("naming", "pragma", "solc-version", "style", "unused-import")):
        return True
    return False


def make_finding(
    *,
    engine: str,
    rule: str,
    title: str,
    severity: Any = "info",
    confidence: Any = "low",
    file: Optional[str] = None,
    line: Optional[int] = None,
    contract: Optional[str] = None,
    function: Optional[str] = None,
    evidence: Any = "",
    class_hint: Optional[str] = None,
) -> EngineFinding:
    funds_class = class_hint if class_hint in FUNDS_AT_RISK_CLASSES else classify_finding(
        class_hint, rule, title, str(evidence or "")
    )
    generic = is_generic_rule(rule)
    rule_family = rule_family_of(rule)
    # Agreement clusters on class + rule family (cross-engine). Location is
    # kept on the finding for humans / within-engine dedupe only.
    cluster = "%s|%s" % (funds_class, rule_family)
    loc = (function or "").lower() or ("%s:%s" % (file or "", line or ""))
    loc = re.sub(r"\s+", "", loc)[:80]
    dedupe = "%s|%s|%s|%s" % (engine, cluster, loc, rule.lower())
    fid = "%s:%s:%s" % (engine, rule, hashlib.sha1(dedupe.encode()).hexdigest()[:10])
    return EngineFinding(
        id=fid,
        engine=engine,
        rule=rule or "unknown",
        title=title or rule or engine,
        severity=normalize_severity(severity),
        confidence=normalize_confidence(confidence),
        funds_class=funds_class,
        file=file,
        line=line,
        contract=contract,
        function=function,
        evidence=sanitize_evidence(evidence),
        generic=generic,
        agreement_engines=[engine],
        cluster_key=cluster,
    )


def rule_family_of(rule: str) -> str:
    """Normalize detector ids across engines (reentrancy-eth ≈ reentrancy ≈ SWC-107)."""
    rule_family = re.sub(r"[^a-z0-9]+", "-", (rule or "").lower()).strip("-")
    if re.match(r"^swc-0*107$", rule_family) or "reentr" in rule_family:
        return "reentrancy"
    if re.match(r"^swc-0*105$", rule_family) or "arbitrary-send" in rule_family or "unprotected" in rule_family:
        return "access-control"
    if re.match(r"^swc-0*101$", rule_family):
        return "arithmetic"
    rule_family = re.sub(r"^(arbitrary-send).*$", "arbitrary-send", rule_family)
    rule_family = re.sub(r"^swc-0*(\d+)$", r"swc-\1", rule_family)
    return rule_family or "unknown"


def dedupe_findings(rows: list[EngineFinding]) -> list[EngineFinding]:
    """Merge identical engine+cluster rows; keep highest severity."""
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    by_id: dict[str, EngineFinding] = {}
    for row in rows:
        prev = by_id.get(row.id)
        if prev is None or order.get(row.severity, 9) < order.get(prev.severity, 9):
            by_id[row.id] = row
    return list(by_id.values())


def apply_agreement(rows: list[EngineFinding]) -> list[EngineFinding]:
    """Group by cluster_key; bump confidence when ≥2 distinct engines agree."""
    buckets: dict[str, list[EngineFinding]] = {}
    for row in rows:
        buckets.setdefault(row.cluster_key or row.id, []).append(row)

    out: list[EngineFinding] = []
    for key, group in buckets.items():
        engines = sorted({g.engine for g in group})
        n = len(engines)
        for g in group:
            g.agreement_count = n
            g.agreement_engines = engines
            if n >= 2 and not g.generic:
                g.confidence = "high"
            elif n >= 2 and g.generic:
                g.confidence = "medium"
            out.append(g)
    return out


def agreement_summary(rows: list[EngineFinding]) -> dict[str, Any]:
    clusters: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = row.cluster_key or row.id
        slot = clusters.setdefault(key, {
            "cluster_key": key,
            "funds_class": row.funds_class,
            "engines": set(),
            "generic": row.generic,
            "max_severity": row.severity,
            "titles": [],
        })
        slot["engines"].add(row.engine)
        slot["generic"] = slot["generic"] and row.generic
        slot["titles"].append(row.title)
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    summarized = []
    for slot in clusters.values():
        engines = sorted(slot["engines"])
        summarized.append({
            "cluster_key": slot["cluster_key"],
            "funds_class": slot["funds_class"],
            "engines": engines,
            "agreement_count": len(engines),
            "generic": slot["generic"],
            "heat_eligible": len(engines) >= 2 and not slot["generic"],
            "titles": list(dict.fromkeys(slot["titles"]))[:5],
        })
    summarized.sort(key=lambda s: (-s["agreement_count"], s["cluster_key"]))
    return {
        "finding_count": len(rows),
        "cluster_count": len(summarized),
        "multi_engine_clusters": sum(1 for s in summarized if s["agreement_count"] >= 2),
        "heat_eligible_clusters": sum(1 for s in summarized if s["heat_eligible"]),
        "clusters": summarized,
        "policy": (
            "Single-engine generic detectors never add heat. "
            "Multi-engine agreement raises confidence only; Lane A evidence gate still required."
        ),
    }


def heat_eligible_clusters(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in (summary.get("clusters") or []) if c.get("heat_eligible")]
