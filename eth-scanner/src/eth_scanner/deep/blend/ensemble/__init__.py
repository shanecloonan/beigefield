"""Ensemble layers for the Blend gauntlet. Evidence in, one gate for heat."""

from __future__ import annotations

from typing import Any, Optional

from eth_scanner.deep.blend.ensemble.fusion import fuse
from eth_scanner.deep.blend.ensemble.versions import LAYER_ORDER, pins_public


def _witness_hits(witnesses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hits = []
    for row in witnesses:
        delta = int(row.get("caller_profit_delta") or 0)
        if delta <= 0:
            continue
        hits.append({
            "engine": row.get("engine") or "ensemble",
            "rule": row.get("rule") or "no_caller_profit",
            "family": "caller-profit",
            "call_path": row.get("call_path") or "mutant",
            "caller_profit_delta": delta,
            "evidence": "ensemble witness caller_profit_delta=%s" % delta,
            "heat_contribution": 0,
        })
    return hits


def finalize_ensemble(
    report: dict[str, Any],
    *,
    prepared: Optional[dict[str, Any]] = None,
    source: str = "",
    contract_name: str = "",
) -> dict[str, Any]:
    """Attach layers and, if a layer measured caller profit, re-run the one gate.

    Layer blocks always store heat_contribution 0. The gate is
    apply_caller_profit_heat, the same function the four engines already use.
    """
    from eth_scanner.deep.blend.ensemble.facts import collect_facts
    from eth_scanner.deep.blend.ensemble.spec import build_spec
    from eth_scanner.deep.blend.receipt import apply_caller_profit_heat, build_groups

    prepared = dict(prepared or {})
    if "facts" not in prepared:
        prepared["facts"] = collect_facts(source, contract_name, live=False)
    if "spec" not in prepared:
        prepared["spec"] = build_spec(prepared["facts"])
    if "symbolic" not in prepared:
        prepared["symbolic"] = {
            "status": "skipped",
            "note": "symbolic lane recorded from the engine log",
            "heat_contribution": 0,
            "label": "evidence only",
            "halmos": {"status": "skipped", "heat_contribution": 0, "label": "evidence only"},
            "smtchecker": {
                "status": "skipped",
                "note": "SMTChecker not invoked",
                "heat_contribution": 0,
                "label": "evidence only",
                "caller_profit_delta": 0,
                "chc": {"status": "skipped", "heat_contribution": 0},
                "bmc": {"status": "skipped", "heat_contribution": 0},
            },
        }
    if "fuzz" not in prepared:
        prepared["fuzz"] = {
            "status": "ok",
            "heat_contribution": 0,
            "label": "evidence only",
            "foundry": {
                "status": "skipped",
                "note": "foundry invariant not invoked",
                "heat_contribution": 0,
                "label": "evidence only",
                "caller_profit_delta": 0,
            },
        }
    if "mutation" not in prepared:
        from eth_scanner.deep.blend.ensemble.mutation import run_mutation
        prepared["mutation"] = run_mutation(
            list((prepared["spec"] or {}).get("selected") or []),
            live=False,
        )
    for block in prepared.values():
        if isinstance(block, dict):
            block["heat_contribution"] = 0
            block.setdefault("label", "evidence only")
    layers = {name: prepared[name] for name in LAYER_ORDER if name in prepared and name != "fusion"}
    # Halmos stays an engine. Mirror its status into the symbolic layer.
    for row in report.get("engines") or []:
        if str(row.get("engine") or "") == "halmos" and isinstance(layers.get("symbolic"), dict):
            layers["symbolic"]["halmos"] = {
                "status": row.get("status") or "skipped",
                "note": row.get("note") or "",
                "heat_contribution": 0,
                "label": "evidence only",
            }
    fusion = fuse(
        findings=list(report.get("findings") or []),
        layers=layers,
        adaptations=report.get("adaptations") if isinstance(report.get("adaptations"), dict) else {},
    )
    layers["fusion"] = fusion
    witnesses = _witness_hits(list(fusion.get("witnesses") or []))
    if witnesses:
        from eth_scanner.deep.blend.receipt import dedupe_hits as _dedupe
        existing = []
        for row in report.get("findings") or []:
            existing.append({
                "engine": (row.get("engines") or [row.get("engine")])[0] if row.get("engines") else row.get("engine"),
                "rule": row.get("rule"),
                "family": "caller-profit" if row.get("kind") == "drain-proof" else (
                    "incentive" if row.get("kind") == "incentive" else "solvency"
                ),
                "call_path": row.get("call_path") or "",
                "caller_profit_delta": row.get("caller_profit_delta") or 0,
                "who_benefits": (row.get("incentive") or {}).get("who_benefits") if isinstance(row.get("incentive"), dict) else "",
                "what_breaks": (row.get("incentive") or {}).get("what_breaks") if isinstance(row.get("incentive"), dict) else "",
                "evidence": row.get("evidence") or "",
            })
        # A witness whose root cause is already a drain proof must not split the receipt.
        merged = _dedupe(existing + witnesses)
        target = report.get("target") or {}
        heat, breakdown = apply_caller_profit_heat(
            merged,
            funds_usd=target.get("funds_usd"),
            address=str(target.get("address") or ""),
            contract_name=str(target.get("contract_name") or ""),
        )
        report["findings"] = merged
        report["heat"] = heat
        report["heat_breakdown"] = breakdown
        report["groups"] = build_groups(merged)
        if heat > 0 and any(row.get("kind") == "drain-proof" for row in merged):
            report["bucket"] = "drain-found"
        elif merged:
            report["bucket"] = "maybe"
        else:
            report["bucket"] = "no"
        fusion["proven_caller_profit"] = any(row.get("kind") == "drain-proof" for row in merged)
    # passes_agreeing sits beside engines_agreeing. It does not change the engine score.
    passes = list(fusion.get("passes_agreeing") or [])
    for row in report.get("findings") or []:
        row["passes_agreeing"] = list(passes)
    classes = list((prepared.get("facts") or {}).get("bug_classes") or [])
    for row in report.get("findings") or []:
        if row.get("kind") == "drain-proof" and "unprivileged-caller-profit" not in classes:
            classes.append("unprivileged-caller-profit")
        elif row.get("kind") == "incentive" and "incentive-ordering" not in classes:
            classes.append("incentive-ordering")
    report["layers"] = layers
    report["bug_classes"] = classes
    report["drain_probability"] = fusion.get("drain_probability") or 0
    report["ensemble_pins"] = pins_public()
    report["policy"] = (
        "Heat rises only for a caller-profit drain proof on a target that holds value. "
        "Static facts, Scribble and crytic properties, SMTChecker, fuzz logs, Gambit mutants, "
        "adaptation passes, and the fusion prior are evidence and contribute 0 heat."
    )
    return report
