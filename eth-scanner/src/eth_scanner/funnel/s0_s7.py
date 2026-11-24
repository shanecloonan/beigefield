"""S0–S7 scoring funnel from SWEEP_SCANNING_REFERENCE §6.0.

Cheap stages first. Ambiguity never becomes discard — weak or failed
cheap checks route to `manual-review`, never automated `no` / `skip`.

Never auto-yes. Never auto-no on low IR / decompile confidence.
Heat ranks only; it does not dismiss.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from eth_scanner.heat import evidence_heat, load_heat_weights, should_promote_lane_b
from eth_scanner.heuristics.patterns import detect_fork_family, detect_weird_signals, skim_known_patterns
from eth_scanner.heuristics.scope import FUNDS_AT_RISK_CLASSES, ScopeDecision, classify_scope
from eth_scanner.classify import classify_contract
from eth_scanner.invariants.live import run_live_invariants, summarize_role_flags
from eth_scanner.known_safe import filter_standard_movers, is_known_safe
from eth_scanner.types import (
    DEFAULT_HEAT_THRESHOLD,
    DEFAULT_MIN_FUNDS_USD,
    DEFAULT_TVL_FLOOR_USD,
    MAX_HEAT,
    Bucket,
    FunnelResult,
    Hypothesis,
    IRDocument,
    SourceArtifact,
    StageTrace,
    Target,
)


@dataclass
class FunnelConfig:
    heat_threshold: int = DEFAULT_HEAT_THRESHOLD
    tvl_floor_usd: float = DEFAULT_TVL_FLOOR_USD
    min_funds_usd: float = DEFAULT_MIN_FUNDS_USD
    # Unit tests can inject results / skip network.
    skip_live_invariants: bool = False


@dataclass
class FunnelContext:
    target: Target
    artifact: Optional[SourceArtifact] = None
    ir: Optional[IRDocument] = None
    source_text: str = ""
    hypotheses: list[Hypothesis] = field(default_factory=list)
    config: FunnelConfig = field(default_factory=FunnelConfig)
    rpc_url: str = ""
    invariant_results: list[dict[str, Any]] = field(default_factory=list)


def _trace(stage: str, decision: str, reason: str, **extras: Any) -> StageTrace:
    return StageTrace(stage=stage, decision=decision, reason=reason, extras=extras)


def _exposed_movers(ir: IRDocument) -> list[str]:
    """Deduped exposed custody movers (not erc20-standard)."""
    names: list[str] = []
    seen: set[str] = set()
    for fn in ir.functions:
        if fn.is_value_mover and fn.exposed and fn.role != "erc20-standard":
            key = (fn.name or "").lower()
            if key in seen:
                continue
            seen.add(key)
            names.append(fn.name)
    return names


def _erc20_standard_names(ir: Optional[IRDocument]) -> list[str]:
    if ir is None:
        return []
    return [fn.name for fn in ir.functions if fn.role == "erc20-standard" and fn.exposed]


def _auth_for(ir: IRDocument, name: str) -> str:
    for fn in ir.functions:
        if fn.name == name:
            return fn.auth_heuristic
    return "AMBIGUOUS"


def _scope_of(ctx: FunnelContext) -> ScopeDecision:
    ir = ctx.ir
    if ir is not None and ir.contract_class and ir.contract_class != "unknown":
        return ScopeDecision(
            contract_class=ir.contract_class,
            scope=ir.scope or "unknown",
            signals=list(ir.scope_signals or []),
            promote=ir.contract_class in FUNDS_AT_RISK_CLASSES,
        )
    source = ctx.source_text or (ctx.artifact.content if ctx.artifact else "")
    extra = list(ir.function_names) if ir is not None else []
    decision = classify_scope(
        source=source,
        functions=(ir.functions if ir else []),
        extra_names=extra,
        contract_name=(ctx.artifact.contract_name if ctx.artifact else None),
    )
    fine, conf = classify_contract(
        name=(ctx.artifact.contract_name if ctx.artifact else "") or "",
        source=source,
    )
    if conf in {"high", "med"} and fine != "other":
        decision.contract_class = fine
        decision.signals = list(decision.signals) + ["class:%s:%s" % (fine, conf)]
    return decision


def _class_for_live(ctx: FunnelContext, fallback: str) -> str:
    source = ctx.source_text or (ctx.artifact.content if ctx.artifact else "")
    fine, conf = classify_contract(
        name=(ctx.artifact.contract_name if ctx.artifact else "") or "",
        source=source,
    )
    if conf in {"high", "med"} and fine != "other":
        return fine
    return fallback or "other"


def _cap_heat(heat: int) -> int:
    return min(max(0, int(heat)), MAX_HEAT)


def _funds_usd(ctx: FunnelContext) -> Optional[float]:
    """Prefer live funds probe; fall back to manual TVL override on the target."""
    t = ctx.target
    if getattr(t, "funds_usd", None) is not None:
        try:
            return float(t.funds_usd)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            pass
    if t.tvl_usd is not None:
        try:
            return float(t.tvl_usd)
        except (TypeError, ValueError):
            return None
    return None


def run_lane_a(ctx: FunnelContext) -> FunnelResult:
    """S0–S6. Lane A emits a bucket; it never stamps yes/no."""
    notes: list[str] = [
        "Lane A is noise-kill + ranking, not a verdict.",
        "Do Not Auto-Dismiss: low/failed IR or ambiguous cheap checks → manual-review.",
    ]
    traces: list[StageTrace] = []
    src_conf = ctx.artifact.src_confidence if ctx.artifact else "low"
    ir = ctx.ir
    ir_conf = ir.ir_confidence if ir else "low"
    heat = 0
    pattern_leads: list[dict[str, Any]] = []

    # --- S0 Intake gate ----------------------------------------------------
    s0 = _stage_s0(ctx.target)
    traces.append(s0)
    if s0.decision == "drop":
        return FunnelResult(
            bucket=None,
            dropped=True,
            drop_reason=s0.reason,
            heat=0,
            src_confidence=src_conf,
            ir_confidence=ir_conf,
            stage_trace=traces,
            notes=notes + [s0.reason],
        )

    # --- S1 Artifact class -------------------------------------------------
    traces.append(_trace(
        "S1", "tag",
        "src_confidence=%s (never discard on low)" % src_conf,
        src_confidence=src_conf,
        kind=(ctx.artifact.kind if ctx.artifact else "missing"),
        verified_match=(ctx.artifact.verified_match if ctx.artifact else None),
    ))

    source = ctx.source_text or (ctx.artifact.content if ctx.artifact else "")
    funds_usd = _funds_usd(ctx)
    scope_early = _scope_of(ctx)

    # --- Known-safe hard skip (heat 0) — after scope so triage keeps class ---
    early_safe, early_safe_reasons = is_known_safe(
        address=ctx.target.address,
        contract_name=(ctx.artifact.contract_name if ctx.artifact else None),
        source=source,
        implementation=(ctx.artifact.implementation if ctx.artifact else None),
    )
    if early_safe:
        movers_early = _exposed_movers(ir) if ir else []
        traces.append(_trace(
            "S1b", "drop", "known-safe",
            reasons=early_safe_reasons[:6],
            contract_name=(ctx.artifact.contract_name if ctx.artifact else None),
            contract_class=scope_early.contract_class,
            scope=scope_early.scope,
            movers=movers_early,
        ))
        return FunnelResult(
            bucket="lane-a-cool",
            dropped=True,
            drop_reason="known-safe",
            heat=0,
            src_confidence=src_conf,
            ir_confidence=ir_conf,
            stage_trace=traces,
            notes=notes + ["known-safe — heat 0, skipped (%s)" % ",".join(early_safe_reasons[:4])],
            value_movers=movers_early,
            contract_class=scope_early.contract_class,
            scope=scope_early.scope,
            scope_signals=list(scope_early.signals),
            funds_usd=funds_usd,
            heat_breakdown={"funds": 0, "funds_rank": 0, "funds_in_heat": 0, "total": 0},
            known_safe=True,
            contract_name=(ctx.artifact.contract_name if ctx.artifact else None),
            invariant_results=[{
                "id": "known-safe",
                "name": "known-safe library/protocol",
                "status": "held",
                "evidence": ",".join(early_safe_reasons) or "curated",
            }],
        )

    # --- S2 IR confidence --------------------------------------------------
    # Classify scope FIRST, then route analysis failures. Demoted surfaces
    # cool-archive; funds-at-floor venues with failed analysis → try live
    # invariants when the class is already known funds-at-risk, else
    # manual-review. Pattern leads never add heat.
    analysis_failed = (
        ir is None or ir.lift_failed or ir_conf == "low"
        or (ir and ir.unpack_failed) or src_conf == "low"
    )
    # Soft recovery: verified source + in-scope funds class → still run live
    # invariants even when unpack/IR lift failed (e.g. Curve Twocrypto Vyper).
    soft_recover = (
        analysis_failed
        and src_conf == "high"
        and scope_early.contract_class in FUNDS_AT_RISK_CLASSES
        and not scope_early.demoted
        and funds_usd is not None
        and funds_usd >= ctx.config.min_funds_usd
    )
    if analysis_failed and not soft_recover:
        reason = "analysis failed"
        if ir and ir.unpack_failed:
            detail = "unpack_failed"
        elif ir is None or (ir and ir.lift_failed) or ir_conf == "low":
            detail = "ir_failed_or_low"
        else:
            detail = "src_confidence=low"
        if scope_early.demoted or scope_early.contract_class in {"token", "wrap-token", "nft"}:
            traces.append(_trace(
                "S2", "drop", "token-only" if scope_early.contract_class in {"token", "wrap-token", "nft"} else reason,
                detail=detail, ir_confidence=ir_conf, src_confidence=src_conf,
                contract_class=scope_early.contract_class, scope=scope_early.scope,
            ))
            drop_reason = (
                "token-only" if scope_early.contract_class in {"token", "wrap-token", "nft"}
                else "analysis-failed-demoted"
            )
            return FunnelResult(
                bucket="lane-a-cool",
                dropped=True,
                drop_reason=drop_reason,
                heat=0,
                src_confidence=src_conf,
                ir_confidence=ir_conf,
                stage_trace=traces,
                notes=notes + ["Dropped demoted/token surface after analysis failure."],
                contract_class=scope_early.contract_class,
                scope=scope_early.scope,
                scope_signals=list(scope_early.signals),
                funds_usd=funds_usd,
                heat_breakdown={"funds": 0, "funds_rank": 0, "funds_in_heat": 0, "total": 0},
                contract_name=(ctx.artifact.contract_name if ctx.artifact else None),
            )
        if funds_usd is not None and funds_usd >= ctx.config.min_funds_usd:
            traces.append(_trace(
                "S2", "manual-review", reason,
                detail=detail, ir_confidence=ir_conf, src_confidence=src_conf,
                funds_usd=funds_usd,
            ))
            heat, heat_bd = evidence_heat(funds_usd=funds_usd, invariant_results=[], source=source)
            return _done(
                "manual-review", traces, src_conf, ir_conf, heat, notes,
                extra="analysis failed — funds >= floor; needs human read (Do Not Auto-Dismiss).",
                pattern_leads=pattern_leads,
                movers=_exposed_movers(ir) if ir else [],
                scope=scope_early,
                funds_usd=funds_usd,
                heat_breakdown=heat_bd,
            )
        traces.append(_trace(
            "S2", "lane-a-cool", reason,
            detail=detail, funds_usd=funds_usd,
        ))
        return _done(
            "lane-a-cool", traces, src_conf, ir_conf, 0, notes,
            extra="analysis failed with funds below floor / unknown — cool-archive.",
            pattern_leads=pattern_leads,
            movers=_exposed_movers(ir) if ir else [],
            scope=scope_early,
            funds_usd=funds_usd,
        )
    if soft_recover:
        traces.append(_trace(
            "S2", "continue",
            "analysis soft-recover: verified + in-scope %s — run live invariants"
            % scope_early.contract_class,
            ir_confidence=ir_conf,
            unpack_failed=bool(ir and ir.unpack_failed),
            lift_failed=bool(ir and ir.lift_failed),
        ))
        # Jump to live-invariant path with empty movers / injected class.
        inv_rows: list[dict[str, Any]] = []
        if not ctx.config.skip_live_invariants:
            live = run_live_invariants(
                ctx.target.address,
                contract_class=_class_for_live(ctx, scope_early.contract_class),
                rpc_url=ctx.rpc_url or "",
            )
            inv_rows = [r.to_dict() for r in live]
        privileged, eoa_admin = False, False
        if inv_rows:
            from eth_scanner.invariants.live import LiveInvariantResult
            objs = [
                LiveInvariantResult(
                    id=str(r.get("id") or ""),
                    name=str(r.get("name") or ""),
                    status=str(r.get("status") or "unknown"),
                    evidence=str(r.get("evidence") or ""),
                    extras=dict(r.get("extras") or {}),
                )
                for r in inv_rows
            ]
            privileged, eoa_admin = summarize_role_flags(objs)
        weights = load_heat_weights()
        heat, heat_bd = evidence_heat(
            funds_usd=funds_usd,
            invariant_results=inv_rows,
            privileged_callable=privileged,
            eoa_admin=eoa_admin,
            weights=weights,
            source=source,
        )
        promote, why = should_promote_lane_b(
            funds_usd=funds_usd,
            invariant_results=inv_rows,
            privileged_callable=privileged,
            eoa_admin=eoa_admin,
            weights=weights,
        )
        bucket = "lane-b-queue" if promote else "lane-a-cool"
        traces.append(_trace("S5b", "heat", "soft-recover evidence heat=%d" % heat, heat=heat, heat_breakdown=heat_bd))
        traces.append(_trace("S6", bucket, why, heat=heat, funds_usd=funds_usd))
        return _done(
            bucket, traces, src_conf, ir_conf, heat, notes,  # type: ignore[arg-type]
            extra="Soft-recovered after unpack/IR failure; live invariants only. Not a verdict.",
            pattern_leads=pattern_leads,
            movers=_exposed_movers(ir) if ir else [],
            scope=scope_early,
            funds_usd=funds_usd,
            invariant_results=inv_rows,
            heat_breakdown=heat_bd,
            contract_name=(ctx.artifact.contract_name if ctx.artifact else None),
        )
    traces.append(_trace("S2", "continue", "ir_confidence=%s" % ir_conf, ir_confidence=ir_conf, lift_tool=ir.lift_tool))

    # --- S3 Known-pattern skim (high/med IR only) --------------------------
    pattern_leads = list(ir.pattern_leads) or skim_known_patterns(source)
    traces.append(_trace(
        "S3", "leads-only",
        "pattern hits=%d (never a close)" % len(pattern_leads),
        lead_ids=[p.get("id") for p in pattern_leads],
    ))

    # --- S4 Value-mover presence + scope filter ----------------------------
    movers = _exposed_movers(ir)
    erc20_leads = _erc20_standard_names(ir)
    scope = _scope_of(ctx)
    erc20_note = ""
    if erc20_leads:
        erc20_note = (
            " ERC20-standard transfer/approve surfaces %s recorded as leads, "
            "not I1 custody movers." % ",".join(erc20_leads[:12])
        )

    if ctx.target.ingest_incomplete and not movers:
        traces.append(_trace(
            "S4", "manual-review",
            "ingest incomplete; movers unknown (not a confirmed empty surface)",
            incomplete_reason=ctx.target.ingest_incomplete_reason,
        ))
        return _done(
            "manual-review", traces, src_conf, ir_conf, heat, notes,
            extra="Do Not Auto-Dismiss: Etherscan/proxy ingest incomplete — not a no-mover close.",
            pattern_leads=pattern_leads,
            scope=scope,
        )

    if scope.demoted:
        demoted_safe, demoted_safe_reasons = is_known_safe(
            address=ctx.target.address,
            contract_name=(ctx.artifact.contract_name if ctx.artifact else None),
            source=source,
            implementation=(ctx.artifact.implementation if ctx.artifact else None),
        )
        # Token / wrap-token / nft / router: drop — balance dust is not custody.
        drop_token = scope.contract_class in {"token", "wrap-token", "nft", "router", "nft-market"}
        drop_reason = "known-safe" if demoted_safe else ("token-only" if drop_token else "demoted-passthrough")
        traces.append(_trace(
            "S4", "drop",
            drop_reason,
            contract_class=scope.contract_class,
            scope=scope.scope,
            signals=scope.signals,
            erc20_standard=erc20_leads,
            movers=movers,
            known_safe=demoted_safe,
        ))
        traces.append(_trace("S5", "skip", "out-of-scope class — dropped"))
        traces.append(_trace("S6", "drop", "heat 0 — demoted / token-only / known-safe"))
        return FunnelResult(
            bucket="lane-a-cool",
            dropped=True,
            drop_reason=drop_reason,
            heat=0,
            src_confidence=src_conf,
            ir_confidence=ir_conf,
            stage_trace=traces,
            pattern_leads=pattern_leads,
            notes=notes + [
                "Dropped %s (%s). Tokens/wraps/routers/NFTs are not money-at-risk venues; "
                "funds on a token contract are accidental self-balance, not custody. Heat 0."
                % (scope.contract_class, drop_reason)
                + erc20_note
            ],
            value_movers=movers,
            contract_class=scope.contract_class,
            scope=scope.scope,
            scope_signals=list(scope.signals),
            funds_usd=funds_usd,
            heat_breakdown={"funds": 0, "funds_rank": 0, "funds_in_heat": 0, "total": 0},
            known_safe=demoted_safe,
            contract_name=(ctx.artifact.contract_name if ctx.artifact else None),
        )

    if not movers:
        # Live Eigen DelegationManager (`0x3905…f37A`) was a funds-at-risk
        # family with zero lifted movers → human-no-candidate. Prefer keep.
        if (
            scope.contract_class in FUNDS_AT_RISK_CLASSES
            or "diamond-facets-missing" in scope.signals
        ):
            traces.append(_trace(
                "S4", "continue",
                "in-scope %s with no lifted movers — prefer keep (Do Not Auto-Dismiss)"
                % scope.contract_class,
                contract_class=scope.contract_class,
                signals=scope.signals,
                erc20_standard=erc20_leads,
            ))
        elif ir_conf == "high" and src_conf == "high":
            traces.append(_trace(
                "S4", "human-no-candidate",
                "no custody movers + high IR + verified",
                erc20_standard=erc20_leads,
                contract_class=scope.contract_class,
            ))
            traces.append(_trace("S5", "skip", "no custody movers"))
            traces.append(_trace("S6", "skip", "S4 closed as human-no-candidate (still needs human stamp)"))
            return _done(
                "human-no-candidate", traces, src_conf, ir_conf, heat, notes,
                extra="Candidate auto-no only: high IR + verified + no custody movers. Human still stamps no." + erc20_note,
                pattern_leads=pattern_leads,
                scope=scope,
            )
        else:
            traces.append(_trace(
                "S4", "lane-a-cool",
                "no custody movers; IR not high+verified so not a close",
                erc20_standard=erc20_leads,
                contract_class=scope.contract_class,
            ))
            traces.append(_trace("S5", "skip", "no custody movers"))
            traces.append(_trace("S6", "lane-a-cool", "utility / non-custody with usable IR"))
            return _done(
                "lane-a-cool", traces, src_conf, ir_conf, heat, notes,
                extra="No exposed custody movers; absence is only a close when IR is high and source verified." + erc20_note,
                pattern_leads=pattern_leads,
                scope=scope,
            )
    traces.append(_trace(
        "S4", "continue",
        "exposed value movers=%d class=%s" % (len(movers), scope.contract_class),
        movers=movers, contract_class=scope.contract_class, scope=scope.scope,
    ))

    # --- S5 Evidence collection (auth tag + live invariants) ---------------
    # Pattern leads / weird / fork / missing-auth keyword heat contribute ZERO.
    # They only select which invariants to run.
    safe, safe_reasons = is_known_safe(
        address=ctx.target.address,
        contract_name=(ctx.artifact.contract_name if ctx.artifact else None),
        source=source,
        implementation=(ctx.artifact.implementation if ctx.artifact else None),
    )
    if safe:
        movers = filter_standard_movers(movers, known_safe=True)
        notes.append("known-safe surface (%s) — standard movers ignored for ranking" % ",".join(safe_reasons[:4]))

    auth_map: dict[str, str] = {}
    ambiguous_n = 0
    clear_n = 0
    for name in movers:
        auth = _auth_for(ir, name)
        if auth == "SELF-SCOPED?":
            auth = "WEAK"
        auth_map[name] = auth
        if auth == "AMBIGUOUS":
            ambiguous_n += 1
        else:
            clear_n += 1

    # Proxy flag comes from Etherscan Proxy/Implementation fields only.
    is_proxy = bool(ctx.artifact and ctx.artifact.is_proxy)
    impl = ctx.artifact.implementation if ctx.artifact else None
    weird = list(ir.weird_signals) or []
    fork = ir.fork_family
    # Record pattern leads for invariant selection — never as heat.
    traces.append(_trace(
        "S5", "evidence",
        "auth tagged; live invariants next (pattern leads add zero heat)",
        auth=auth_map,
        known_safe=safe,
        is_proxy=is_proxy,
        implementation=impl,
        weird=weird,
        fork_family=fork,
        pattern_lead_ids=[p.get("id") for p in pattern_leads],
    ))

    inv_rows = list(ctx.invariant_results or [])
    if not inv_rows and not ctx.config.skip_live_invariants and not safe:
        live = run_live_invariants(
            ctx.target.address,
            contract_class=_class_for_live(ctx, scope.contract_class),
            rpc_url=ctx.rpc_url or "",
        )
        inv_rows = [r.to_dict() for r in live]
    elif not inv_rows and safe:
        inv_rows = [{
            "id": "known-safe",
            "name": "known-safe library/protocol",
            "status": "held",
            "evidence": ",".join(safe_reasons) or "curated",
        }]

    privileged, eoa_admin = False, False
    if inv_rows:
        # Rebuild lightweight objects for summarize_role_flags
        from eth_scanner.invariants.live import LiveInvariantResult
        objs = [
            LiveInvariantResult(
                id=str(r.get("id") or ""),
                name=str(r.get("name") or ""),
                status=str(r.get("status") or "unknown"),
                evidence=str(r.get("evidence") or ""),
                extras=dict(r.get("extras") or {}),
            )
            for r in inv_rows
        ]
        privileged, eoa_admin = summarize_role_flags(objs)

    weights = load_heat_weights()
    heat, heat_bd = evidence_heat(
        funds_usd=funds_usd,
        invariant_results=inv_rows,
        privileged_callable=privileged,
        eoa_admin=eoa_admin,
        weights=weights,
        source=source,
    )
    traces.append(_trace(
        "S5b", "heat",
        "evidence heat=%d (funds + failed invariants only)" % heat,
        heat=heat,
        heat_breakdown=heat_bd,
        invariant_results=inv_rows,
        privileged_callable=privileged,
        eoa_admin=eoa_admin,
        funds_usd=funds_usd,
    ))

    if ambiguous_n > 0 and clear_n == 0 and funds_usd is not None and funds_usd >= ctx.config.min_funds_usd:
        traces.append(_trace(
            "S5", "manual-review",
            "analysis failed",
            detail="all cheap auth parses are truly ambiguous",
            auth=auth_map, heat=heat,
        ))
        return _done(
            "manual-review", traces, src_conf, ir_conf, heat, notes,
            extra="Ambiguous auth with funds >= floor → manual-review (analysis failed).",
            pattern_leads=pattern_leads,
            movers=movers,
            scope=scope,
            funds_usd=funds_usd,
            invariant_results=inv_rows,
            heat_breakdown=heat_bd,
            known_safe=safe,
        )

    # --- S6 Deep-lane gate (evidence only) ---------------------------------
    # lane-b only if funds >= floor AND (failed invariant OR privileged
    # callable OR EOA admin on >= $100k). Else cool; funds_rank sorts /test.
    # proxy-delegatecall is NOT a promote signal. Funds alone never make heat.
    promote, why = should_promote_lane_b(
        funds_usd=funds_usd,
        invariant_results=inv_rows,
        privileged_callable=privileged,
        eoa_admin=eoa_admin,
        weights=weights,
    )
    if promote:
        traces.append(_trace(
            "S6", "lane-b-queue",
            why,
            heat=heat, funds_usd=funds_usd, contract_class=scope.contract_class,
            invariant_failed=any((r.get("status") or "").lower() == "failed" for r in inv_rows),
        ))
        return _done(
            "lane-b-queue", traces, src_conf, ir_conf, heat, notes,
            extra="Promoted to Lane B on failed invariant / open privilege / EOA admin. Not a finding.",
            pattern_leads=pattern_leads,
            movers=movers,
            scope=scope,
            funds_usd=funds_usd,
            invariant_results=inv_rows,
            heat_breakdown=heat_bd,
            known_safe=safe,
        )

    traces.append(_trace(
        "S6", "lane-a-cool",
        why or "no evidence for lane-b — funds_rank sorts, heat stays 0",
        heat=heat, funds_usd=funds_usd, contract_class=scope.contract_class,
        funds_rank=(heat_bd or {}).get("funds_rank"),
    ))
    return _done(
        "lane-a-cool", traces, src_conf, ir_conf, heat, notes,
        extra="Lane A cool-archive. Heat is evidence-only; funds_usd/funds_rank sort the desk.",
        pattern_leads=pattern_leads,
        movers=movers,
        scope=scope,
        funds_usd=funds_usd,
        invariant_results=inv_rows,
        heat_breakdown=heat_bd,
        known_safe=safe,
    )


def run_lane_b(ctx: FunnelContext) -> FunnelResult:
    """S7 deep invariants. Workers never invent BROKEN from heuristics.

    Routing is still implemented for an injected BROKEN hypothesis so a
    human-verified locus can land in `human-yes-candidate`. Automation
    itself only emits OPEN / HOLDS-shaped leads.
    """
    notes = [
        "Lane B is thoroughness on S6 survivors and manual-review promotions.",
        "Never auto-yes. BROKEN requires an exact locus and a human stamp.",
        "Heuristic flags remain leads, never findings.",
    ]
    traces = list(_prior_or_s7_header(ctx))
    src_conf = ctx.artifact.src_confidence if ctx.artifact else (ctx.ir.src_confidence if ctx.ir else "low")
    ir = ctx.ir
    ir_conf = ir.ir_confidence if ir else "low"
    heat = 0
    movers = _exposed_movers(ir) if ir else []

    if ir is None or ir.lift_failed or ir_conf == "low" or src_conf == "low":
        traces.append(_trace("S7", "manual-review", "low-confidence residual after promotion"))
        return _done(
            "manual-review", traces, src_conf, ir_conf, heat, notes,
            extra="Low IR/src residual → needs-look / manual-review. Not a silent no.",
            hypotheses=list(ctx.hypotheses),
            movers=movers,
            scope=_scope_of(ctx),
        )

    hyps = list(ctx.hypotheses)
    if any(h.status == "BROKEN" for h in hyps):
        broken = [h for h in hyps if h.status == "BROKEN"]
        traces.append(_trace(
            "S7", "human-yes-candidate",
            "BROKEN hypothesis present — human must verify path (no PoC)",
            loci=[h.locus for h in broken],
        ))
        return _done(
            "human-yes-candidate", traces, src_conf, ir_conf, heat, notes,
            extra="Candidate only. Human stamps yes after path verify. Automation never emits verdict yes.",
            hypotheses=hyps,
            movers=movers,
        )

    open_high = [h for h in hyps if h.status == "OPEN" and h.score >= 8]
    if open_high:
        traces.append(_trace("S7", "manual-review", "OPEN hypothesis score>=8", scores=[h.score for h in open_high]))
        return _done(
            "manual-review", traces, src_conf, ir_conf, heat, notes,
            extra="OPEN ≥8 → needs-look. Human six-pass / read.",
            hypotheses=hyps,
            movers=movers,
        )

    if hyps and all(h.status == "HOLDS" for h in hyps) and ir_conf == "high" and src_conf == "high":
        traces.append(_trace("S7", "human-no-candidate", "all HOLDS + high confidence"))
        return _done(
            "human-no-candidate", traces, src_conf, ir_conf, heat, notes,
            extra="High-confidence all-clear after S7. Human still stamps no.",
            hypotheses=hyps,
            movers=movers,
        )

    traces.append(_trace("S7", "manual-review", "residual OPEN or not all HOLDS at high confidence"))
    return _done(
        "manual-review", traces, src_conf, ir_conf, heat, notes,
        extra="Prefer a larger manual bucket over a false no.",
        hypotheses=hyps,
        movers=movers,
    )


def build_hypotheses(ir: IRDocument, tvl_usd: Optional[float] = None) -> list[Hypothesis]:
    """I1–I8 hypothesis stubs from surface IR. Status is OPEN (never BROKEN)."""
    funds_axis = _funds_axis(tvl_usd)
    hyps: list[Hypothesis] = []
    movers = [fn for fn in ir.functions if fn.is_value_mover and fn.exposed]
    for fn in movers:
        auth_axis = {"PRESENT": 0, "WEAK": 2, "SELF-SCOPED?": 2, "AMBIGUOUS": 2}.get(fn.auth_heuristic, 3)
        if fn.auth_heuristic.startswith("MISSING"):
            auth_axis = 3
        novelty = 2 if ir.fork_family else 1
        if ir.src_confidence == "low" or ir.abi_mismatch_hint:
            novelty = 3
        reach = 2
        score = min(12, funds_axis + reach + auth_axis + novelty)
        hyps.append(Hypothesis(
            invariant="I1",
            text="Value mover `%s` auth heuristic=%s (lead only)." % (fn.name, fn.auth_heuristic),
            status="OPEN",
            score=score,
            axes={"funds": funds_axis, "reachability": reach, "auth": auth_axis, "novelty": novelty},
            locus="%s:%s:%d" % (fn.file or "source", fn.name, fn.line),
            notes="Confirm beneficiary and debited account bind to the caller by reading. Not a finding.",
        ))
    if ir.accounting_hits:
        hyps.append(Hypothesis(
            invariant="I2",
            text="Accounting hotspot(s) present — check paired ledger updates.",
            status="OPEN",
            score=min(12, funds_axis + 1 + 1 + 1),
            axes={"funds": funds_axis, "reachability": 1, "auth": 1, "novelty": 1},
            notes="Heuristic surface only.",
        ))
    if ir.external_calls:
        hyps.append(Hypothesis(
            invariant="I3",
            text="External/low-level call sites — list trusted inputs by hand.",
            status="OPEN",
            score=min(12, funds_axis + 1 + 1 + 1),
            axes={"funds": funds_axis, "reachability": 1, "auth": 1, "novelty": 1},
        ))
    if ir.src_confidence == "low" or ir.abi_mismatch_hint:
        hyps.append(Hypothesis(
            invariant="I4",
            text="Source/decompile or proxy-implementation mismatch hint (I4).",
            status="OPEN",
            score=min(12, funds_axis + 2 + 2 + 3),
            axes={"funds": funds_axis, "reachability": 2, "auth": 2, "novelty": 3},
            notes="Deployed == reviewed is UNKNOWN until a human closes it.",
        ))
    if ir.fork_family:
        hyps.append(Hypothesis(
            invariant="I5",
            text="Fork-family hint `%s` — diff movers vs canonical by hand." % ir.fork_family,
            status="OPEN",
            score=min(12, funds_axis + 1 + 1 + 2),
            axes={"funds": funds_axis, "reachability": 1, "auth": 1, "novelty": 2},
        ))
    hyps.append(Hypothesis(
        invariant="I6",
        text="Privilege monotonicity: trace owner/role/upgrade writes (read-only).",
        status="OPEN",
        score=min(12, funds_axis + 1 + 1 + 1),
        axes={"funds": funds_axis, "reachability": 1, "auth": 1, "novelty": 1},
    ))
    if "first-deposit-edge" in ir.weird_signals:
        hyps.append(Hypothesis(
            invariant="I7",
            text="Empty-supply / first-deposit edge hint — reachable today?",
            status="OPEN",
            score=min(12, funds_axis + 2 + 2 + 2),
            axes={"funds": funds_axis, "reachability": 2, "auth": 2, "novelty": 2},
        ))
    if movers and ir.external_calls:
        hyps.append(Hypothesis(
            invariant="I8",
            text="Cross-function sequencing among value movers (describe in prose; do not script).",
            status="OPEN",
            score=min(12, funds_axis + 1 + 1 + 1),
            axes={"funds": funds_axis, "reachability": 1, "auth": 1, "novelty": 1},
        ))
    return hyps


def _funds_axis(tvl_usd: Optional[float]) -> int:
    if tvl_usd is None:
        return 1
    if tvl_usd <= 0:
        return 0
    if tvl_usd < 10_000:
        return 1
    if tvl_usd <= 1_000_000:
        return 2
    return 3


def _stage_s0(target: Target) -> StageTrace:
    if getattr(target, "chain", "ethereum") != "ethereum":
        return _trace("S0", "drop", "non-ethereum chain (this environment is Ethereum-only)", chain=target.chain)
    if not target.has_code and target.ingest_incomplete:
        return _trace(
            "S0", "keep",
            "ingest incomplete — not a confirmed empty EOA",
            ingest_incomplete=True,
            incomplete_reason=target.ingest_incomplete_reason,
        )
    if not target.has_code:
        return _trace("S0", "drop", "empty EOA / zero-code", has_code=False, tvl_usd=target.tvl_usd)
    if target.prior_closed_no and target.bytecode_hash:
        return _trace(
            "S0", "drop",
            "exact duplicate bytecode already closed no",
            bytecode_hash=target.bytecode_hash,
        )
    if target.prior_verdict == "needs-look" and target.bytecode_hash:
        return _trace("S0", "keep", "duplicate-hash needs-look is not dropped", bytecode_hash=target.bytecode_hash)
    return _trace("S0", "keep", "intake ok", address=target.address, bytecode_hash=target.bytecode_hash)


def _prior_or_s7_header(ctx: FunnelContext) -> list[StageTrace]:
    return [_trace("S7", "start", "deep invariant pass (I1–I8 leads)", address=ctx.target.address)]


def _done(
    bucket: Bucket,
    traces: list[StageTrace],
    src_conf: str,
    ir_conf: str,
    heat: int,
    notes: list[str],
    extra: str = "",
    pattern_leads: Optional[list[dict[str, Any]]] = None,
    hypotheses: Optional[list[Hypothesis]] = None,
    movers: Optional[list[str]] = None,
    scope: Optional[ScopeDecision] = None,
    funds_usd: Optional[float] = None,
    invariant_results: Optional[list[dict[str, Any]]] = None,
    heat_breakdown: Optional[dict[str, Any]] = None,
    known_safe: bool = False,
    contract_name: Optional[str] = None,
) -> FunnelResult:
    n = list(notes)
    if extra:
        n.append(extra)
    # Cool-archive ranks by funds_rank in heat_breakdown — funds never become heat.
    if heat_breakdown is None and funds_usd is not None and bucket == "lane-a-cool":
        heat, heat_breakdown = evidence_heat(
            funds_usd=funds_usd,
            invariant_results=invariant_results or [],
        )
    if known_safe:
        heat = 0
        if heat_breakdown is not None:
            heat_breakdown = dict(heat_breakdown)
            heat_breakdown["total"] = 0
            heat_breakdown["funds_in_heat"] = 0
            heat_breakdown["gated_leads"] = 0
            heat_breakdown["gated_lead_ids"] = []
    return FunnelResult(
        bucket=bucket,
        dropped=False,
        drop_reason=None,
        heat=_cap_heat(heat),
        src_confidence=src_conf,  # type: ignore[arg-type]
        ir_confidence=ir_conf,  # type: ignore[arg-type]
        stage_trace=traces,
        pattern_leads=pattern_leads or [],
        hypotheses=hypotheses or [],
        notes=n,
        value_movers=movers or [],
        contract_class=scope.contract_class if scope else "unknown",
        scope=scope.scope if scope else "unknown",
        scope_signals=list(scope.signals) if scope else [],
        funds_usd=funds_usd,
        invariant_results=list(invariant_results or []),
        heat_breakdown=dict(heat_breakdown or {}),
        known_safe=known_safe,
        contract_name=contract_name,
    )
