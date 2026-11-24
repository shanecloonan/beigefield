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
    preview_stands: Optional[bool] = None,
    solvency_stands: Optional[bool] = None,
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
    # A re-read that shows the stored accounting failure does not stand drops one failure's points.
    if preview_stands is False:
        inv = max(0, inv - w.failed_invariant)
    if solvency_stands is False:
        inv = max(0, inv - w.failed_invariant)
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


def _reason(breakdown: dict[str, Any]) -> str:
    return str(breakdown.get("drain_reason") or "")


def _names_preview(breakdown: dict[str, Any]) -> bool:
    reason = _reason(breakdown)
    return "erc4626-preview-consistency" in reason or "erc4626-preview-overpay" in reason


def _retired_preview(breakdown: dict[str, Any]) -> bool:
    """The old check failed any gap. That stamp is not proof of an overpay."""
    reason = _reason(breakdown)
    return "erc4626-preview-consistency" in reason and "erc4626-preview-overpay" not in reason


def _names_solvency(breakdown: dict[str, Any]) -> bool:
    reason = _reason(breakdown)
    return "erc4626-solvency" in reason or "erc4626-asset-shortfall" in reason


def _retired_solvency(breakdown: dict[str, Any]) -> bool:
    """The old check failed whenever the conversion exceeded totalAssets."""
    reason = _reason(breakdown)
    return "erc4626-solvency" in reason and "erc4626-asset-shortfall" not in reason


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


def _has_components(breakdown: dict[str, Any]) -> bool:
    return any(key in (breakdown or {}) for key in (
        "invariants_failed",
        "eoa_admin",
        "privileged_callable",
        "corroborated_leads",
        "total",
    ))


def _admin(breakdown: dict[str, Any]) -> dict[str, Any]:
    admin = breakdown.get("admin")
    return admin if isinstance(admin, dict) else {}


def _controller_details(breakdown: dict[str, Any]) -> dict[str, Any]:
    meta = _admin(breakdown).get("meta")
    if not isinstance(meta, dict):
        return {}
    details = meta.get("controller_details")
    return details if isinstance(details, dict) else {}


def _eoa_from_artifact(breakdown: dict[str, Any]) -> Optional[bool]:
    """False when the saved record is not a successful empty getCode.

    A missing code_status is the old path that called a failed read an EOA.
    A multisig, Safe, or timelock is not an EOA. None means this row has no
    EOA points to judge.
    """
    if _points(breakdown, "eoa_admin") <= 0:
        return None
    admin = _admin(breakdown)
    kind = str(admin.get("admin_class") or "").lower()
    if kind in {"multisig", "safe", "timelock", "contract"}:
        return False
    if admin.get("eoa_admin") is False:
        return False
    details = _controller_details(breakdown)
    status = str(details.get("code_status") or "")
    try:
        size = int(details.get("code_size")) if details.get("code_size") is not None else None
    except (TypeError, ValueError):
        size = None
    if status == "ok" and size == 0 and kind in {"", "eoa"}:
        return True
    return False


def _current_privileged(breakdown: dict[str, Any]) -> bool:
    admin = _admin(breakdown)
    for item in admin.get("confirmed") or []:
        if isinstance(item, dict) and _CURRENT_PRIV in str(item.get("evidence") or ""):
            return True
    return False


def _priv_from_artifact(breakdown: dict[str, Any]) -> Optional[bool]:
    """False for the retired no-revert probe, or points the admin report rejected."""
    if _retired_privileged(breakdown):
        return False
    if _points(breakdown, "privileged_callable") <= 0:
        return None
    if _current_privileged(breakdown):
        return True
    if _admin(breakdown).get("privileged_callable") is False:
        return False
    return None


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
        column: "gte.1",
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
        eoa_stands: Optional[bool] = None
        priv_stands: Optional[bool] = None
        if (
            _points(breakdown, "eoa_admin") > 0
            or _points(breakdown, "privileged_callable") > 0
            or _retired_privileged(breakdown)
        ):
            eoa_stands, priv_stands = live_flags(rpc_url, address, breakdown)
            # A failed live read stays None. The saved record can still decide.
            if eoa_stands is None:
                eoa_stands = _eoa_from_artifact(breakdown)
            if priv_stands is None:
                priv_stands = _priv_from_artifact(breakdown)
        preview_stands: Optional[bool] = None
        solvency_stands: Optional[bool] = None
        if _points(breakdown, "invariants_failed") > 0 and _names_preview(breakdown):
            from eth_scanner.invariants.live import preview_failure_stands
            preview_stands = preview_failure_stands(rpc_url, address)
            # A dead RPC cannot confirm the retired two-sided gap. It is not an overpay.
            if preview_stands is None and _retired_preview(breakdown):
                preview_stands = False
        if _points(breakdown, "invariants_failed") > 0 and _names_solvency(breakdown):
            from eth_scanner.invariants.live import solvency_failure_stands
            solvency_stands = solvency_failure_stands(rpc_url, address)
            if solvency_stands is None and _retired_solvency(breakdown):
                solvency_stands = False
        proved = (
            eoa_stands is False
            or priv_stands is False
            or preview_stands is False
            or solvency_stands is False
        )
        explained = [
            _best_breakdown([item]) for item in siblings if _has_components(_best_breakdown([item]))
        ]
        explained_cap = 0
        if explained:
            explained_cap = max(
                adjust_heat(
                    heat=10**6,
                    breakdown=bd,
                    eoa_stands=eoa_stands,
                    privileged_stands=priv_stands,
                    preview_stands=preview_stands if _names_preview(bd) else None,
                    solvency_stands=solvency_stands if _names_solvency(bd) else None,
                )["heat"]
                for bd in explained
            )
        bare = any(
            not _has_components(_best_breakdown([item])) and _stored_heat(item) > explained_cap
            for item in siblings
        )
        if not proved and not (explained and bare):
            if len(skipped) < 15:
                skipped.append({
                    "address": address,
                    "heat": _stored_heat(row),
                    "reason": "not-contradicted" if explained else "no-probe-points",
                    "eoa_stands": eoa_stands,
                    "privileged_stands": priv_stands,
                })
            continue
        original_peak = max(_stored_heat(item) for item in siblings)
        adjusted_rows = []
        for item in siblings:
            own = _best_breakdown([item])
            # A bare number beside a component breakdown is not a second piece of evidence.
            bd = own if _has_components(own) else {}
            adjusted = adjust_heat(
                heat=_stored_heat(item),
                breakdown=bd,
                eoa_stands=eoa_stands,
                privileged_stands=priv_stands,
                preview_stands=preview_stands if _names_preview(bd) else None,
                solvency_stands=solvency_stands if _names_solvency(bd) else None,
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
            new_bd["invariants_failed"] = adjusted["invariants_failed"]
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
