"""Deep worker — claim lane-b / manual-review, run engines, persist findings.

Defensive only. Never sends transactions. Never invents BROKEN from greps.
Single-engine generic detectors do not add heat.
"""

from __future__ import annotations

import json
import os
import socket
import time
from typing import Any, Optional

from eth_scanner.config import Settings, load_settings
from eth_scanner.deep.findings import agreement_summary, heat_eligible_clusters
from eth_scanner.deep.runners import engine_availability, run_all_engines
from eth_scanner.ingest.etherscan import EtherscanClient, IngestError, RateLimitError, parse_source_result
from eth_scanner.ingest.quota import DailyBudgetExhausted
from eth_scanner.ingest.unpack import materialize_source
from eth_scanner.store.supabase import ScanStore, normalize_address, open_store
from eth_scanner.types import SourceArtifact


def _worker_id() -> str:
    return "deep-%s-%s" % (socket.gethostname()[:24], os.getpid())


def _optional_explanations(
    findings: list[Any],
    address: str,
    contract_name: Optional[str],
    row: dict[str, Any],
) -> list[dict[str, Any]]:
    """Phase E: explain up to 3 non-generic agreed findings when an LLM key exists."""
    try:
        from eth_scanner.triage_ai.explain import explain_finding, llm_configured
    except Exception:  # noqa: BLE001
        return []
    if not llm_configured():
        return []
    out: list[dict[str, Any]] = []
    candidates = [
        f for f in findings
        if not getattr(f, "generic", False) and int(getattr(f, "agreement_count", 1) or 1) >= 1
    ][:3]
    for f in candidates:
        payload = f.to_dict() if hasattr(f, "to_dict") else dict(f)
        note = explain_finding(
            payload,
            context={
                "address": address,
                "contract_name": contract_name,
                "funds_usd": row.get("funds_usd"),
                "bucket": row.get("bucket"),
                "known_safe": row.get("known_safe"),
            },
        )
        out.append({"finding_id": payload.get("id"), **note})
    return out


def _fetch_source(address: str, settings: Settings) -> tuple[Optional[str], Optional[str], list[str]]:
    """Return (source_text, contract_name, notes)."""
    notes: list[str] = []
    if not settings.etherscan_api_keys:
        notes.append("no ETHERSCAN_API_KEYS — cannot fetch verified source")
        return None, None, notes
    client = EtherscanClient(settings.etherscan_api_keys, min_interval_s=settings.etherscan_min_interval_s)
    try:
        raw = client.get_source(address)
        art = parse_source_result(address, raw)
        art, _ = materialize_source(art)
        if not (art.content or "").strip():
            notes.append("etherscan returned empty source")
            return None, art.contract_name, notes
        notes.append("fetched verified source via etherscan (%s)" % (art.contract_name or "unnamed"))
        return art.content, art.contract_name, notes
    except RateLimitError as exc:
        notes.append("etherscan rate-limited: %s" % exc)
        return None, None, notes
    except DailyBudgetExhausted:
        raise
    except IngestError as exc:
        notes.append("etherscan ingest failed: %s" % exc)
        return None, None, notes
    except Exception as exc:  # noqa: BLE001
        notes.append("source fetch error: %s" % str(exc)[:200])
        return None, None, notes


def run_deep_one(
    address: str,
    *,
    settings: Optional[Settings] = None,
    store: Optional[ScanStore] = None,
    source_text: Optional[str] = None,
    engines: Optional[list[str]] = None,
    timeout_s: int = 90,
) -> dict[str, Any]:
    settings = settings or load_settings()
    store = store or open_store(settings)
    addr = normalize_address(address)
    notes: list[str] = []
    contract_name: Optional[str] = None

    source = source_text
    if not source:
        source, contract_name, fetch_notes = _fetch_source(addr, settings)
        notes.extend(fetch_notes)
    if not source:
        report = {
            "address": addr,
            "status": "skipped",
            "reason": "no verified source",
            "notes": notes,
            "availability": engine_availability(),
            "findings": [],
            "agreement": agreement_summary([]),
            "engine_runs": [],
        }
        _persist_deep(store, addr, report, contract_name=contract_name)
        return report

    findings, runs = run_all_engines(source, engines=engines, timeout_s=timeout_s)
    summary = agreement_summary(findings)
    fork_props: list[dict[str, Any]] = []
    protocol_graph: dict[str, Any] = {}
    protocol_risks: dict[str, Any] = {}
    row = store.get_target(addr) or {}
    klass = str(row.get("contract_class") or "unknown")
    try:
        from eth_scanner.fork_props.runner import run_fork_properties
        fork_props = [
            r.to_dict()
            for r in run_fork_properties(
                addr,
                contract_class=klass,
                rpc_url=getattr(settings, "eth_rpc_url", "") or "",
                run_forge=False,  # forge is optional in GHA Phase B job / local --fork-props
                timeout_s=float(timeout_s),
            )
        ]
        notes.append("phase-B eth_call fork properties=%d" % len(fork_props))
    except Exception as exc:  # noqa: BLE001
        notes.append("phase-B fork properties skipped: %s" % str(exc)[:160])
    try:
        from eth_scanner.protocol_graph.builder import build_protocol_graph
        from eth_scanner.protocol_graph.risk import score_graph_risks
        graph = build_protocol_graph(
            addr,
            source=source or "",
            contract_name=contract_name,
            funds_breakdown=list(row.get("funds_breakdown") or []),
            rpc_url=getattr(settings, "eth_rpc_url", "") or "",
            contract_class=klass,
        )
        protocol_graph = graph.to_dict()
        protocol_risks = score_graph_risks(
            graph,
            funds_usd=row.get("funds_usd"),
            source=source or "",
        )
        notes.append(
            "phase-C graph nodes=%d risks=%d"
            % (len(graph.nodes), len(protocol_risks.get("factors") or []))
        )
    except Exception as exc:  # noqa: BLE001
        notes.append("phase-C protocol graph skipped: %s" % str(exc)[:160])
    report = {
        "address": addr,
        "status": "done",
        "contract_name": contract_name,
        "notes": notes + ["engines: %s" % ", ".join("%s=%s" % (r.engine, r.status) for r in runs)],
        "availability": engine_availability(),
        "findings": [f.to_dict() for f in findings],
        "agreement": summary,
        "heat_eligible_clusters": heat_eligible_clusters(summary),
        "fork_properties": fork_props,
        "protocol_graph": protocol_graph,
        "protocol_risks": protocol_risks,
        "triage_explanations": _optional_explanations(findings, addr, contract_name, row),
        "engine_runs": [
            {
                "engine": r.engine,
                "status": r.status,
                "note": r.note,
                "duration_ms": r.duration_ms,
                "finding_count": len(r.findings),
            }
            for r in runs
        ],
        "policy": (
            "Deep engines raise confidence via agreement only. "
            "They do not add heat by themselves; Lane A evidence gate still applies. "
            "Fork properties report held/violated with state evidence only."
        ),
        "defensive_only": True,
    }
    _persist_deep(store, addr, report, contract_name=contract_name)
    return report


def run_deep_claim(
    *,
    limit: int = 2,
    settings: Optional[Settings] = None,
    store: Optional[ScanStore] = None,
    engines: Optional[list[str]] = None,
    timeout_s: int = 90,
    worker_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    settings = settings or load_settings()
    store = store or open_store(settings)
    wid = worker_id or _worker_id()
    claimed = _claim_deep(store, limit=limit, worker_id=wid)
    if not claimed:
        return []
    out: list[dict[str, Any]] = []
    for row in claimed:
        addr = row.get("address") or ""
        try:
            out.append(run_deep_one(
                addr,
                settings=settings,
                store=store,
                engines=engines,
                timeout_s=timeout_s,
            ))
        except Exception as exc:  # noqa: BLE001
            err = {
                "address": addr,
                "status": "error",
                "reason": str(exc)[:300],
                "findings": [],
                "agreement": agreement_summary([]),
            }
            _persist_deep(store, addr, err)
            out.append(err)
    return out


def _claim_deep(store: ScanStore, *, limit: int, worker_id: str) -> list[dict[str, Any]]:
    """Prefer store.claim_deep when present; else claim_lane_b and filter."""
    claim_deep = getattr(store, "claim_deep", None)
    if callable(claim_deep):
        return list(claim_deep(limit, worker_id) or [])
    rows = store.claim_lane_b(limit, worker_id)
    # Skip rows that already have a deep report artifact if we can see it.
    out: list[dict[str, Any]] = []
    for row in rows:
        deep = (row or {}).get("deep_status")
        if deep in {"done", "running"}:
            continue
        out.append(row)
    return out[:limit]


def _persist_deep(
    store: ScanStore,
    address: str,
    report: dict[str, Any],
    *,
    contract_name: Optional[str] = None,
) -> None:
    addr = normalize_address(address)
    status = str(report.get("status") or "done")
    store.save_artifact(
        addr,
        "report",
        {
            "kind": "deep-engines",
            "phase": "A",
            "report": report,
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        confidence="med" if report.get("findings") else "low",
    )
    patch = getattr(store, "patch_deep_status", None)
    if callable(patch):
        patch(
            addr,
            deep_status=status,
            contract_name=contract_name or report.get("contract_name"),
            engine_findings=report.get("findings") or [],
            engine_agreement=report.get("agreement") or {},
            fork_properties=report.get("fork_properties") or [],
            protocol_graph=report.get("protocol_graph") or {},
            protocol_risks=report.get("protocol_risks") or {},
        )
        return
    # Memory / older stores: best-effort target touch.
    row = store.get_target(addr) or {"address": addr}
    from eth_scanner.types import Target
    store.upsert_target(Target(
        address=addr,
        status="done" if status in {"done", "skipped"} else status,
        tvl_usd=row.get("tvl_usd"),
        funds_usd=row.get("funds_usd"),
        funds_status=row.get("funds_status"),
        bytecode_hash=row.get("bytecode_hash"),
    ))
