"""Inline advanced engine pipeline for Lane A / monitor / backfill.

Order: funds floor (caller) → verified + money-at-risk gate →
clone fingerprint → oracle (every funded) → admin/proxy → storage diff →
Slither → Mythril (gated) → corroboration → fuzz (leads) → Halmos (leads).

Slither/Mythril/clone/oracle leads alone add *zero* heat. Heat only from
confirmed corroborations, failed invariants (fuzz/halmos), privileged_callable,
and eoa_admin ($100k+).
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
from eth_scanner.engines.admin_checks import (
    admin_as_confirmed,
    admin_as_leads,
    run_admin_checks,
)
from eth_scanner.engines.clones import match_known_bad
from eth_scanner.engines.corroborate import corroborate_lead, resolve_proxy_meta
from eth_scanner.engines.fuzz_runner import (
    FuzzReport,
    fuzz_failures_as_confirmed,
    fuzz_failures_as_invariants,
    run_lead_fuzz,
)
from eth_scanner.engines.halmos_runner import (
    HalmosReport,
    run_lead_halmos,
    symbolic_failures_as_confirmed,
    symbolic_failures_as_invariants,
)
from eth_scanner.engines.oracle_checks import (
    oracle_as_confirmed,
    oracle_as_leads,
    run_oracle_checks,
)
from eth_scanner.engines.storage_diff import (
    run_storage_diff,
    storage_as_confirmed,
    storage_as_leads,
)
from eth_scanner.heuristics.scope import FUNDS_AT_RISK_CLASSES
from eth_scanner.research.slither_runner import SLITHER_ALLOWLIST

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
    fuzz: dict[str, Any] = field(default_factory=dict)
    fuzz_invariant_results: list[dict[str, Any]] = field(default_factory=list)
    fuzz_artifacts: list[dict[str, Any]] = field(default_factory=list)
    # Phase-G stages
    oracle: dict[str, Any] = field(default_factory=dict)
    admin: dict[str, Any] = field(default_factory=dict)
    storage: dict[str, Any] = field(default_factory=dict)
    symbolic: dict[str, Any] = field(default_factory=dict)
    stage_artifacts: list[dict[str, Any]] = field(default_factory=list)
    privileged_callable: bool = False
    eoa_admin: bool = False
    extra_invariant_results: list[dict[str, Any]] = field(default_factory=list)

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
    source_dir: Optional[Path] = None,
    compiler: Optional[str] = None,
    runtime_bytecode: str = "",
    slither_timeout_s: int = 60,
    mythril_timeout_s: int = 90,
    fuzz_timeout_s: int = 60,
    halmos_timeout_s: int = 90,
    min_funds_usd: float = 2_000.0,
    run_fuzz: bool = True,
    run_halmos: bool = True,
) -> AdvancedEngineReport:
    """Run gated defensive engine stages. Never broadcasts / builds attacks."""
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
            "score": c.score,
            "dataset_id": c.dataset_id,
        })

    # --- Oracle / price-source (every funded eligible contract) ------------
    try:
        oracle = run_oracle_checks(
            address=address,
            source=source,
            rpc_url=rpc_url,
            funds_usd=funds_usd,
            timeout_s=25.0,
        )
        report.oracle = oracle.to_dict()
        report.leads.extend(oracle_as_leads(oracle))
        for row in oracle_as_confirmed(oracle):
            report.confirmed.append(row)
        if oracle.artifact:
            report.stage_artifacts.append(dict(oracle.artifact))
        report.notes.extend(list(oracle.notes or [])[:3])
    except Exception as exc:  # noqa: BLE001
        report.notes.append("oracle error (non-blocking): %s" % str(exc)[:140])

    # --- Admin / upgrade (+ legacy proxy meta) -----------------------------
    try:
        if rpc_url:
            admin = run_admin_checks(
                address=address,
                rpc_url=rpc_url,
                funds_usd=funds_usd,
                source=source,
                timeout_s=30.0,
            )
            report.admin = admin.to_dict()
            report.proxy = {
                "implementation": admin.implementation,
                "admin": admin.admin,
                "admin_is_eoa": admin.admin_is_eoa,
                "proxy_kind": admin.proxy_kind,
                "admin_class": admin.admin_class,
            }
            report.privileged_callable = bool(admin.privileged_callable)
            report.eoa_admin = bool(admin.eoa_admin)
            report.leads.extend(admin_as_leads(admin))
            for row in admin_as_confirmed(admin):
                report.confirmed.append(row)
            if admin.artifact:
                report.stage_artifacts.append(dict(admin.artifact))
            report.notes.extend(list(admin.notes or [])[:3])
        else:
            report.proxy = resolve_proxy_meta(rpc_url, address)
    except Exception as exc:  # noqa: BLE001
        report.notes.append("admin error (non-blocking): %s" % str(exc)[:140])
        if rpc_url:
            report.proxy = resolve_proxy_meta(rpc_url, address)

    # --- Storage layout diff (upgradeable proxies) -------------------------
    try:
        if rpc_url:
            storage = run_storage_diff(
                address=address,
                rpc_url=rpc_url,
                source=source,
                timeout_s=30.0,
            )
            report.storage = storage.to_dict()
            report.leads.extend(storage_as_leads(storage))
            for row in storage_as_confirmed(storage):
                report.confirmed.append(row)
            if storage.artifact:
                report.stage_artifacts.append(dict(storage.artifact))
            report.notes.extend(list(storage.notes or [])[:2])
    except Exception as exc:  # noqa: BLE001
        report.notes.append("storage-diff error (non-blocking): %s" % str(exc)[:140])

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
    is_lead = has_slither_lead or inv_needs

    # --- Mythril (gated) ---------------------------------------------------
    if is_lead:
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
    confirmable = [
        l for l in report.leads
        if not l.get("generic") and l.get("engine") in {"slither", "mythril", "clone"}
    ]
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

    # --- Fuzz (Medusa → Foundry) on leads only -----------------------------
    fuzz_report: Optional[FuzzReport] = None
    if run_fuzz and is_lead and rpc_url:
        try:
            fuzz_report = run_lead_fuzz(
                address=address,
                contract_class=contract_class,
                contract_name=contract_name,
                rpc_url=rpc_url,
                work_dir=work_dir,
                timeout_s=fuzz_timeout_s,
                source=source,
                compiler=compiler,
                runtime_bytecode=runtime_bytecode,
                source_dir=source_dir,
            )
            report.fuzz = fuzz_report.to_dict()
            report.notes.extend(list(fuzz_report.notes or [])[:4])
            report.notes.append(
                "fuzz %s tool=%s props=%d failures=%d (%sms)"
                % (
                    fuzz_report.status,
                    fuzz_report.tool,
                    fuzz_report.properties_checked,
                    fuzz_report.failure_count,
                    fuzz_report.duration_ms,
                )
            )
            if fuzz_report.failures:
                report.fuzz_invariant_results = fuzz_failures_as_invariants(fuzz_report)
                for row in fuzz_failures_as_confirmed(fuzz_report):
                    report.confirmed.append(row)
            if fuzz_report.artifact:
                report.fuzz_artifacts.append(dict(fuzz_report.artifact))
                report.stage_artifacts.append(dict(fuzz_report.artifact))
        except Exception as exc:  # noqa: BLE001
            report.notes.append("fuzz error (non-blocking): %s" % str(exc)[:160])
            report.fuzz = {"status": "error", "ran": False, "skipped": True}
    elif run_fuzz:
        report.notes.append("fuzz skipped — need Slither lead or failed/unknown invariant + rpc")
        report.fuzz = {"status": "skipped", "ran": False, "skipped": True}

    # --- Halmos symbolic on leads only -------------------------------------
    halmos_report: Optional[HalmosReport] = None
    if run_halmos and is_lead:
        try:
            halmos_report = run_lead_halmos(
                address=address,
                contract_class=contract_class,
                contract_name=contract_name,
                rpc_url=rpc_url,
                work_dir=work_dir,
                timeout_s=halmos_timeout_s,
                source=source,
                compiler=compiler,
                runtime_bytecode=runtime_bytecode,
                source_dir=source_dir,
            )
            report.symbolic = halmos_report.to_dict()
            report.notes.extend(list(halmos_report.notes or [])[:4])
            if halmos_report.failures:
                inv_rows = symbolic_failures_as_invariants(halmos_report)
                report.extra_invariant_results.extend(inv_rows)
                report.fuzz_invariant_results = list(report.fuzz_invariant_results) + inv_rows
                for row in symbolic_failures_as_confirmed(halmos_report):
                    report.confirmed.append(row)
            if halmos_report.artifact:
                report.stage_artifacts.append(dict(halmos_report.artifact))
        except Exception as exc:  # noqa: BLE001
            report.notes.append("halmos error (non-blocking): %s" % str(exc)[:160])
            report.symbolic = {"status": "error", "ran": False, "skipped": True}
    elif run_halmos:
        report.notes.append("halmos skipped — need Slither lead or failed/unknown invariant")
        report.symbolic = {"status": "skipped", "ran": False, "skipped": True}

    fuzz_ms = int((fuzz_report.duration_ms if fuzz_report else 0) or 0)
    halmos_ms = int((halmos_report.duration_ms if halmos_report else 0) or 0)
    fuzz_status = (fuzz_report.status if fuzz_report else report.fuzz.get("status") or "skipped")
    halmos_status = (halmos_report.status if halmos_report else report.symbolic.get("status") or "skipped")
    oracle_ran = bool((report.oracle or {}).get("ran"))
    admin_ran = bool((report.admin or {}).get("ran"))
    storage_ran = bool((report.storage or {}).get("ran"))
    slither_executed = report.ran_slither and report.slither_status not in {"skipped", "compile-skip"}
    mythril_executed = report.ran_mythril and report.mythril_status not in {"skipped", "compile-skip"}
    fuzz_executed = bool(fuzz_report and fuzz_report.ran and fuzz_status not in {"skipped", "compile-skip"})
    halmos_executed = bool(
        halmos_report and getattr(halmos_report, "executed", False)
        and halmos_status not in {"skipped", "compile-skip"}
    )
    report.timing = {
        "slither_ms": report.slither_ms,
        "mythril_ms": report.mythril_ms,
        "fuzz_ms": fuzz_ms,
        "halmos_ms": halmos_ms,
        "oracle_ms": int((report.oracle or {}).get("duration_ms") or 0),
        "admin_ms": int((report.admin or {}).get("duration_ms") or 0),
        "storage_ms": int((report.storage or {}).get("duration_ms") or 0),
        "total_ms": int((time.monotonic() - t0) * 1000),
        "cache_hit": report.cache_hit,
        "ran_slither": report.ran_slither,
        "ran_mythril": report.ran_mythril,
        "ran_fuzz": bool(fuzz_report and fuzz_report.ran),
        "ran_halmos": bool(halmos_report and halmos_report.ran),
        "ran_oracle": oracle_ran,
        "ran_admin": admin_ran,
        "ran_storage": storage_ran,
        # Executed vs skipped (campaign actually checked something).
        "slither_executed": slither_executed,
        "slither_skipped": not slither_executed,
        "mythril_executed": mythril_executed,
        "mythril_skipped": not mythril_executed,
        "fuzz_executed": fuzz_executed,
        "fuzz_skipped": not fuzz_executed,
        "halmos_executed": halmos_executed,
        "halmos_skipped": not halmos_executed,
        "oracle_executed": oracle_ran,
        "oracle_skipped": not oracle_ran,
        "admin_executed": admin_ran,
        "admin_skipped": not admin_ran,
        "storage_executed": storage_ran,
        "storage_skipped": not storage_ran,
        "clone_executed": True,  # fingerprint stage always runs when engines gate passes
        "clone_skipped": False,
        "slither_status": report.slither_status,
        "mythril_status": report.mythril_status,
        "fuzz_status": fuzz_status,
        "fuzz_tool": (fuzz_report.tool if fuzz_report else "none"),
        "fuzz_properties": (fuzz_report.properties_checked if fuzz_report else 0),
        "fuzz_failures": (fuzz_report.failure_count if fuzz_report else 0),
        "halmos_status": halmos_status,
        "halmos_properties": (halmos_report.properties_checked if halmos_report else 0),
        "halmos_properties_executed": int(getattr(halmos_report, "properties_executed", 0) or 0) if halmos_report else 0,
        "halmos_properties_skipped": int(getattr(halmos_report, "properties_skipped", 0) or 0) if halmos_report else 0,
        "halmos_failures": (halmos_report.failure_count if halmos_report else 0),
        "oracle_confirmed": sum(1 for c in (report.oracle or {}).get("confirmed") or [] if c.get("confirmed")),
        "admin_confirmed": sum(1 for c in (report.admin or {}).get("confirmed") or [] if c.get("confirmed")),
        "storage_confirmed": sum(1 for c in (report.storage or {}).get("confirmed") or [] if c.get("confirmed")),
        "clone_leads": len(report.clone_leads),
        "leads": len(report.leads),
        "confirmed": report.confirmed_count,
        "privileged_callable": report.privileged_callable,
        "eoa_admin": report.eoa_admin,
    }
    return report


def _slither_to_leads(result: EngineRunResult) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for f in result.findings:
        rule = (f.rule or "").strip()
        if rule and rule not in SLITHER_ALLOWLIST and is_generic_rule(rule):
            continue
        if is_generic_rule(rule):
            continue
        if rule and SLITHER_ALLOWLIST and rule not in SLITHER_ALLOWLIST:
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
