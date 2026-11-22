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
# The old probe treated a non-reverting eth_call as an open privileged function.
_RETIRED_PRIV = "eth_call succeeded (no revert)"
_CURRENT_PRIV = "control selector reverted"


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


def _ethereum(chain: Any) -> bool:
    text = str(chain or "").strip().lower()
    return text in {"", "ethereum", "eth", "mainnet"}


def _evidence_points(breakdown: dict[str, Any]) -> int:
    return (
        _points(breakdown, "eoa_admin")
        + _points(breakdown, "privileged_callable")
        + _points(breakdown, "invariants_failed")
        + _points(breakdown, "corroborated_leads")
    )


def _breakdowns(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Column breakdown, or the copy Blend stores on the receipt."""
    found: list[dict[str, Any]] = []
    column = row.get("heat_breakdown")
    if isinstance(column, dict):
        found.append(column)
    receipt = row.get("blend_receipt")
    if isinstance(receipt, dict):
        nested = receipt.get("heat_breakdown")
        if isinstance(nested, dict):
            found.append(nested)
    return found


def _best_breakdown(rows: list[dict[str, Any]]) -> dict[str, Any]:
    best: dict[str, Any] = {}
    best_points = -1
    for row in rows:
        for breakdown in _breakdowns(row):
            points = _evidence_points(breakdown)
            if points > best_points:
                best = breakdown
                best_points = points
    return best


def _retired_privileged(breakdown: dict[str, Any]) -> bool:
    """The saved confirmation is the probe the selector-and-control check replaced."""
    admin = breakdown.get("admin") if isinstance(breakdown.get("admin"), dict) else {}
    for item in admin.get("confirmed") or []:
        if not isinstance(item, dict):
            continue
        evidence = str(item.get("evidence") or "")
        if _RETIRED_PRIV not in evidence or _CURRENT_PRIV in evidence:
            continue
        lead = str(item.get("id") or item.get("lead_id") or "")
        if not lead or "privileg" in lead or "uninit" in lead or "upgrade" in lead:
            return True
    return False


def _stored_heat(row: dict[str, Any]) -> int:
    try:
        heat = int(row.get("heat") or 0)
    except (TypeError, ValueError):
        heat = 0
    try:
        blend = int(row.get("blend_heat") or 0)
    except (TypeError, ValueError):
        blend = 0
    return max(heat, blend, 0)


def _pages(store: Any, query: dict[str, str]):
    """Every matching row. The board reads older scans than a single page."""
    offset = 0
    while offset <= 5000:
        page_query = dict(query)
        page_query["limit"] = "200"
        page_query["offset"] = str(offset)
        rows = store._req("GET", "test_scan_runs", query=page_query) or []
        if not isinstance(rows, list) or not rows:
            return
        for item in rows:
            if isinstance(item, dict):
                yield item
        if len(rows) < 200:
            return
        offset += 200


def _top_addresses(store: Any, column: str, limit: int) -> list[dict[str, Any]]:
    chosen: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in _pages(store, {
        "select": "id,address,chain,heat,blend_heat,heat_breakdown,blend_receipt",
        column: "gte.3",
        "order": "%s.desc" % column,
    }):
        address = str(row.get("address") or "").lower()
        if not _ethereum(row.get("chain")) or not address or address in seen:
            continue
        seen.add(address)
        chosen.append(row)
        if len(chosen) >= limit:
            break
    return chosen


def _candidates(store: Any, limit: int) -> list[dict[str, Any]]:
    """High heat from either column. The board ranks max(heat, blend_heat)."""
    merged: dict[str, dict[str, Any]] = {}
    for column in ("heat", "blend_heat"):
        for row in _top_addresses(store, column, limit):
            address = str(row.get("address") or "").lower()
            current = merged.get(address)
            if current is None or _stored_heat(row) > _stored_heat(current):
                merged[address] = row
    ordered = sorted(merged.values(), key=_stored_heat, reverse=True)
    return ordered[:limit]


def rescore_rows(store: Any, rpc_url: str, *, limit: int = 30) -> dict[str, Any]:
    """Lower stored heat when a live read contradicts it. Never raises heat.

    Every stored scan for that contract is rewritten, so the all-time peak
    falls with the false pattern. Original peak is kept for audit. A row whose
    heat is a real invariant failure is not reduced by this pass.
    """
    if not rpc_url or not hasattr(store, "_req"):
        return {"status": "skipped", "reason": "no store or rpc", "updated": 0, "heat_contribution": 0}
    updated = 0
    changes = []
    skipped = []
    for row in _candidates(store, max(1, limit)):
        address = str(row.get("address") or "").lower()
        siblings = list(_pages(store, {
            "select": "id,address,chain,heat,blend_heat,heat_breakdown,blend_receipt",
            "address": "ilike.%s" % address,
        }))
        siblings = [item for item in siblings if _ethereum(item.get("chain"))] or [row]
        breakdown = _best_breakdown(siblings)
        if _points(breakdown, "eoa_admin") <= 0 and _points(breakdown, "privileged_callable") <= 0:
            if len(skipped) < 15:
                skipped.append({
                    "address": address,
                    "heat": _stored_heat(row),
                    "reason": "no-probe-points",
                })
            continue
        eoa_stands, priv_stands = live_flags(rpc_url, address, breakdown)
        # A failed live read stays None. The retired phrase is already proof.
        if priv_stands is None and _retired_privileged(breakdown):
            priv_stands = False
        if eoa_stands is not False and priv_stands is not False:
            if len(skipped) < 15:
                skipped.append({
                    "address": address,
                    "heat": _stored_heat(row),
                    "reason": "not-contradicted",
                    "eoa_stands": eoa_stands,
                    "privileged_stands": priv_stands,
                })
            continue
        original_peak = max(_stored_heat(item) for item in siblings)
        adjusted_rows = []
        for item in siblings:
            own = _best_breakdown([item])
            bd = own if _evidence_points(own) > 0 else breakdown
            adjusted = adjust_heat(
                heat=_stored_heat(item),
                breakdown=bd,
                eoa_stands=eoa_stands,
                privileged_stands=priv_stands,
            )
            adjusted_rows.append((item, bd, adjusted))
        recomputed = max(item[2]["heat"] for item in adjusted_rows)
        for item, bd, adjusted in adjusted_rows:
            if not item.get("id"):
                continue
            new_bd = dict(bd)
            if "original_peak" not in new_bd:
                new_bd["original_peak"] = original_peak
            new_bd["eoa_admin"] = adjusted["eoa_admin"]
            new_bd["privileged_callable"] = adjusted["privileged_callable"]
            new_bd["corroborated_leads"] = adjusted["corroborated_leads"]
            new_bd["total"] = adjusted["heat"]
            new_bd["peak_heat"] = recomputed
            new_bd["rescore"] = "evidence-read"
            stored = _stored_heat(item)
            if stored == adjusted["heat"] and item.get("heat_breakdown") == new_bd:
                continue
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
            changes.append({
                "address": address,
                "heat": adjusted["heat"],
                "peak_heat": recomputed,
                "original_peak": original_peak,
            })
    return {
        "status": "ok",
        "updated": updated,
        "changes": changes[:20],
        "skipped": skipped,
        "heat_contribution": 0,
    }


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
