"""Deep-scan strong master-list candidates. Defensive engines only.

A strong candidate is hot or Lane B after the light pass, tier 1 holding at
least TIER1_MIN_FUNDS_USD, tier 2 holding at least TIER2_MIN_FUNDS_USD, or a
list drain prior of at least DRAIN_PROBABILITY_STRONG_MIN (0.60).

The deep pass walks that set in drain-probability order. A changed list hash
resets the cursor to the top. Engine output is stored on test_scan_findings
and adds zero heat. Heat moves only when a live read-only invariant or
privileged/EOA check fails. No exploit code, no transaction broadcasting.
"""

from __future__ import annotations

import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from eth_scanner.classify import classify_contract, engine_config_for_class
from eth_scanner.config import Settings, load_settings
from eth_scanner.deep.findings import EngineFinding, sanitize_evidence
from eth_scanner.deep.findings import apply_agreement, dedupe_findings
from eth_scanner.deep.medusa_runner import fork_profit_results, run_medusa
from eth_scanner.deep.runners import EngineRunResult
from eth_scanner.deep.runners import (
    MYTHRIL_EXECUTION_TIMEOUT_S,
    MYTHRIL_MAX_DEPTH,
    engine_availability,
    run_aderyn,
    run_halmos,
    run_mythril,
    run_property_fuzz,
    run_semgrep,
    run_slither,
    run_slither_printers,
)
from eth_scanner.deep.source_tree import solc_version_of, write_verified_project
from eth_scanner.feed.master_list import MasterCandidate, list_fingerprint, load_master_candidates
from eth_scanner.heat import evidence_heat
from eth_scanner.ingest.etherscan import EtherscanClient, parse_source_result
from eth_scanner.known_safe import is_known_safe
from eth_scanner.store.supabase import ScanStore, normalize_address, open_store
from eth_scanner.types import SourceArtifact

# Live-balance thresholds for the deep set. Hot/Lane B always qualifies.
TIER1_MIN_FUNDS_USD = 10_000.0
TIER2_MIN_FUNDS_USD = 100_000.0
# List prior (0–1), not the 0–100 live drain score.
DRAIN_PROBABILITY_STRONG_MIN = 0.60
CURSOR_ID = "strong-deep"
RANK_KEY = "drain_probability"
FUZZ_ROOT = Path(__file__).resolve().parents[3] / "research" / "fuzz"


def is_strong_candidate(
    *,
    tier: int,
    funds_usd: Optional[float],
    heat: int = 0,
    bucket: Optional[str] = None,
    drain_probability: Optional[float] = None,
    tier1_min_usd: float = TIER1_MIN_FUNDS_USD,
    tier2_min_usd: float = TIER2_MIN_FUNDS_USD,
    drain_min: float = DRAIN_PROBABILITY_STRONG_MIN,
) -> bool:
    if int(heat or 0) > 0 or bucket == "lane-b-queue":
        return True
    try:
        if drain_probability is not None and float(drain_probability) >= float(drain_min):
            return True
    except (TypeError, ValueError):
        pass
    funds = float(funds_usd) if funds_usd is not None else 0.0
    if int(tier or 99) == 1 and funds >= float(tier1_min_usd):
        return True
    if int(tier or 99) == 2 and funds >= float(tier2_min_usd):
        return True
    return False


def heat_if_live_confirmed(
    previous: int,
    funds_usd: Optional[float],
    live_results: list[dict[str, Any]],
) -> tuple[int, bool, dict[str, Any]]:
    """Raise heat only from live read-only failures. Engine hits are ignored."""
    failed = [r for r in live_results if str(r.get("status") or "").lower() == "failed"]
    priv = any(
        str(r.get("id") or "").startswith("privileged-") and str(r.get("status") or "").lower() == "failed"
        for r in live_results
    )
    eoa = any(
        r.get("id") == "roles-owner" and (r.get("extras") or {}).get("kind") == "eoa"
        for r in live_results
    )
    prev = int(previous or 0)
    if not failed and not priv and not eoa:
        return prev, False, {"live_confirmed": False, "engine_heat": 0, "previous": prev}
    new, breakdown = evidence_heat(
        funds_usd=funds_usd,
        invariant_results=list(live_results),
        privileged_callable=priv,
        eoa_admin=eoa,
        corroborated=None,
    )
    breakdown["engine_heat"] = 0
    breakdown["live_confirmed"] = True
    breakdown["previous"] = prev
    if new > prev:
        return new, True, breakdown
    return prev, False, breakdown


@dataclass
class StrongProgress:
    status: str = "running"
    strong: int = 0
    cursor_start: int = 0
    cursor_next: int = 0
    scanned: int = 0
    skipped_known_safe: int = 0
    findings_stored: int = 0
    heat_changed: int = 0
    errors: int = 0
    duration_s: float = 0.0
    message: str = ""
    engine_runtime_ms: dict[str, int] = field(default_factory=dict)
    heat_changes: list[dict[str, Any]] = field(default_factory=list)
    availability: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def select_strong(
    candidates: list[MasterCandidate],
    light_by_address: dict[str, dict[str, Any]],
) -> list[tuple[MasterCandidate, dict[str, Any], float]]:
    """Highest drain prior first, then tier, live/estimated USD, TVL."""
    chosen: list[tuple[MasterCandidate, dict[str, Any], float]] = []
    for cand in candidates:
        light = light_by_address.get(cand.address) or {}
        if light.get("funds_usd") is not None:
            funds = float(light["funds_usd"])
        else:
            funds = float(cand.est_usd_held or 0.0)
        heat = int(light.get("heat") or 0)
        bucket = light.get("bucket")
        if is_strong_candidate(
            tier=cand.tier,
            funds_usd=funds,
            heat=heat,
            bucket=bucket,
            drain_probability=cand.drain_probability,
        ):
            chosen.append((cand, light, funds))
    chosen.sort(key=_strong_sort_key)
    return chosen


def _strong_sort_key(item: tuple[MasterCandidate, dict[str, Any], float]) -> tuple:
    cand, _light, funds = item
    tvl = float(cand.defillama_eth_tvl or 0.0)
    return (
        -float(cand.drain_probability or 0.0),
        cand.tier,
        -float(funds or 0.0),
        -tvl,
        cand.rank,
        cand.address,
    )


def run_strong_deep(
    *,
    settings: Optional[Settings] = None,
    store: Optional[ScanStore] = None,
    path: Optional[str] = None,
    workers: int = 2,
    deadline_minutes: float = 40.0,
    deadline_monotonic: Optional[float] = None,
    reset: bool = False,
    scan_one: Optional[Callable[..., dict[str, Any]]] = None,
) -> StrongProgress:
    settings = settings or load_settings()
    store = store or open_store(settings)
    started = time.monotonic()
    deadline = (
        float(deadline_monotonic)
        if deadline_monotonic is not None
        else started + max(1.0, float(deadline_minutes) * 60.0)
    )
    progress = StrongProgress(availability=engine_availability())
    candidates = load_master_candidates(path)
    light = _light_index(store)
    selected = select_strong(candidates, light)
    progress.strong = len(selected)
    if not selected:
        progress.status = "done"
        progress.message = "no strong candidates"
        progress.duration_s = round(time.monotonic() - started, 1)
        return progress

    list_sha = list_fingerprint(candidates)
    row = _read_cursor(store)
    cursor = _strong_cursor(row, len(selected), list_sha, reset=reset)
    progress.cursor_start = cursor
    progress.cursor_next = cursor
    workers = max(1, min(int(workers or 1), 4))
    scan = scan_one or (lambda cand, light_row, funds: _scan_candidate(
        cand, light_row, funds, settings=settings,
    ))
    idx = cursor
    try:
        while idx < len(selected):
            if idx > cursor and time.monotonic() >= deadline:
                break
            batch = selected[idx:idx + workers]
            reports = _scan_batch(batch, scan=scan, workers=workers)
            for (cand, light_row, funds), report in zip(batch, reports):
                _absorb(progress, cand, light_row, funds, report, store)
            idx += len(batch)
            finished = idx >= len(selected)
            progress.cursor_next = 0 if finished else idx
            _checkpoint(store, progress, len(selected), list_sha)
            if finished or time.monotonic() >= deadline:
                break
        progress.status = "done" if progress.cursor_next == 0 and progress.scanned else "running"
        if progress.status == "done":
            progress.message = "strong set covered — next run starts at the highest drain probability"
        else:
            progress.message = "checkpoint saved — resume at %d/%d" % (progress.cursor_next, len(selected))
    except Exception as exc:  # noqa: BLE001
        progress.status = "error"
        progress.message = str(exc)[:240]
    progress.duration_s = round(time.monotonic() - started, 1)
    _checkpoint(store, progress, len(selected), list_sha)
    return progress


def _scan_batch(batch, *, scan, workers: int) -> list[dict[str, Any]]:
    if workers == 1 or len(batch) == 1:
        return [scan(c, light, funds) for c, light, funds in batch]
    out: list[Optional[dict[str, Any]]] = [None] * len(batch)

    def _one(i: int, item) -> tuple[int, dict[str, Any]]:
        cand, light, funds = item
        try:
            return i, scan(cand, light, funds)
        except Exception as exc:  # noqa: BLE001
            return i, {"status": "error", "error": str(exc)[:240], "findings": [], "engine_runs": []}

    with ThreadPoolExecutor(max_workers=min(workers, len(batch))) as pool:
        futs = [pool.submit(_one, i, item) for i, item in enumerate(batch)]
        for fut in as_completed(futs):
            i, report = fut.result()
            out[i] = report
    return [r or {"status": "error", "findings": [], "engine_runs": []} for r in out]


def _scan_candidate(
    cand: MasterCandidate,
    light: dict[str, Any],
    funds: float,
    *,
    settings: Settings,
) -> dict[str, Any]:
    safe, reasons = is_known_safe(
        address=cand.address,
        contract_name=light.get("contract_name") or None,
        implementation=cand.proxy_implementation,
    )
    if safe:
        return {
            "status": "skipped",
            "skipped_reason": "known-safe",
            "known_safe_reasons": reasons,
            "findings": [],
            "engine_runs": [],
            "live_results": [],
            "heat_before": int(light.get("heat") or 0),
        }
    artifact = _fetch_artifact(cand.address, settings)
    impl_artifact = None
    impl = cand.proxy_implementation or (artifact.implementation if artifact else None)
    if impl and impl != cand.address:
        impl_artifact = _fetch_artifact(impl, settings)
    findings: list[EngineFinding] = []
    runs = []
    with tempfile.TemporaryDirectory(prefix="strong-deep-") as tmp:
        root = Path(tmp)
        if artifact and (artifact.content or "").strip():
            meta = write_verified_project(artifact, root / "proxy" if artifact.is_proxy else root / "srcproj")
            _select_solc(meta.get("solc") or "")
            project = str(root / ("proxy" if artifact.is_proxy else "srcproj"))
            klass, conf = classify_contract(
                name=artifact.contract_name or cand.protocol,
                source=artifact.content or "",
                category=cand.category,
                forked_from=cand.forked_from or "",
            )
            findings, runs = _run_engine_set(
                project, meta.get("primary") or "", settings,
                slither_detect=engine_config_for_class(klass)["slither_detect"],
            )
            runs.append({"engine": "class", "status": conf, "note": klass, "duration_ms": 0, "finding_count": 0})
        if impl_artifact and (impl_artifact.content or "").strip():
            impl_root = root / "implementation"
            impl_meta = write_verified_project(impl_artifact, impl_root)
            _select_solc(impl_meta.get("solc") or "")
            impl_findings, impl_runs = _run_engine_set(
                str(impl_root), impl_meta.get("primary") or "", settings, include_fuzz=False,
            )
            for finding in impl_findings:
                finding.id = "impl:" + finding.id
                finding.contract = finding.contract or impl_artifact.contract_name
            findings.extend(impl_findings)
            runs.extend(impl_runs)
    live = _live(cand.address, settings)
    return {
        "status": "done" if artifact and artifact.content else "skipped",
        "skipped_reason": None if artifact and artifact.content else "no verified source",
        "contract_name": (artifact.contract_name if artifact else None) or light.get("contract_name"),
        "findings": findings,
        "engine_runs": runs,
        "live_results": live,
        "heat_before": int(light.get("heat") or 0),
        "compiler": artifact.compiler if artifact else None,
    }


def _run_engine_set(
    project: str,
    primary: str,
    settings: Settings,
    *,
    include_fuzz: bool = True,
    slither_detect: str = "all",
) -> tuple[list[EngineFinding], list[dict[str, Any]]]:
    """Per-engine timeouts. One slow engine does not cancel the others."""
    tasks = {
        "slither": lambda: run_slither("", project_dir=project, timeout_s=120, detect=slither_detect),
        "slither-printers": lambda: run_slither_printers(project, timeout_s=60),
        "aderyn": lambda: run_aderyn("", project_dir=project, timeout_s=120),
        "mythril": lambda: (
            run_mythril(
                "",
                sol_path=primary,
                timeout_s=MYTHRIL_EXECUTION_TIMEOUT_S + 30,
                execution_timeout=MYTHRIL_EXECUTION_TIMEOUT_S,
                max_depth=MYTHRIL_MAX_DEPTH,
            ) if primary else EngineRunResult("mythril", "skipped", note="no primary source file")
        ),
        "semgrep": lambda: run_semgrep(project, timeout_s=120),
        "halmos": lambda: run_halmos(harness_dir=FUZZ_ROOT, timeout_s=90),
        "medusa": lambda: run_medusa(suite_dir=FUZZ_ROOT, timeout_s=90),
    }
    if include_fuzz:
        tasks["forge-fuzz"] = lambda: run_property_fuzz(
            fork_url=getattr(settings, "eth_rpc_url", "") or "",
            timeout_s=180,
            suite_dir=FUZZ_ROOT,
        )
    results = []
    findings: list[EngineFinding] = []
    with ThreadPoolExecutor(max_workers=min(4, len(tasks))) as pool:
        futs = {pool.submit(fn): name for name, fn in tasks.items()}
        for fut in as_completed(futs):
            name = futs[fut]
            try:
                result = fut.result()
            except Exception as exc:  # noqa: BLE001
                results.append({
                    "engine": name, "status": "error", "note": str(exc)[:160],
                    "duration_ms": 0, "finding_count": 0,
                })
                continue
            # Static/symbolic/fuzz output is evidence. A caller-profit
            # counterexample is the only row that may later raise heat.
            for finding in result.findings:
                evidence = finding.evidence or ""
                if "caller_profit_delta=0" in evidence or "caller_profit_delta=" not in evidence:
                    finding.generic = True
            findings.extend(result.findings[:40])
            results.append({
                "engine": result.engine,
                "status": result.status,
                "note": result.note,
                "duration_ms": result.duration_ms,
                "finding_count": len(result.findings),
            })
    ranked = apply_agreement(dedupe_findings(findings))
    for finding in ranked:
        if finding.agreement_count > 1 and "agreement" not in finding.title:
            finding.title = "%s · agreement %d" % (finding.title, finding.agreement_count)
    return ranked, results


def _live(address: str, settings: Settings) -> list[dict[str, Any]]:
    try:
        from eth_scanner.invariants.live import run_live_invariants
        rows = run_live_invariants(
            address,
            rpc_url=getattr(settings, "eth_rpc_url", "") or "",
            timeout_s=20,
        )
        return [r.to_dict() for r in rows]
    except Exception:  # noqa: BLE001
        return []


def _fetch_artifact(address: str, settings: Settings) -> Optional[SourceArtifact]:
    keys = list(getattr(settings, "etherscan_api_keys", None) or [])
    if not keys:
        return None
    try:
        client = EtherscanClient(keys, min_interval_s=getattr(settings, "etherscan_min_interval_s", 0.4))
        raw = client.get_source(address)
        return parse_source_result(address, raw)
    except Exception:  # noqa: BLE001
        return None


def _select_solc(version: str) -> None:
    ver = solc_version_of(version) or version
    if not ver:
        return
    import shutil
    import subprocess
    if not shutil.which("solc-select"):
        return
    try:
        subprocess.run(["solc-select", "install", ver], capture_output=True, timeout=90, check=False)
        subprocess.run(["solc-select", "use", ver], capture_output=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return


def _absorb(progress, cand, light, funds, report, store) -> None:
    progress.scanned += 1
    if report.get("skipped_reason") == "known-safe":
        progress.skipped_known_safe += 1
    if report.get("status") == "error":
        progress.errors += 1
    for run in report.get("engine_runs") or []:
        name = str(run.get("engine") or "engine")
        progress.engine_runtime_ms[name] = progress.engine_runtime_ms.get(name, 0) + int(run.get("duration_ms") or 0)
    heat_before = int(report.get("heat_before") if report.get("heat_before") is not None else (light.get("heat") or 0))
    live = list(report.get("live_results") or [])
    live.extend(fork_profit_results(report.get("findings") or []))
    heat_after, changed, breakdown = heat_if_live_confirmed(
        heat_before, funds, live,
    )
    if changed:
        progress.heat_changed += 1
        progress.heat_changes.append({
            "address": cand.address,
            "heat_before": heat_before,
            "heat_after": heat_after,
            "tier": cand.tier,
            "candidate_reason": cand.candidate_reason,
        })
    n = _persist(store, cand, light, funds, report, heat_after, changed, breakdown)
    progress.findings_stored += n


def _persist(store, cand, light, funds, report, heat_after, changed, breakdown) -> int:
    save_run = getattr(store, "save_test_scan_run", None)
    save_findings = getattr(store, "save_test_scan_findings", None)
    if not callable(save_run):
        return 0
    addr = normalize_address(cand.address)
    status = "skipped" if report.get("status") == "skipped" else ("error" if report.get("status") == "error" else "done")
    row = save_run({
        "dedupe_key": "strong-deep:%s" % addr,
        "kind": "engines",
        "address": addr,
        "contract_name": report.get("contract_name") or cand.protocol,
        "tvl_usd": funds,
        "money_at_risk_usd": funds,
        "funds_usd": funds,
        "discovery_source": "master_list",
        "candidate_reason": cand.candidate_reason,
        "tier": cand.tier,
        "bucket": light.get("bucket"),
        "heat": heat_after if changed else int(light.get("heat") or 0),
        "status": "done" if status == "done" else status,
        "dropped": False,
        "notes": [
            "strong-deep engines are evidence only (heat contribution 0)",
            report.get("skipped_reason") or "",
        ],
        "raw": {
            "feed": "strong-deep",
            "engine_runs": report.get("engine_runs") or [],
            "heat_changed": changed,
            "heat_breakdown": breakdown,
            "engine_heat": 0,
            "compiler": report.get("compiler"),
        },
    })
    run_id = (row or {}).get("id")
    findings = []
    for i, finding in enumerate(report.get("findings") or []):
        data = finding.to_dict() if isinstance(finding, EngineFinding) else dict(finding)
        sev = str(data.get("severity") or "info")
        if sev not in {"critical", "high", "medium", "med", "low", "info"}:
            sev = "info"
        conf = str(data.get("confidence") or "")
        if conf not in {"high", "medium", "med", "low"}:
            conf = None
        snippet = sanitize_evidence(data.get("evidence") or "")
        findings.append({
            "finding_key": "%s:%s:%s" % (data.get("engine") or "engine", data.get("rule") or i, data.get("line") or i),
            "kind": "engines",
            "address": addr,
            "engine": data.get("engine"),
            "detector": data.get("rule"),
            "rule": data.get("rule"),
            "title": str(data.get("title") or "")[:180],
            "severity": sev,
            "confidence": conf,
            "evidence": snippet,
            "snippet": snippet,
            "location_file": data.get("file"),
            "location_line": data.get("line"),
            "location_contract": data.get("contract"),
            "location_function": data.get("function"),
            "defensive_only": True,
            "funds_at_risk_class": data.get("funds_class") if data.get("funds_class") in {
                "reentrancy", "access-control", "arithmetic", "rounding", "oracle-manipulation",
                "staleness", "unchecked-call", "token-integration", "signature-replay",
                "delegatecall-storage", "bridge-message", "dos-locked-funds", "mev-slippage",
                "selfdestruct-ether", "randomness", "invariant-violation", "other",
            } else "other",
            "raw": {
                "tool": data.get("engine"),
                "detector": data.get("rule"),
                "severity": sev,
                "location": {
                    "file": data.get("file"),
                    "line": data.get("line"),
                    "contract": data.get("contract"),
                    "function": data.get("function"),
                },
                "snippet": snippet,
                "heat_contribution": 0,
            },
        })
    if run_id and findings and callable(save_findings):
        return int(save_findings(str(run_id), findings) or 0)
    return 0


def _light_index(store: ScanStore) -> dict[str, dict[str, Any]]:
    fn = getattr(store, "list_test_scan_runs", None)
    if not callable(fn):
        return {}
    try:
        rows = fn(discovery_source="master_list", limit=1000) or []
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        addr = str(row.get("address") or "").lower()
        if addr and addr not in out:
            out[addr] = row
    return out


def _read_cursor(store: ScanStore) -> Optional[dict[str, Any]]:
    fn = getattr(store, "get_backfill", None)
    if not callable(fn):
        return None
    try:
        row = fn(CURSOR_ID)
    except Exception:  # noqa: BLE001
        return None
    return dict(row) if row else None


def _strong_cursor(
    row: Optional[dict[str, Any]],
    n: int,
    list_sha: str,
    *,
    reset: bool,
) -> int:
    if reset or not row:
        return 0
    stats = row.get("stats") or {}
    if not isinstance(stats, dict):
        stats = {}
    if stats.get("list_sha") != list_sha or stats.get("rank_key") != RANK_KEY:
        return 0
    cur = int(row.get("cursor_block") or 0)
    if cur <= 0 or cur >= n:
        return 0
    return cur


def _checkpoint(store: ScanStore, progress: StrongProgress, strong_n: int, list_sha: str = "") -> None:
    fn = getattr(store, "upsert_backfill", None)
    if not callable(fn):
        return
    try:
        fn({
            "id": CURSOR_ID,
            "start_block": 0,
            "end_block": int(strong_n),
            "cursor_block": int(progress.cursor_next),
            "status": progress.status,
            "source": "strong-deep",
            "fully_scanned": progress.scanned,
            "heat_positive": progress.heat_changed,
            "stats": {
                "strong": progress.strong,
                "list_sha": list_sha,
                "rank_key": RANK_KEY,
                "engine_runtime_ms": progress.engine_runtime_ms,
                "heat_changes": progress.heat_changes[:20],
                "availability": progress.availability,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            "last_error": progress.message if progress.status == "error" else None,
        })
    except Exception:  # noqa: BLE001
        return


