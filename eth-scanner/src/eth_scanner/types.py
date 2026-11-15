"""Shared types for the Ethereum-only invariant scanner.

Automation emits *buckets*, never a human verdict. Heuristic flags are
leads, never findings. See docs/ETH_SWEEP_SCANNING_REFERENCE.md §6.0.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Literal, Optional

Chain = Literal["ethereum"]
SrcConfidence = Literal["high", "med", "low"]
IrConfidence = Literal["high", "med", "low"]
Bucket = Literal[
    "lane-a-cool",
    "lane-b-queue",
    "manual-review",
    "human-no-candidate",
    "human-yes-candidate",
]
TargetStatus = Literal["pending", "running", "done", "skipped", "error"]
ArtifactKind = Literal["source", "decompile", "ir", "report"]
HypothesisStatus = Literal["HOLDS", "BROKEN", "OPEN"]
AuthHeuristic = Literal[
    "PRESENT",
    "WEAK",
    "MISSING",
    "MISSING(internal — check callers)",
    "SELF-SCOPED?",
    "AMBIGUOUS",
]

BUCKETS: tuple[Bucket, ...] = (
    "lane-a-cool",
    "lane-b-queue",
    "manual-review",
    "human-no-candidate",
    "human-yes-candidate",
)

# §6.0 heat ranking only — never used to auto-dismiss.
DEFAULT_HEAT_THRESHOLD = 3
DEFAULT_TVL_FLOOR_USD = 10_000.0
# Live funds floor (native + major ERC-20s / vault AUM) checked before ingest.
DEFAULT_MIN_FUNDS_USD = 2_000.0
MAX_HEAT = 12
# Fallback spacing only. Live pace is ETH_SCANNER_ETHERSCAN_PER_SECOND (default 5)
# times ETH_SCANNER_ETHERSCAN_PACE (default 0.95) — just under the free-tier cap.
DEFAULT_ETHERSCAN_INTERVAL_S = 0.4


def to_plain(obj: Any) -> Any:
    """JSON-friendly dump for dataclasses / lists / dicts."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: to_plain(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_plain(v) for v in obj]
    return obj


@dataclass
class Target:
    address: str
    chain: Chain = "ethereum"
    bytecode_hash: Optional[str] = None
    bytecode: Optional[str] = None
    tvl_usd: Optional[float] = None
    status: TargetStatus = "pending"
    has_code: bool = True
    # Prior closed-no hashes for this exact bytecode (S0 dedupe).
    prior_closed_no: bool = False
    prior_verdict: Optional[str] = None
    # Rate-limit / proxy-impl fetch failure — NOT a confirmed empty EOA.
    ingest_incomplete: bool = False
    ingest_incomplete_reason: Optional[str] = None
    # Live funds probe (first step). Manual TVL override still wins when set.
    funds_usd: Optional[float] = None
    funds_breakdown: list[dict[str, Any]] = field(default_factory=list)
    funds_status: Optional[str] = None  # ok | unknown | skipped | override
    funds_checked_at: Optional[str] = None
    # Recent-deployment discovery metadata (prefer newest first).
    deployed_block: Optional[int] = None
    deployed_at: Optional[str] = None  # ISO8601 UTC
    discovery_source: Optional[str] = None  # rpc-create | etherscan-verified | fallback


@dataclass
class SourceArtifact:
    """Verified source or decompile text. Decompile is never proof."""

    kind: ArtifactKind
    language: str  # solidity | vyper | unknown
    content: str
    src_confidence: SrcConfidence
    verified_match: Optional[str] = None  # exact | partial | none
    compiler: Optional[str] = None
    contract_name: Optional[str] = None
    is_proxy: bool = False
    implementation: Optional[str] = None
    tool: Optional[str] = None  # etherscan | heimdall | panoramix | local | none
    notes: list[str] = field(default_factory=list)


@dataclass
class FunctionIR:
    name: str
    visibility: str
    line: int
    end: int = 0
    file: str = ""
    modifiers: list[str] = field(default_factory=list)
    fund_signals: list[str] = field(default_factory=list)
    auth_signals: list[str] = field(default_factory=list)
    auth_heuristic: str = "AMBIGUOUS"
    accounting_touched: list[str] = field(default_factory=list)
    is_value_mover: bool = False
    exposed: bool = False
    # custody | erc20-standard | wrap-unwrap — ranking only, never a verdict.
    role: str = ""


@dataclass
class IRDocument:
    functions: list[FunctionIR] = field(default_factory=list)
    ir_confidence: IrConfidence = "low"
    src_confidence: SrcConfidence = "low"
    language: str = "unknown"
    lift_failed: bool = False
    lift_tool: str = "heuristic"
    notes: list[str] = field(default_factory=list)
    surface: dict[str, Any] = field(default_factory=dict)
    weird_signals: list[str] = field(default_factory=list)
    pattern_leads: list[dict[str, Any]] = field(default_factory=list)
    accounting_hits: list[dict[str, Any]] = field(default_factory=list)
    external_calls: list[dict[str, Any]] = field(default_factory=list)
    abi_mismatch_hint: bool = False
    fork_family: Optional[str] = None
    unpack_failed: bool = False
    contract_class: str = "unknown"
    scope: str = "unknown"  # in-scope | demoted-token | demoted-passthrough | utility | unknown
    scope_signals: list[str] = field(default_factory=list)
    function_names: list[str] = field(default_factory=list)


@dataclass
class StageTrace:
    stage: str
    decision: str
    reason: str
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class Hypothesis:
    invariant: str  # I1–I8
    text: str
    status: HypothesisStatus = "OPEN"
    score: int = 0
    axes: dict[str, int] = field(default_factory=dict)
    locus: Optional[str] = None  # file:function:line if known
    notes: str = ""


@dataclass
class FunnelResult:
    bucket: Optional[Bucket]
    dropped: bool
    drop_reason: Optional[str]
    heat: int
    src_confidence: SrcConfidence
    ir_confidence: IrConfidence
    stage_trace: list[StageTrace] = field(default_factory=list)
    pattern_leads: list[dict[str, Any]] = field(default_factory=list)
    hypotheses: list[Hypothesis] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    value_movers: list[str] = field(default_factory=list)
    contract_class: str = "unknown"
    scope: str = "unknown"
    scope_signals: list[str] = field(default_factory=list)
    funds_usd: Optional[float] = None
    funds_breakdown: list[dict[str, Any]] = field(default_factory=list)
    funds_status: Optional[str] = None
    funds_checked_at: Optional[str] = None
    # Evidence-based ranking (pattern leads never contribute heat).
    invariant_results: list[dict[str, Any]] = field(default_factory=list)
    heat_breakdown: dict[str, Any] = field(default_factory=dict)
    known_safe: bool = False
    contract_name: Optional[str] = None
    # Advanced engines: Slither/Mythril/clone leads vs read-only confirmed findings.
    engine_leads: list[dict[str, Any]] = field(default_factory=list)
    confirmed_findings: list[dict[str, Any]] = field(default_factory=list)
    engine_timing: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_plain(self)
