"""Evidence-based heat — ranking signal only when rules fail.

Funds are a *sort key*, never heat. Pattern leads (weak auth, proxy-delegatecall,
fork family, erc4626-rounding, etc.) contribute ZERO heat.

Heat comes only from evidence:
  (a) invariant checks that actually fail (held/unknown → 0)
  (b) privileged function callable by an outsider
  (c) single-EOA admin over eoa_admin_min_usd
  (d) Slither/Mythril/clone leads ONLY when a read-only corroboration confirms

Slither/Mythril hits alone are leads (0 heat). Never a verdict. Never auto-yes.
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
    min_funds_for_lane_b: float = 2_000.0

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


def invariant_heat(
    results: list[dict[str, Any]],
    weights: Optional[HeatWeights] = None,
) -> int:
    """Only *failed* invariants add heat. held/unknown add zero."""
    w = weights or load_heat_weights()
    n_failed = sum(1 for r in results if (r.get("status") or "").lower() == "failed")
    return min(w.failed_invariant_cap, n_failed * w.failed_invariant)


def corroborated_heat(
    confirmed: list[dict[str, Any]],
    weights: Optional[HeatWeights] = None,
) -> int:
    """Only *confirmed* engine/clone corroborations add heat. Leads alone → 0."""
    w = weights or load_heat_weights()
    n = sum(1 for c in confirmed if c.get("confirmed"))
    return min(w.corroborated_lead_cap, n * w.corroborated_lead)


def evidence_heat(
    *,
    funds_usd: Optional[float],
    invariant_results: list[dict[str, Any]],
    privileged_callable: bool = False,
    eoa_admin: bool = False,
    corroborated: Optional[list[dict[str, Any]]] = None,
    weights: Optional[HeatWeights] = None,
) -> tuple[int, dict[str, Any]]:
    """Compose heat from evidence only. Funds are ranking metadata, not heat."""
    w = weights or load_heat_weights()
    rank = funds_rank(funds_usd, w)
    inv = invariant_heat(invariant_results, w)
    priv = w.privileged_callable if privileged_callable else 0
    eoa = 0
    if eoa_admin and funds_usd is not None and funds_usd >= w.eoa_admin_min_usd:
        eoa = w.eoa_admin
    corr = corroborated_heat(list(corroborated or []), w)
    total = min(w.max_heat, inv + priv + eoa + corr)
    breakdown = {
        # "funds" kept for UI sort; explicitly not part of total heat.
        "funds": rank,
        "funds_rank": rank,
        "funds_in_heat": 0,
        "invariants_failed": inv,
        "privileged_callable": priv,
        "eoa_admin": eoa,
        "corroborated_leads": corr,
        "total": total,
        "weights": w.to_dict(),
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
    failed = [r for r in invariant_results if (r.get("status") or "").lower() == "failed"]
    if failed:
        return True, "invariant failed: %s" % (failed[0].get("id") or failed[0].get("name") or "unknown")
    if privileged_callable:
        return True, "privileged function callable by arbitrary address"
    if eoa_admin and funds >= w.eoa_admin_min_usd:
        return True, "EOA admin/upgrader on contract holding >= $%s" % (
            "{:,.0f}".format(w.eoa_admin_min_usd)
        )
    confirmed = [c for c in (corroborated or []) if c.get("confirmed")]
    if confirmed:
        return True, "corroborated engine lead: %s" % (confirmed[0].get("lead_id") or "lead")
    return False, "no failed invariant / privileged / EOA-admin / corroborated evidence"
