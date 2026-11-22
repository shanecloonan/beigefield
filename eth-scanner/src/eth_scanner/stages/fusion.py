"""Confidence-weighted stage fusion.

Heat is the sum of distinct evidence facts. A later stage that finds
nothing does not lower that sum, and a pending stage is ignored. A hold
removes a fact only when its confidence is higher than the support. The
same fact is counted once.
"""

from __future__ import annotations

from typing import Any, Optional

_MAX_HEAT = 12
_SLOW = ("similarity", "cross-contract", "halmos", "hevm", "kontrol", "fork", "fuzz")
_FACTS = (
    ("invariants_failed", "invariant-failed", 1.0),
    ("privileged_callable", "privileged-callable", 0.45),
    ("eoa_admin", "eoa-admin", 0.8),
    ("corroborated_leads", "corroborated-lead", 0.7),
    ("exploit_poc_heat", "fork-conservation", 0.9),
)


def _confidence(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number < 0:
        return 0.0
    if number > 1:
        return 1.0
    return number


def fuse(stages: list[dict[str, Any]]) -> dict[str, Any]:
    """Combine stage facts. Empty and pending stages add nothing and remove nothing."""
    best: dict[str, dict[str, float]] = {}
    pending: list[str] = []
    for stage in stages or []:
        if not isinstance(stage, dict):
            continue
        status = str(stage.get("status") or "pending")
        if status in {"pending", "running"}:
            pending.append(str(stage.get("id") or "stage"))
            continue
        if status != "done":
            continue
        stage_confidence = _confidence(stage.get("confidence"), 0.0)
        for fact in stage.get("facts") or []:
            if not isinstance(fact, dict):
                continue
            key = str(fact.get("fact") or "")
            if not key:
                continue
            confidence = _confidence(fact.get("confidence"), stage_confidence)
            slot = best.setdefault(key, {"heat": 0.0, "support": 0.0, "hold": 0.0})
            if str(fact.get("direction") or "support") == "hold":
                slot["hold"] = max(slot["hold"], confidence)
                continue
            try:
                heat = int(fact.get("heat") or 0)
            except (TypeError, ValueError):
                heat = 0
            if heat <= 0:
                continue
            if confidence > slot["support"] or (confidence == slot["support"] and heat > slot["heat"]):
                slot["heat"] = float(heat)
                slot["support"] = confidence
    facts: dict[str, int] = {}
    total = 0
    for key, slot in best.items():
        heat = int(slot["heat"])
        if slot["hold"] > slot["support"]:
            heat = 0
        elif slot["hold"] > 0 and slot["hold"] == slot["support"]:
            heat = heat // 2
        facts[key] = heat
        total += heat
    return {
        "heat": min(_MAX_HEAT, total),
        "score_state": "provisional" if pending else "final",
        "pending_stages": pending,
        "facts": facts,
    }


def stages_for(breakdown: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    """One finished quick stage plus the slow stages still waiting."""
    bd = breakdown or {}
    facts = []
    for key, fact, confidence in _FACTS:
        try:
            heat = int(bd.get(key) or 0)
        except (TypeError, ValueError):
            heat = 0
        if heat <= 0:
            continue
        facts.append({"fact": fact, "heat": heat, "direction": "support", "confidence": confidence})
    quick = {"id": "quick", "status": "done", "confidence": 1.0, "facts": facts}
    waiting = [
        {"id": name, "status": "pending", "confidence": 0.0, "facts": []}
        for name in _SLOW
    ]
    return [quick, *waiting]


def annotate_stages(breakdown: Optional[dict[str, Any]], *, heat: int = 0) -> dict[str, Any]:
    """Attach stage status. The evidence heat number is left unchanged."""
    bd = dict(breakdown or {})
    stages = stages_for(bd)
    fused = fuse(stages)
    bd["stages"] = stages
    bd["score_state"] = fused["score_state"]
    bd["pending_stages"] = fused["pending_stages"]
    bd["fused_heat"] = fused["heat"]
    bd["evidence_heat"] = int(heat or bd.get("total") or 0)
    return bd


def complete_stage(
    breakdown: Optional[dict[str, Any]],
    stage_id: str,
    *,
    facts: Optional[list[dict[str, Any]]] = None,
    confidence: float = 0.95,
    status: str = "done",
) -> dict[str, Any]:
    """Record one finished stage and fuse again. No new fact means the heat stays."""
    bd = dict(breakdown or {})
    stages = [dict(row) for row in bd.get("stages") or stages_for(bd)]
    found = False
    for row in stages:
        if str(row.get("id") or "") != stage_id:
            continue
        row["status"] = status
        row["confidence"] = _confidence(confidence, 0.95)
        row["facts"] = list(facts or [])
        found = True
        break
    if not found:
        stages.append({
            "id": stage_id,
            "status": status,
            "confidence": _confidence(confidence, 0.95),
            "facts": list(facts or []),
        })
    fused = fuse(stages)
    bd["stages"] = stages
    bd["score_state"] = fused["score_state"]
    bd["pending_stages"] = fused["pending_stages"]
    bd["fused_heat"] = fused["heat"]
    return bd
