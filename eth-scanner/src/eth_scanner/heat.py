"""Evidence-based heat — ranking signal only when rules fail.

Funds are a *sort key*, never heat. Pattern leads (weak auth, proxy-delegatecall,
fork family, erc4626-rounding, etc.) contribute ZERO heat.

Heat comes only from evidence:
  (a) invariant checks that actually fail (held/unknown → 0)
  (b) privileged function callable by an outsider
  (c) single-EOA admin over eoa_admin_min_usd
  (d) Slither/Mythril/clone leads ONLY when a read-only corroboration confirms
  (e) allowlisted static detectors (static_evidence). High-confidence
      funds rules weigh the most. Generic, informational, and admin-gated
      hits stay at 0.
  (f) a bytecode surface. EIP-7702 delegation and a value-moving clone
      weigh 2 (`surface_evidence`). Selector recovery alone weighs 0.

A generic Slither/Mythril hit is still a lead (0 heat). An allowlisted
high-confidence detector is the static_evidence component, not a verdict.
Never auto-yes.
"""

from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class HeatWeights:
    """Configurable multipliers. Override via ETH_SCANNER_HEAT_* env vars."""

    # log10(1 + funds_usd) * funds_log_scale — ranking/sort only, NOT heat
    funds_log_scale: float = 1.5
    funds_cap: int = 8
    # per failed invariant (held → 0, unknown → 0)
    failed_invariant: int = 3
    failed_invariant_cap: int = 9
    # privileged call from random EOA that did NOT revert
    privileged_callable: int = 4
    # EOA admin/owner/upgrader on a contract holding >= eoa_admin_min_usd
    eoa_admin: int = 3
    eoa_admin_min_usd: float = 100_000.0
    # per corroborated engine/clone lead (Slither-only → 0)
    corroborated_lead: int = 3
    corroborated_lead_cap: int = 6
    # absolute heat ceiling
    max_heat: int = 12
    # lane-b still needs funds >= floor (from settings); this is the promote bar
    # when evidence fires (failed invariant / privileged / eoa admin)
    min_funds_for_lane_b: float = 100.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_DEFAULT = HeatWeights()


def load_heat_weights() -> HeatWeights:
    def _f(name: str, default: float) -> float:
        raw = os.environ.get(name)
        if raw is None or raw.strip() == "":
            return default
        try:
            return float(raw)
        except ValueError:
            return default

    def _i(name: str, default: int) -> int:
        return int(round(_f(name, float(default))))

    return HeatWeights(
        funds_log_scale=_f("ETH_SCANNER_HEAT_FUNDS_LOG_SCALE", _DEFAULT.funds_log_scale),
        funds_cap=_i("ETH_SCANNER_HEAT_FUNDS_CAP", _DEFAULT.funds_cap),
        failed_invariant=_i("ETH_SCANNER_HEAT_FAILED_INVARIANT", _DEFAULT.failed_invariant),
        failed_invariant_cap=_i("ETH_SCANNER_HEAT_FAILED_INVARIANT_CAP", _DEFAULT.failed_invariant_cap),
        privileged_callable=_i("ETH_SCANNER_HEAT_PRIVILEGED_CALLABLE", _DEFAULT.privileged_callable),
        eoa_admin=_i("ETH_SCANNER_HEAT_EOA_ADMIN", _DEFAULT.eoa_admin),
        eoa_admin_min_usd=_f("ETH_SCANNER_HEAT_EOA_ADMIN_MIN_USD", _DEFAULT.eoa_admin_min_usd),
        corroborated_lead=_i("ETH_SCANNER_HEAT_CORROBORATED_LEAD", _DEFAULT.corroborated_lead),
        corroborated_lead_cap=_i("ETH_SCANNER_HEAT_CORROBORATED_LEAD_CAP", _DEFAULT.corroborated_lead_cap),
        max_heat=_i("ETH_SCANNER_HEAT_MAX", _DEFAULT.max_heat),
        min_funds_for_lane_b=_f("ETH_SCANNER_MIN_FUNDS_USD", _DEFAULT.min_funds_for_lane_b),
    )


def funds_rank(funds_usd: Optional[float], weights: Optional[HeatWeights] = None) -> int:
    """Log-scaled funds *ranking* key. Not heat. None/unknown → 0."""
    w = weights or load_heat_weights()
    if funds_usd is None or funds_usd <= 0:
        return 0
    score = math.log10(1.0 + float(funds_usd)) * w.funds_log_scale
    return min(w.funds_cap, max(0, int(round(score))))


# Back-compat alias — callers that still say funds_heat mean the ranking key.
funds_heat = funds_rank


def _harness_noise(row: dict[str, Any]) -> bool:
    """Setup/constructor failures are harness noise, not a live rule failure."""
    blob = " ".join([
        str(row.get("id") or ""),
        str(row.get("name") or ""),
        str(row.get("evidence") or ""),
    ]).lower()
    return any(tok in blob for tok in ("setup()", "setup", "constructor", "deploy("))


def _counts_as_live_failure(row: dict[str, Any]) -> bool:
    if (row.get("status") or "").lower() != "failed":
        return False
    if _harness_noise(row):
        return False
    # Engine/fuzz/symbolic output is evidence only until a live eth_call fails.
    source = str(row.get("source") or "").lower()
    if source in {"fuzz", "symbolic", "halmos", "slither", "mythril", "semgrep", "aderyn"}:
        return False
    return True


def invariant_heat(
    results: list[dict[str, Any]],
    weights: Optional[HeatWeights] = None,
) -> int:
    """Only *failed* live rules add heat. held/unknown/engine output add zero.

    The same rule id is counted once so a duplicated fuzz row cannot stack.
    """
    w = weights or load_heat_weights()
    seen: set[str] = set()
    n_failed = 0
    for row in results:
        if not _counts_as_live_failure(row):
            continue
        key = str(row.get("id") or row.get("name") or "")
        if key in seen:
            continue
        seen.add(key)
        n_failed += 1
    return min(w.failed_invariant_cap, n_failed * w.failed_invariant)


_EOA_FACT = "eoa-admin"
_PRIV_FACT = "privileged-callable"
_FACT_IDS = {
    "admin-eoa": _EOA_FACT,
    "admin-eoa-confirmed": _EOA_FACT,
    "eoa-admin": _EOA_FACT,
    "admin-privileged-open": _PRIV_FACT,
    "admin-uninit-impl": _PRIV_FACT,
    "admin-uninit-impl-lead": _PRIV_FACT,
    "privileged-callable": _PRIV_FACT,
}


def evidence_fact(row: dict[str, Any]) -> str:
    """One name for one fact, so a flag and a confirmed row cannot both add heat."""
    extras = row.get("extras") if isinstance(row.get("extras"), dict) else {}
    explicit = str(row.get("fact") or extras.get("fact") or "")
    if explicit in {_EOA_FACT, _PRIV_FACT}:
        return explicit
    lead = str(row.get("lead_id") or row.get("id") or "")
    return _FACT_IDS.get(lead, lead)


def stronger_holds(results: list[dict[str, Any]]) -> set[str]:
    """A passing symbolic access-control check contradicts a weaker call probe."""
    held: set[str] = set()
    for row in results or []:
        if str(row.get("status") or "").lower() != "held":
            continue
        source = str(row.get("source") or row.get("tool") or "").lower()
        if source not in {"symbolic", "halmos"}:
            continue
        blob = " ".join([str(row.get("id") or ""), str(row.get("name") or "")]).lower()
        if "access_control" in blob or "access-control" in blob:
            held.add(_PRIV_FACT)
    return held


def corroborated_heat(
    confirmed: list[dict[str, Any]],
    weights: Optional[HeatWeights] = None,
    *,
    skip_facts: Optional[set[str]] = None,
) -> int:
    """Only *confirmed* engine/clone corroborations add heat. Leads alone → 0.

    Each fact is counted once. Facts already applied as eoa or privileged
    heat are skipped.
    """
    w = weights or load_heat_weights()
    n = 0
    seen: set[str] = set()
    skip = set(skip_facts or ())
    for c in confirmed:
        if not c.get("confirmed"):
            continue
        method = str(c.get("method") or "").lower()
        # Engine output adds zero heat. A live eth_call confirmation still counts.
        if method in {"fuzz", "symbolic", "slither", "mythril", "semgrep", "aderyn", "halmos", "none", "source"}:
            if not c.get("live_confirmed"):
                continue
        fact = evidence_fact(c)
        if fact in skip:
            continue
        key = fact
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        n += 1
    return min(w.corroborated_lead_cap, n * w.corroborated_lead)


_SHAPE_LEADS = ("share-balance", "spot-price", "reentrancy")


def shape_lead_names(source: str = "", extra: Optional[list[str]] = None) -> list[str]:
    """The three recall leads present on a source or already stored on a row."""
    names: list[str] = []
    if source:
        from eth_scanner.benchmark.leads import benchmark_lead_names
        for name in benchmark_lead_names(source):
            if name not in names:
                names.append(name)
    for name in extra or []:
        if name in _SHAPE_LEADS and name not in names:
            names.append(name)
    return names


def fork_backed(records: Optional[list[dict[str, Any]]]) -> bool:
    """A conservation failure above the value-delta threshold."""
    if not records:
        return False
    from eth_scanner.engines.conservation import high_confidence
    return bool(high_confidence(list(records)))


def gated_lead_points(
    leads: list[str],
    *,
    backing: int,
    conservation: Optional[list[dict[str, Any]]] = None,
    taken: Optional[set[str]] = None,
    weights: Optional[HeatWeights] = None,
) -> tuple[int, list[str]]:
    """Heat for shape leads. Bare leads score 0. Each lead name counts once."""
    w = weights or load_heat_weights()
    names: list[str] = []
    for name in leads:
        if name in _SHAPE_LEADS and name not in names:
            names.append(name)
    if not names:
        return 0, []
    if int(backing or 0) <= 0 and not fork_backed(conservation):
        return 0, names
    skip = set(taken or ())
    counted = [name for name in names if name not in skip]
    points = min(w.corroborated_lead_cap, len(counted) * w.corroborated_lead)
    return points, names


def evidence_heat(
    *,
    funds_usd: Optional[float],
    invariant_results: list[dict[str, Any]],
    privileged_callable: bool = False,
    eoa_admin: bool = False,
    corroborated: Optional[list[dict[str, Any]]] = None,
    weights: Optional[HeatWeights] = None,
    source: str = "",
    conservation: Optional[list[dict[str, Any]]] = None,
    lead_ids: Optional[list[str]] = None,
    static_findings: Optional[list[Any]] = None,
    corpus_findings: Optional[list[Any]] = None,
    clone_match: Optional[dict[str, Any]] = None,
    bytecode_surface: Optional[dict[str, Any]] = None,
    source_record: Optional[dict[str, Any]] = None,
    external_suite: Optional[dict[str, Any]] = None,
    weird_tokens: Optional[dict[str, Any]] = None,
    unprotected_value: bool = False,
    unverified_proxy: bool = False,
    deployed_at: Optional[str] = None,
    now: Any = None,
) -> tuple[int, dict[str, Any]]:
    """Compose heat from evidence only. Funds are ranking metadata, not heat."""
    w = weights or load_heat_weights()
    rank = funds_rank(funds_usd, w)
    inv = invariant_heat(invariant_results, w)
    contradicted = stronger_holds(invariant_results)
    priv_on = bool(privileged_callable) and _PRIV_FACT not in contradicted
    priv = w.privileged_callable if priv_on else 0
    eoa = 0
    if eoa_admin and funds_usd is not None and funds_usd >= w.eoa_admin_min_usd:
        eoa = w.eoa_admin
    skip = set(contradicted)
    if priv_on:
        skip.add(_PRIV_FACT)
    if eoa:
        skip.add(_EOA_FACT)
    corr = corroborated_heat(list(corroborated or []), w, skip_facts=skip)
    taken = set(skip)
    for item in corroborated or []:
        if item.get("confirmed"):
            taken.add(evidence_fact(item))
    gated, lead_names = gated_lead_points(
        shape_lead_names(source, lead_ids),
        backing=inv + priv + eoa + corr,
        conservation=conservation,
        taken=taken,
        weights=w,
    )
    static_points = 0
    static_rows: list[dict[str, Any]] = []
    if static_findings:
        from eth_scanner.logic.static_norm import score_static
        scored = score_static(list(static_findings))
        static_points = int(scored["points"])
        static_rows = list(scored["rows"])
    corpus_points = 0
    corpus_rows: list[dict[str, Any]] = []
    if corpus_findings:
        from eth_scanner.logic.static_norm import score_static
        scored = score_static(list(corpus_findings))
        taken_rules = {str(row.get("rule") or "") for row in static_rows if row.get("counted")}
        kept: list[dict[str, Any]] = []
        for row in scored["rows"]:
            item = dict(row)
            if item.get("rule") in taken_rules:
                item["counted"] = False
                item["weight_applied"] = 0
            elif item.get("counted"):
                room = 6 - corpus_points
                applied = min(int(item.get("weight_applied") or 0), room)
                item["weight_applied"] = applied
                item["counted"] = applied > 0
                corpus_points += applied
            kept.append(item)
        corpus_rows = kept
    clone_points = 0
    if isinstance(clone_match, dict):
        try:
            clone_points = max(0, int(clone_match.get("weight") or 0))
        except (TypeError, ValueError):
            clone_points = 0
        clone_points = min(3, clone_points)
    surface_points = 0
    surface_show = False
    surface_overlap = ""
    surface_selectors = 0
    if isinstance(bytecode_surface, dict):
        from eth_scanner.logic.bytecode_surface import score_surface
        scored_surface = score_surface(bytecode_surface)
        surface_points = int(scored_surface["points"])
        surface_show = bool(scored_surface["show"])
        surface_overlap = str(scored_surface["overlap"] or "")
        surface_selectors = int(scored_surface["selectors"])
    layout_show = False
    metadata_show = False
    layout_slots = 0
    compiler = ""
    if isinstance(source_record, dict):
        slots = source_record.get("storage_layout") or []
        meta = source_record.get("metadata") if isinstance(source_record.get("metadata"), dict) else {}
        layout_slots = len(slots) if isinstance(slots, list) else 0
        layout_show = layout_slots > 0
        metadata_show = bool(meta.get("present"))
        compiler = str(meta.get("compiler") or "")[:80]
    from eth_scanner.logic.priority import ADMIN_ONLY_CAP, priority_points
    priority = priority_points(
        unprotected_value=unprotected_value,
        unverified_proxy=unverified_proxy,
        funds_usd=funds_usd,
        deployed_at=deployed_at,
        now=now,
    )
    unprotected_points = int(priority["unprotected_evidence"])
    proxy_points = int(priority["proxy_evidence"])
    fresh_points = int(priority["fresh_evidence"])
    fork = fork_backed(conservation)
    substantive = (
        inv + priv + corr + static_points + corpus_points + clone_points
        + unprotected_points + proxy_points + fresh_points + surface_points
    )
    admin_capped = bool(eoa and gated and substantive == 0 and not fork)
    if admin_capped:
        gated = min(gated, max(0, ADMIN_ONLY_CAP - eoa))
    failed_ids = {
        str(row.get("id") or "")
        for row in invariant_results or []
        if str(row.get("status") or "") == "failed"
    }
    sequence = bool(failed_ids & {
        "erc4626-asset-shortfall",
        "share-price-monotonic",
        "profit-attacker-balance",
    })
    oracle = any(
        name.startswith("profit-spot")
        or name.startswith("profit-chainlink")
        or name.startswith("profit-oracle")
        or "oracle" in name
        for name in failed_ids
    )
    total = min(w.max_heat, substantive + eoa + gated)
    from eth_scanner.drain import score_drain
    drain = score_drain(
        funds_usd=funds_usd,
        invariant_results=list(invariant_results or []),
        privileged_callable=privileged_callable,
        eoa_admin=eoa_admin,
    )
    breakdown = {
        # "funds" kept for UI sort; explicitly not part of total heat.
        "funds": rank,
        "funds_rank": rank,
        "funds_in_heat": 0,
        "invariants_failed": inv,
        "privileged_callable": priv,
        "privileged_confidence": 0 if _PRIV_FACT in contradicted else (1 if priv_on else 0),
        "eoa_admin": eoa,
        "corroborated_leads": corr,
        "gated_leads": gated,
        "gated_lead_ids": lead_names,
        "static_evidence": static_points,
        "corpus_evidence": corpus_points,
        "clone_evidence": clone_points,
        "surface_evidence": surface_points,
        "bytecode_surface": surface_show,
        "surface_selectors": surface_selectors,
        "surface_overlap": surface_overlap,
        "storage_layout": layout_show,
        "storage_slots": layout_slots,
        "source_metadata": metadata_show,
        "compiler": compiler,
        "erc4626_suite": bool(isinstance(external_suite, dict) and external_suite.get("erc4626")),
        "crytic_properties": bool(isinstance(external_suite, dict) and external_suite.get("crytic")),
        "weird_tokens": bool(isinstance(weird_tokens, dict) and weird_tokens.get("ran")),
        "unprotected_evidence": unprotected_points,
        "proxy_evidence": proxy_points,
        "fresh_evidence": fresh_points,
        "admin_capped": admin_capped,
        "sequence": sequence,
        "oracle": oracle,
        "contradictions": sorted(contradicted),
        "total": total,
        "drain_probability": drain["drain_probability"],
        "profit_invariant_broke": drain["profit_invariant_broke"],
        "drain_band": drain["band"],
        "drain_reason": drain["reason"],
        "weights": w.to_dict(),
    }
    if static_rows:
        breakdown["static_findings"] = static_rows
    if corpus_rows:
        breakdown["corpus_findings"] = corpus_rows
    if isinstance(clone_match, dict) and clone_match.get("kind") not in (None, "", "none"):
        breakdown["clone_match"] = {
            "id": str(clone_match.get("id") or ""),
            "kind": str(clone_match.get("kind") or ""),
            "similarity": clone_match.get("similarity"),
            "runtime_hash": str(clone_match.get("runtime_hash") or ""),
        }
    return total, breakdown


def should_promote_lane_b(
    *,
    funds_usd: Optional[float],
    invariant_results: list[dict[str, Any]],
    privileged_callable: bool = False,
    eoa_admin: bool = False,
    corroborated: Optional[list[dict[str, Any]]] = None,
    weights: Optional[HeatWeights] = None,
) -> tuple[bool, str]:
    """lane-b-queue only with funds floor + real evidence."""
    w = weights or load_heat_weights()
    funds = float(funds_usd) if funds_usd is not None else 0.0
    if funds < w.min_funds_for_lane_b:
        return False, "funds below floor for lane-b"
    from eth_scanner.drain import is_profit_break
    profit = [r for r in invariant_results if is_profit_break(r)]
    if profit:
        return True, "profit invariant broke: %s" % (profit[0].get("id") or "profit")
    if privileged_callable:
        return True, "privileged function callable by arbitrary address"
    return False, "no simulated profit path — accounting quirks stay low"
