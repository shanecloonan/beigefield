"""Unified Blend receipt. One finding per root cause, across all four engines.

Heat moves only when a deduped finding is a caller-profit drain proof and the
target holds value and is not known-safe. Agreement raises confidence only.
"""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from eth_scanner.deep.blend.parse import canonical_rule, family_of, root_cause
from eth_scanner.deep.blend.versions import BLEND_ENGINES, pins_public, pin_version
from eth_scanner.deep.strong import heat_if_live_confirmed
from eth_scanner.known_safe import is_known_safe


def _kind(family: str, delta: int, incentive: bool) -> str:
    if delta > 0 and family in {"caller-profit", "incentive"}:
        return "drain-proof"
    if incentive or family == "incentive":
        return "incentive"
    return "evidence-only"


def _label(kind: str) -> str:
    return "drain proof" if kind == "drain-proof" else "evidence only"


def dedupe_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse the same broken invariant and call path from any engine."""
    buckets: dict[str, dict[str, Any]] = {}
    for hit in hits:
        family = str(hit.get("family") or family_of(str(hit.get("rule") or "")))
        path = str(hit.get("call_path") or "")
        key = root_cause(family, path)
        slot = buckets.get(key)
        if slot is None:
            slot = {
                "root_cause": key,
                "family": family,
                "call_path": path,
                "rules": [],
                "engine_rules": {},
                "engines": set(),
                "delta": 0,
                "who_benefits": "",
                "what_breaks": "",
                "evidence": "",
            }
            buckets[key] = slot
        rule = str(hit.get("rule") or "")
        engine = str(hit.get("engine") or "")
        if rule and rule not in slot["rules"]:
            slot["rules"].append(rule)
        if engine:
            slot["engines"].add(engine)
            slot["engine_rules"][engine] = rule or slot["engine_rules"].get(engine) or ""
        try:
            delta = int(hit.get("caller_profit_delta") or 0)
        except (TypeError, ValueError):
            delta = 0
        if delta > slot["delta"]:
            slot["delta"] = delta
        if hit.get("who_benefits") and not slot["who_benefits"]:
            slot["who_benefits"] = str(hit["who_benefits"])
        if hit.get("what_breaks") and not slot["what_breaks"]:
            slot["what_breaks"] = str(hit["what_breaks"])
        if hit.get("evidence") and not slot["evidence"]:
            slot["evidence"] = str(hit["evidence"])
    findings: list[dict[str, Any]] = []
    for slot in buckets.values():
        family = slot["family"]
        kind = _kind(family, slot["delta"], family == "incentive" or bool(slot["who_benefits"] or slot["what_breaks"]))
        engines = [name for name in BLEND_ENGINES if name in slot["engines"]]
        engines += sorted(slot["engines"] - set(engines))
        rule = canonical_rule(family if kind != "drain-proof" or family == "caller-profit" else family, slot["rules"])
        if kind == "drain-proof" and family == "caller-profit":
            rule = canonical_rule("caller-profit", slot["rules"])
        title = {
            "drain-proof": "Caller-profit drain proof: unprivileged balance rose",
            "incentive": "Incentive finding: ordered call favors one actor",
            "evidence-only": "Property failure (evidence only)",
        }[kind]
        if kind == "incentive" and slot["what_breaks"]:
            title = "Incentive finding: %s" % slot["what_breaks"][:120]
        score = round(len(engines) / float(len(BLEND_ENGINES)), 2)
        fid = "blend:%s" % hashlib.sha1(slot["root_cause"].encode()).hexdigest()[:12]
        incentive_block = None
        if kind == "incentive" or slot["who_benefits"] or slot["what_breaks"]:
            incentive_block = {
                "who_benefits": slot["who_benefits"] or "unspecified caller",
                "what_breaks": slot["what_breaks"] or rule,
                "ordered": True,
            }
        findings.append({
            "id": fid,
            "engine": engines[0] if engines else "blend",
            "engines": engines,
            "engines_agreeing": list(engines),
            "engine_rules": dict(slot["engine_rules"]),
            "agreement_count": len(engines),
            "agreement_score": score,
            "rule": rule,
            "root_cause": slot["root_cause"],
            "call_path": slot["call_path"] or "-",
            "title": title,
            "severity": "high" if kind == "drain-proof" else ("medium" if kind == "incentive" else "info"),
            "confidence": "high" if len(engines) >= 2 else "low",
            "funds_class": "invariant-violation",
            "kind": kind,
            "label": _label(kind),
            "caller_profit_delta": int(slot["delta"]) if kind == "drain-proof" else 0,
            "heat_contribution": 0,
            "evidence": slot["evidence"],
            "incentive": incentive_block if kind == "incentive" or (
                kind == "drain-proof" and (slot["who_benefits"] or slot["what_breaks"])
            ) else None,
            "defensive_only": True,
            "generic": kind != "drain-proof",
        })
    findings.sort(key=lambda row: (
        0 if row["kind"] == "drain-proof" else 1 if row["kind"] == "incentive" else 2,
        -int(row["agreement_count"]),
        row["root_cause"],
    ))
    return findings


def _bucket(heat: int, findings: list[dict[str, Any]]) -> str:
    if heat > 0 and any(row["kind"] == "drain-proof" for row in findings):
        return "drain-found"
    if findings:
        return "maybe"
    return "no"


def apply_caller_profit_heat(
    findings: list[dict[str, Any]],
    *,
    funds_usd: Optional[float],
    address: str = "",
    contract_name: str = "",
) -> tuple[int, dict[str, Any]]:
    """Existing heat model. Engine agreement and evidence-only rows add nothing."""
    safe, reasons = is_known_safe(address=address, contract_name=contract_name)
    proofs = [row for row in findings if row.get("kind") == "drain-proof" and int(row.get("caller_profit_delta") or 0) > 0]
    held = float(funds_usd) if funds_usd is not None else 0.0
    if safe or not proofs or held <= 0:
        _heat, _changed, breakdown = heat_if_live_confirmed(0, funds_usd, [])
        breakdown["caller_profit_gate"] = False
        breakdown["engine_heat"] = 0
        breakdown["known_safe"] = bool(safe)
        breakdown["known_safe_reasons"] = reasons
        if safe:
            breakdown["gate_reason"] = "known-safe stays cold"
        elif held <= 0 and proofs:
            breakdown["gate_reason"] = "no value held · heat 0"
        else:
            breakdown["gate_reason"] = "evidence only · heat 0"
        for row in findings:
            row["heat_contribution"] = 0
        return 0, breakdown
    delta = max(int(row["caller_profit_delta"]) for row in proofs)
    live = [{
        "id": "profit-free-value",
        "status": "failed",
        "source": "fork-simulation",
        "attacker_delta": delta,
        "evidence": "caller balance rose on a fork conservation check (no_third_party_balance_drop)",
    }]
    heat, _changed, breakdown = heat_if_live_confirmed(0, funds_usd, live)
    breakdown["caller_profit_gate"] = True
    breakdown["engine_heat"] = 0
    breakdown["known_safe"] = False
    breakdown["gate_reason"] = "caller-profit drain proof"
    stamped = False
    for row in findings:
        if not stamped and row.get("kind") == "drain-proof":
            row["heat_contribution"] = int(heat)
            stamped = True
        else:
            row["heat_contribution"] = 0
    return int(heat), breakdown


def build_groups(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per engine+rule so /test and Blend can show agreement beside each engine."""
    groups: list[dict[str, Any]] = []
    for finding in findings:
        engines = list(finding.get("engines_agreeing") or [])
        rules = finding.get("engine_rules") or {}
        for engine in engines:
            groups.append({
                "engine": engine,
                "rule": str(rules.get(engine) or finding.get("rule") or ""),
                "agreement_score": finding.get("agreement_score") or 0,
                "agreement_count": finding.get("agreement_count") or 0,
                "engines_agreeing": engines,
                "kind": finding.get("kind"),
                "label": finding.get("label"),
                "severity": finding.get("severity"),
                "title": finding.get("title"),
                "caller_profit_delta": finding.get("caller_profit_delta") or 0,
                "root_cause": finding.get("root_cause"),
            })
    return groups


def receipt_from_hits(
    hits: list[dict[str, Any]],
    *,
    engines: list[dict[str, Any]],
    address: str = "",
    funds_usd: Optional[float] = None,
    contract_name: str = "",
    contracts: Optional[list[str]] = None,
    list_id: Optional[str] = None,
    fixture: Optional[str] = None,
) -> dict[str, Any]:
    findings = dedupe_hits(hits)
    heat, breakdown = apply_caller_profit_heat(
        findings,
        funds_usd=funds_usd,
        address=address,
        contract_name=contract_name,
    )
    present = {str(row.get("id") or row.get("engine") or "") for row in engines}
    for name in BLEND_ENGINES:
        if name not in present and not any(str(row.get("engine")) == name for row in engines):
            engines.append({
                "engine": name,
                "id": name,
                "version_pin": pin_version(name),
                "status": "skipped",
                "note": "not scheduled",
                "duration_ms": 0,
            })
    for row in engines:
        row.setdefault("version_pin", pin_version(str(row.get("engine") or row.get("id") or "")))
        row.setdefault("id", row.get("engine"))
    return {
        "schema": "blend-receipt-v1",
        "defensive_only": True,
        "target": {
            "address": address,
            "contract_name": contract_name,
            "contracts": list(contracts or []),
            "list_id": list_id,
            "funds_usd": funds_usd,
            "fixture": fixture,
        },
        "engines": engines,
        "findings": findings,
        "groups": build_groups(findings),
        "heat": heat,
        "heat_breakdown": breakdown,
        "bucket": _bucket(heat, findings),
        "pins": pins_public(),
        "policy": (
            "Heat rises only for a caller-profit drain proof on a target that holds value. "
            "Symbolic and fuzz misses, mined invariants, and engine agreement stay evidence only."
        ),
    }
