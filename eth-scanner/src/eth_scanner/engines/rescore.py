"""Recompute stored heat after a read-only check. Heat never rises here.

An EOA stamp is kept only when eth_getCode succeeds and the code is empty.
A privileged stamp is kept only when the selector is dispatched and a garbage
selector reverts. A failed read leaves the old points in place.
"""

from __future__ import annotations

from typing import Any, Optional

from eth_scanner.engines.corroborate import confirm_privileged_call, read_code
from eth_scanner.heat import HeatWeights, corroborated_heat, evidence_fact, load_heat_weights

_PRIV = "privileged-callable"
_EOA = "eoa-admin"


def _points(breakdown: dict[str, Any], key: str) -> int:
    try:
        return max(0, int(breakdown.get(key) or 0))
    except (TypeError, ValueError):
        return 0


def _admin_rows(breakdown: dict[str, Any]) -> list[dict[str, Any]]:
    admin = breakdown.get("admin") if isinstance(breakdown.get("admin"), dict) else {}
    rows = []
    for item in admin.get("confirmed") or []:
        if not isinstance(item, dict):
            continue
        lead = str(item.get("id") or item.get("lead_id") or "")
        rows.append({
            "lead_id": lead,
            "confirmed": True,
            "method": item.get("method") or "admin",
            "fact": evidence_fact({"lead_id": lead, "id": lead, "extras": item.get("extras") or {}}),
            "extras": item.get("extras") or {},
        })
    return rows


def adjust_heat(
    *,
    heat: int,
    breakdown: dict[str, Any],
    eoa_stands: Optional[bool],
    privileged_stands: Optional[bool],
    weights: Optional[HeatWeights] = None,
) -> dict[str, Any]:
    """Drop contradicted points. None means the live read did not decide."""
    w = weights or load_heat_weights()
    bd = dict(breakdown or {})
    inv = _points(bd, "invariants_failed")
    priv = _points(bd, "privileged_callable")
    eoa = _points(bd, "eoa_admin")
    corr = _points(bd, "corroborated_leads")
    admin_rows = _admin_rows(bd)
    skip = set()
    if eoa_stands is False:
        eoa = 0
        skip.add(_EOA)
    if privileged_stands is False:
        priv = 0
        skip.add(_PRIV)
    if skip:
        rejected = corroborated_heat(
            [row for row in admin_rows if row.get("fact") in skip],
            w,
        )
        corr = max(0, corr - rejected)
    total = min(w.max_heat, inv + priv + eoa + corr)
    old = max(0, int(heat or 0))
    new = min(old, total)
    return {
        "heat": new,
        "changed": new != old,
        "eoa_admin": eoa,
        "privileged_callable": priv,
        "corroborated_leads": corr,
        "invariants_failed": inv,
        "heat_contribution": 0,
    }


def rescore_rows(store: Any, rpc_url: str, *, limit: int = 30) -> dict[str, Any]:
    """Lower stored heat when a live read contradicts it. Never raises heat."""
    if not rpc_url or not hasattr(store, "_req"):
        return {"status": "skipped", "reason": "no store or rpc", "updated": 0, "heat_contribution": 0}
    rows = store._req(
        "GET",
        "test_scan_runs",
        query={
            "select": "id,address,chain,heat,blend_heat,heat_breakdown",
            "heat": "gte.3",
            "order": "heat.desc",
            "limit": str(limit),
        },
    )
    seen: set[str] = set()
    updated = 0
    changes = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        chain = str(row.get("chain") or "ethereum")
        address = str(row.get("address") or "").lower()
        if chain != "ethereum" or not address or address in seen:
            continue
        seen.add(address)
        siblings = store._req(
            "GET",
            "test_scan_runs",
            query={
                "select": "id,address,heat,blend_heat,heat_breakdown",
                "address": "eq.%s" % address,
                "limit": "20",
            },
        )
        sample = next((item for item in siblings if isinstance(item, dict) and isinstance(item.get("heat_breakdown"), dict)), row)
        breakdown = sample.get("heat_breakdown") if isinstance(sample.get("heat_breakdown"), dict) else {}
        eoa_stands, priv_stands = live_flags(rpc_url, address, breakdown)
        for item in siblings:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            bd = item.get("heat_breakdown") if isinstance(item.get("heat_breakdown"), dict) else breakdown
            adjusted = adjust_heat(
                heat=max(int(item.get("heat") or 0), int(item.get("blend_heat") or 0)),
                breakdown=bd,
                eoa_stands=eoa_stands,
                privileged_stands=priv_stands,
            )
            if not adjusted["changed"]:
                continue
            new_bd = dict(bd)
            new_bd["eoa_admin"] = adjusted["eoa_admin"]
            new_bd["privileged_callable"] = adjusted["privileged_callable"]
            new_bd["corroborated_leads"] = adjusted["corroborated_leads"]
            new_bd["total"] = adjusted["heat"]
            new_bd["rescore"] = "evidence-read"
            store._req(
                "PATCH",
                "test_scan_runs",
                {
                    "heat": adjusted["heat"],
                    "blend_heat": adjusted["heat"],
                    "heat_breakdown": new_bd,
                },
                query={"id": "eq.%s" % item["id"]},
                prefer="return=minimal",
            )
            updated += 1
            changes.append({"address": address, "heat": adjusted["heat"]})
    return {"status": "ok", "updated": updated, "changes": changes[:20], "heat_contribution": 0}


def live_flags(rpc_url: str, address: str, breakdown: dict[str, Any]) -> tuple[Optional[bool], Optional[bool]]:
    """(eoa_stands, privileged_stands). None when the read did not decide."""
    admin = breakdown.get("admin") if isinstance(breakdown.get("admin"), dict) else {}
    controller = str(admin.get("admin") or "")
    if not controller and _points(breakdown, "eoa_admin") > 0:
        from eth_scanner.engines.admin_checks import _owner_of
        controller = _owner_of(rpc_url, address) or ""
    eoa_stands: Optional[bool] = None
    if _points(breakdown, "eoa_admin") > 0 and controller:
        read = read_code(rpc_url, controller)
        if read.get("status") == "ok":
            eoa_stands = int(read.get("size") or 0) == 0
    priv_stands: Optional[bool] = None
    if _points(breakdown, "privileged_callable") > 0:
        code = read_code(rpc_url, address)
        if code.get("status") != "ok":
            return eoa_stands, None
        verdict = confirm_privileged_call(
            rpc_url,
            address,
            "3659cfe6",
            code_hex=str(code.get("hex") or ""),
            signature="upgradeTo(address)",
            data_suffix="00" * 32,
        )
        reason = str(verdict.get("reason") or "")
        if verdict.get("confirmed"):
            priv_stands = True
        elif reason in {"selector not in dispatch", "fallback swallows calls", "call changed no state"}:
            priv_stands = False
    return eoa_stands, priv_stands
