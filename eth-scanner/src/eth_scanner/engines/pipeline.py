"""Inline advanced engine pipeline for Lane A / monitor / backfill.

Order: funds floor (caller) → verified + money-at-risk gate → Slither (cached
by bytecode hash) → Mythril if Slither lead or failed/unknown invariant →
clone fingerprint → proxy meta → read-only corroboration.

Slither/Mythril hits are *leads*. Heat only from confirmed corroborations
(+ existing failed invariants / privileged / EOA-admin evidence).
"""

from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from eth_scanner.deep.findings import EngineFinding, is_generic_rule, sanitize_evidence
from eth_scanner.deep.runners import EngineRunResult, run_mythril, run_slither
from eth_scanner.engines.clones import match_known_bad
from eth_scanner.engines.corroborate import corroborate_lead, resolve_proxy_meta
from eth_scanner.heuristics.scope import FUNDS_AT_RISK_CLASSES
from eth_scanner.research.slither_runner import SLITHER_ALLOWLIST

# Engines run on classic money-at-risk families plus custody (funds-at-rest
# keep class that is intentionally not auto-promoted by the funnel alone).
ENGINE_ELIGIBLE_CLASSES = frozenset(FUNDS_AT_RISK_CLASSES | {"custody"})

_CACHE_LOCK = threading.Lock()
_MEM_CACHE: dict[str, dict[str, Any]] = {}


@dataclass
class AdvancedEngineReport:
    ran_slither: bool = False
    ran_mythril: bool = False
    slither_status: str = "skipped"
    mythril_status: str = "skipped"
    slither_ms: int = 0
    mythril_ms: int = 0
    cache_hit: bool = False
    leads: list[dict[str, Any]] = field(default_factory=list)
    confirmed: list[dict[str, Any]] = field(default_factory=list)
    clone_leads: list[dict[str, Any]] = field(default_factory=list)
    proxy: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    timing: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def confirmed_count(self) -> int:
        return sum(1 for c in self.confirmed if c.get("confirmed"))


def run_advanced_engines(
    *,
    address: str,
    source: str,
    bytecode_hash: str = "",
    contract_class: str = "unknown",
    contract_name: Optional[str] = None,
    funds_usd: Optional[float] = None,
    verified: bool = False,
    rpc_url: str = "",
    invariant_results: Optional[list[dict[str, Any]]] = None,
    work_dir: Optional[Path] = None,
    slither_timeout_s: int = 60,
    mythril_timeout_s: int = 90,
    min_funds_usd: float = 2_000.0,
) -> AdvancedEngineReport:
    """Run gated Slither/Mythril/clone/proxy/corroboration. Defensive only."""
    report = AdvancedEngineReport()
    t0 = time.monotonic()
    inv = list(invariant_results or [])

    if not verified or not (source or "").strip():
        report.notes.append("skip engines — unverified or empty source")
        report.timing["total_ms"] = int((time.monotonic() - t0) * 1000)
        return report
    if contract_class not in ENGINE_ELIGIBLE_CLASSES:
        report.notes.append("skip engines — class %s not money-at-risk" % contract_class)
        report.timing["total_ms"] = int((time.monotonic() - t0) * 1000)
        return report
    if funds_usd is None or float(funds_usd) < float(min_funds_usd):
        report.notes.append("skip engines — funds below floor")
        report.timing["total_ms"] = int((time.monotonic() - t0) * 1000)
        return report

    # --- Clone fingerprint (cheap, always) ---------------------------------
    clones = match_known_bad(bytecode_hash=bytecode_hash, source=source, contract_name=contract_name)
    report.clone_leads = [c.to_dict() for c in clones]
    for c in clones:
        report.leads.append({
            "id": c.id,
            "engine": "clone",
            "kind": c.kind,
            "rule": c.id,
            "title": c.title,
            "severity": c.severity,
            "evidence": sanitize_evidence(c.evidence),
            "generic": False,
        })

    # --- Proxy meta --------------------------------------------------------
    if rpc_url:
        report.proxy = resolve_proxy_meta(rpc_url, address)
        if report.proxy.get("admin_is_eoa") and funds_usd is not None and funds_usd >= 100_000:
            report.leads.append({
                "id": "proxy-admin-eoa",
                "engine": "proxy",
                "rule": "eoa-admin",
                "title": "EIP-1967 admin is an EOA",
                "severity": "high",
                "evidence": sanitize_evidence("admin=%s funds>=100k" % report.proxy.get("admin")),
                "generic": False,
            })

    # --- Slither (cached by bytecode hash) ---------------------------------
    cache_key = (bytecode_hash or "").lower() or None
    cached = _cache_get(cache_key, work_dir) if cache_key else None
    if cached is not None:
        report.cache_hit = True
        report.ran_slither = True
        report.slither_status = cached.get("status") or "ok"
        report.slither_ms = int(cached.get("duration_ms") or 0)
        for row in cached.get("leads") or []:
            report.leads.append(dict(row))
        report.notes.append("slither cache hit bytecode=%s" % (cache_key[:16] if cache_key else ""))
    else:
        sl = run_slither(source, timeout_s=slither_timeout_s)
        report.ran_slither = sl.status != "skipped"
        report.slither_status = sl.status
        report.slither_ms = sl.duration_ms
        leads = _slither_to_leads(sl)
        for row in leads:
            report.leads.append(row)
        if cache_key and sl.status in {"ok", "error"}:
            _cache_put(cache_key, work_dir, {
                "status": sl.status,
                "duration_ms": sl.duration_ms,
                "leads": leads,
                "note": sl.note,
            })
        report.notes.append("slither %s (%s)" % (sl.status, sl.note[:120]))

    has_slither_lead = any(l.get("engine") == "slither" for l in report.leads)
    inv_needs = any((r.get("status") or "").lower() in {"failed", "unknown"} for r in inv)

    # --- Mythril (gated) ---------------------------------------------------
    if has_slither_lead or inv_needs:
        my = run_mythril(source, timeout_s=mythril_timeout_s)
        report.ran_mythril = my.status != "skipped"
        report.mythril_status = my.status
        report.mythril_ms = my.duration_ms
        for f in my.findings:
            if is_generic_rule(f.rule):
                continue
            report.leads.append({
                "id": f.id,
                "engine": "mythril",
                "rule": f.rule,
                "title": f.title,
                "severity": f.severity,
                "evidence": sanitize_evidence(f.evidence),
                "generic": bool(f.generic),
                "funds_class": f.funds_class,
            })
        report.notes.append("mythril %s (%s)" % (my.status, my.note[:120]))
    else:
        report.notes.append("mythril skipped — no Slither lead / failed-or-unknown invariant")

    # --- Corroboration (read-only) -----------------------------------------
    # Confirm each non-generic lead; only confirmed rows can add heat later.
    confirmable = [l for l in report.leads if not l.get("generic")]
    if rpc_url and confirmable:
        max_workers = max(1, min(6, len(confirmable)))

        def _one(lead: dict[str, Any]) -> dict[str, Any]:
            try:
                return corroborate_lead(
                    rpc_url=rpc_url,
                    address=address,
                    lead=lead,
                    funds_usd=funds_usd,
                ).to_dict()
            except Exception as exc:  # noqa: BLE001
                return {
                    "lead_id": lead.get("id"),
                    "confirmed": False,
                    "method": "none",
                    "evidence": "corroboration error: %s" % str(exc)[:120],
                }

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futs = [pool.submit(_one, lead) for lead in confirmable[:24]]
            for fut in as_completed(futs):
                report.confirmed.append(fut.result())
    else:
        for lead in confirmable:
            report.confirmed.append({
                "lead_id": lead.get("id"),
                "confirmed": False,
                "method": "none",
                "evidence": "corroboration skipped",
            })

    report.timing = {
        "slither_ms": report.slither_ms,
        "mythril_ms": report.mythril_ms,
        "total_ms": int((time.monotonic() - t0) * 1000),
        "cache_hit": report.cache_hit,
        "ran_slither": report.ran_slither,
        "ran_mythril": report.ran_mythril,
        "slither_status": report.slither_status,
        "mythril_status": report.mythril_status,
        "leads": len(report.leads),
        "confirmed": report.confirmed_count,
    }
    return report


def _slither_to_leads(result: EngineRunResult) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for f in result.findings:
        rule = (f.rule or "").strip()
        # Prefer research allowlist; drop generics.
        if rule and rule not in SLITHER_ALLOWLIST and is_generic_rule(rule):
            continue
        if is_generic_rule(rule):
            continue
        if rule and SLITHER_ALLOWLIST and rule not in SLITHER_ALLOWLIST:
            # deep parser may use different rule strings — keep funds-class hits
            if f.funds_class in {"other", ""} and f.severity in {"info", "low"}:
                continue
        out.append({
            "id": f.id,
            "engine": "slither",
            "rule": rule,
            "title": f.title,
            "severity": f.severity,
            "evidence": sanitize_evidence(f.evidence),
            "generic": bool(f.generic),
            "funds_class": f.funds_class,
        })
    return out


def _cache_path(work_dir: Optional[Path], key: str) -> Optional[Path]:
    if not work_dir:
        env = os.environ.get("ETH_SCANNER_WORK_DIR")
        if env:
            work_dir = Path(env)
    if not work_dir:
        return None
    root = Path(work_dir) / "engine-cache" / "slither"
    root.mkdir(parents=True, exist_ok=True)
    return root / ("%s.json" % key[:64])


def _cache_get(key: Optional[str], work_dir: Optional[Path]) -> Optional[dict[str, Any]]:
    if not key:
        return None
    with _CACHE_LOCK:
        if key in _MEM_CACHE:
            return dict(_MEM_CACHE[key])
    path = _cache_path(work_dir, key)
    if path and path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            with _CACHE_LOCK:
                _MEM_CACHE[key] = data
            return dict(data)
        except (OSError, json.JSONDecodeError):
            return None
    return None


def _cache_put(key: str, work_dir: Optional[Path], data: dict[str, Any]) -> None:
    with _CACHE_LOCK:
        _MEM_CACHE[key] = dict(data)
    path = _cache_path(work_dir, key)
    if path:
        try:
            path.write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass
