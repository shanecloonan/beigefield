"""Lane A worker — S0–S5 (and S6 gate) across as many ETH addresses as limits allow.

Emits heat + bucket. Never a verdict. Never auto-yes. Low IR → manual-review.
"""

from __future__ import annotations

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Optional

from eth_scanner.config import Settings, load_settings
from eth_scanner.decompile.heimdall import decompile
from eth_scanner.engines.pipeline import run_advanced_engines
from eth_scanner.funnel.s0_s7 import FunnelConfig, FunnelContext, run_lane_a
from eth_scanner.heat import evidence_heat, should_promote_lane_b
from eth_scanner.ingest.etherscan import (
    EtherscanClient,
    IngestError,
    RateLimitError,
    fetch_rpc_code,
    fingerprint_bytecode,
    has_runtime_code,
    parse_source_result,
)
from eth_scanner.feed.lists import bounds_for_address
from eth_scanner.ingest.funds import (
    DEFAULT_MIN_FUNDS_USD,
    FundsSnapshot,
    funds_range_reason,
    probe_contract_funds,
)
from eth_scanner.ingest.unpack import materialize_source, select_ir_artifact
from eth_scanner.ir.normalize import normalize
from eth_scanner.store.supabase import ScanStore, artifact_payload, normalize_address, open_store
from eth_scanner.types import FunnelResult, SourceArtifact, StageTrace, Target, to_plain


def run_one(
    address: str,
    *,
    settings: Optional[Settings] = None,
    store: Optional[ScanStore] = None,
    source_path: Optional[Path] = None,
    source_text: Optional[str] = None,
    tvl_usd: Optional[float] = None,
    bytecode: str = "",
) -> FunnelResult:
    settings = settings or load_settings()
    store = store or open_store(settings)
    addr = normalize_address(address)
    closed = store.closed_no_hashes()
    # Heat / engine floor stays the historical threshold. List scans do not
    # rewrite it. The drop below uses the list range when one is configured.
    min_funds = float(getattr(settings, "min_funds_usd", DEFAULT_MIN_FUNDS_USD) or DEFAULT_MIN_FUNDS_USD)
    drop_min, drop_max = _scan_range(addr, settings, min_funds)

    # --- Funds range FIRST (before source fetch / analysis) ----------------
    # Local fixtures skip the live probe. Manual --tvl override wins.
    funds = _resolve_funds(
        addr,
        settings=settings,
        tvl_usd=tvl_usd,
        local_source=bool(source_path or source_text),
        min_funds=min_funds,
    )
    if funds.status == "ok" and funds.total_usd is not None:
        reason = funds_range_reason(funds.total_usd, drop_min, drop_max)
        if reason:
            result = _funds_floor_drop(addr, funds, reason, drop_min, drop_max)
            target = Target(
                address=addr,
                tvl_usd=funds.total_usd,
                status="skipped",
                has_code=True,
                funds_usd=funds.total_usd,
                funds_breakdown=list(funds.to_dict().get("breakdown") or []),
                funds_status=funds.status,
                funds_checked_at=funds.checked_at,
            )
            store.upsert_target(target)
            store.save_result(addr, result)
            return result

    effective_tvl = tvl_usd if tvl_usd is not None else funds.total_usd

    artifact, code, src_dir, incomplete, incomplete_reason = _ingest(
        addr,
        settings=settings,
        source_path=source_path,
        source_text=source_text,
        bytecode=bytecode,
    )
    code_hash = fingerprint_bytecode(code) if code else _source_fingerprint(artifact.content)
    has_code = has_runtime_code(code) if code else bool(artifact.content)
    if incomplete and not has_code:
        # Rate-limit starvation is not a confirmed empty EOA — S0 must keep the row.
        has_code = True
    target = Target(
        address=addr,
        bytecode_hash=code_hash or None,
        bytecode=code or None,
        tvl_usd=effective_tvl,
        status="running",
        has_code=has_code,
        prior_closed_no=bool(code_hash and code_hash in closed),
        ingest_incomplete=incomplete,
        ingest_incomplete_reason=incomplete_reason,
        funds_usd=funds.total_usd if funds.status in {"ok", "override"} else None,
        funds_breakdown=list(funds.to_dict().get("breakdown") or []),
        funds_status=funds.status,
        funds_checked_at=funds.checked_at,
    )
    store.upsert_target(target)
    store.save_artifact(addr, artifact.kind, artifact_payload(artifact), artifact.src_confidence)

    ir = normalize(artifact, source_dir=src_dir, try_slither=True)
    store.save_artifact(addr, "ir", to_plain(ir), ir.ir_confidence)

    result = run_lane_a(FunnelContext(
        target=target,
        artifact=artifact,
        ir=ir,
        source_text=artifact.content,
        rpc_url=settings.eth_rpc_url or "",
        config=FunnelConfig(
            heat_threshold=settings.heat_threshold,
            tvl_floor_usd=settings.tvl_floor_usd,
            min_funds_usd=float(getattr(settings, "min_funds_usd", min_funds) or min_funds),
        ),
    ))
    # Prepend funds stage so receipts / Supabase show the floor check first.
    result.stage_trace = [_funds_trace(funds, drop_min, drop_max), *list(result.stage_trace or [])]
    result.funds_usd = target.funds_usd
    result.funds_breakdown = list(target.funds_breakdown or [])
    result.funds_status = target.funds_status
    result.funds_checked_at = target.funds_checked_at
    result.contract_name = artifact.contract_name
    if funds.status == "unknown":
        result.notes = list(result.notes or []) + list(funds.notes or ["funds lookup unknown — continued"])

    # Advanced engines AFTER funds floor + class: Slither (cached) → Mythril →
    # read-only corroboration. Leads never add heat alone.
    if (
        not result.dropped
        and artifact.kind == "source"
        and artifact.src_confidence in {"high", "med"}
        and (target.funds_usd is not None and target.funds_usd >= min_funds)
    ):
        try:
            eng = run_advanced_engines(
                address=addr,
                source=artifact.content or "",
                bytecode_hash=code_hash or "",
                contract_class=result.contract_class or "unknown",
                contract_name=artifact.contract_name,
                funds_usd=target.funds_usd,
                verified=True,
                rpc_url=settings.eth_rpc_url or "",
                invariant_results=list(result.invariant_results or []),
                work_dir=settings.work_dir,
                source_dir=src_dir,
                compiler=getattr(artifact, "compiler", None),
                runtime_bytecode=code or "",
            )
            result.engine_leads = list(eng.leads)
            result.confirmed_findings = list(eng.confirmed)
            result.engine_timing = dict(eng.timing)
            result.notes = list(result.notes or []) + list(eng.notes)
            # Fuzz/Halmos property failures feed failed_invariant evidence (+ confirmed).
            inv_rows = (
                list(result.invariant_results or [])
                + list(eng.fuzz_invariant_results or [])
                + list(getattr(eng, "extra_invariant_results", None) or [])
            )
            if eng.fuzz_invariant_results or getattr(eng, "extra_invariant_results", None):
                result.invariant_results = inv_rows
            # Persist stage proof artifacts (fuzz/symbolic/oracle/admin/storage).
            save_art = getattr(store, "save_artifact", None)
            if callable(save_art):
                arts = list(eng.fuzz_artifacts or []) + list(getattr(eng, "stage_artifacts", None) or [])
                seen_kinds: set[str] = set()
                for art in arts:
                    kind = str(art.get("kind") or "fuzz")
                    # Avoid double-saving the same fuzz artifact from both lists.
                    key = kind + ":" + str(art.get("address") or "") + ":" + str(art.get("status") or "")
                    if key in seen_kinds:
                        continue
                    seen_kinds.add(key)
                    try:
                        conf = "med" if art.get("failures") or art.get("confirmed") else "low"
                        save_art(addr, kind, dict(art), conf)
                    except Exception as exc:  # noqa: BLE001
                        result.notes = list(result.notes or []) + [
                            "%s artifact save failed: %s" % (kind, str(exc)[:120])
                        ]
            # Recompute evidence heat with corroborations + stage confirmations.
            priv, eoa = _flags_from_invariant_dicts(inv_rows)
            priv = bool(priv or getattr(eng, "privileged_callable", False))
            eoa = bool(eoa or getattr(eng, "eoa_admin", False))
            heat, heat_bd = evidence_heat(
                funds_usd=target.funds_usd,
                invariant_results=inv_rows,
                privileged_callable=priv,
                eoa_admin=eoa,
                corroborated=list(eng.confirmed),
            )
            heat_bd = dict(heat_bd)
            heat_bd["engine_leads"] = len(eng.leads)
            heat_bd["engine_confirmed"] = eng.confirmed_count
            heat_bd["engine_timing"] = dict(eng.timing)
            heat_bd["fuzz"] = dict(eng.fuzz or {})
            heat_bd["oracle"] = dict(getattr(eng, "oracle", None) or {})
            heat_bd["admin"] = dict(getattr(eng, "admin", None) or {})
            heat_bd["storage"] = dict(getattr(eng, "storage", None) or {})
            heat_bd["symbolic"] = dict(getattr(eng, "symbolic", None) or {})
            result.heat = heat
            result.heat_breakdown = heat_bd
            promote, why = should_promote_lane_b(
                funds_usd=target.funds_usd,
                invariant_results=inv_rows,
                privileged_callable=priv,
                eoa_admin=eoa,
                corroborated=list(eng.confirmed),
            )
            if promote and result.bucket == "lane-a-cool":
                result.bucket = "lane-b-queue"
                result.notes = list(result.notes or []) + ["promoted after corroborated engine lead: %s" % why]
            # Persist engine findings on the target when the store supports it.
            patch = getattr(store, "patch_deep_status", None)
            if callable(patch):
                try:
                    patch(
                        addr,
                        deep_status="inline-engines",
                        engine_findings=list(eng.leads),
                        engine_agreement={
                            "confirmed": list(eng.confirmed),
                            "timing": dict(eng.timing),
                            "proxy": dict(eng.proxy),
                            "fuzz": dict(eng.fuzz or {}),
                            "oracle": dict(getattr(eng, "oracle", None) or {}),
                            "admin": dict(getattr(eng, "admin", None) or {}),
                            "storage": dict(getattr(eng, "storage", None) or {}),
                            "symbolic": dict(getattr(eng, "symbolic", None) or {}),
                        },
                    )
                except Exception:  # noqa: BLE001
                    pass
        except Exception as exc:  # noqa: BLE001 — engines must never sink Lane A
            result.notes = list(result.notes or []) + ["advanced engines error: %s" % str(exc)[:160]]

    # Optional post-heat fork-verify (off unless ETH_SCANNER_FORK_VERIFY=1).
    # Local-fork conservation check; never broadcasts.
    try:
        from eth_scanner.engines.fork_verify import maybe_run_on_result
        maybe_run_on_result(
            result,
            settings=settings,
            address=addr,
            source=(artifact.content or "") if artifact else "",
        )
    except Exception as exc:  # noqa: BLE001 — must never sink Lane A
        result.notes = list(result.notes or []) + [
            "fork-verify error (non-blocking): %s" % str(exc)[:160]
        ]

    store.save_result(addr, result)
    return result


def _resolve_funds(
    address: str,
    *,
    settings: Settings,
    tvl_usd: Optional[float],
    local_source: bool,
    min_funds: float,
) -> FundsSnapshot:
    if tvl_usd is not None:
        return FundsSnapshot(
            status="override",
            total_usd=float(tvl_usd),
            breakdown=[],
            checked_at=None,
            notes=["manual TVL override — live funds probe skipped for floor math"],
        )
    if local_source:
        return FundsSnapshot(
            status="skipped",
            total_usd=None,
            breakdown=[],
            notes=["local fixture/source — live funds floor skipped"],
        )
    return probe_contract_funds(
        address,
        rpc_url=settings.eth_rpc_url or "",
        min_funds_usd=min_funds,
    )


def _scan_range(address: str, settings: Settings, fallback_min: float) -> tuple[float, float | None]:
    """List min/max when this scan is for a list. Otherwise the non-list floor, no ceiling."""
    rmin = getattr(settings, "range_min_usd", None)
    rmax = getattr(settings, "range_max_usd", None)
    if rmin is None and rmax is None:
        found = bounds_for_address(address)
        if found is not None:
            return found
        return float(fallback_min), None
    low = float(fallback_min) if rmin is None else float(rmin)
    high = None if rmax is None else float(rmax)
    return low, high


def _funds_trace(funds: FundsSnapshot, min_funds: float, max_funds: float | None = None) -> StageTrace:
    decision = "keep"
    reason = "funds ok"
    ranged = funds_range_reason(funds.total_usd, min_funds, max_funds) if funds.total_usd is not None else None
    if funds.status == "override":
        decision, reason = "keep", "manual TVL override"
    elif funds.status == "skipped":
        decision, reason = "skip", "local source — funds floor not applied"
    elif funds.status == "unknown":
        decision, reason = "unknown", funds.error or "funds lookup failed — continue"
    elif funds.status == "ok" and ranged:
        decision, reason = "drop", ranged
    elif funds.status == "ok" and max_funds is not None:
        decision, reason = "keep", "funds inside range ($%s–$%s)" % (
            "{:,.0f}".format(min_funds),
            "{:,.0f}".format(max_funds),
        )
    elif funds.status == "ok":
        decision, reason = "keep", "funds >= floor ($%s)" % ("{:,.0f}".format(min_funds))
    return StageTrace(
        stage="funds",
        decision=decision,
        reason=reason,
        extras={
            "funds_usd": funds.total_usd,
            "funds_status": funds.status,
            "min_funds_usd": min_funds,
            "max_funds_usd": max_funds,
            "breakdown": funds.to_dict().get("breakdown") or [],
            "checked_at": funds.checked_at,
            "rpc": funds.to_dict().get("rpc_url"),
        },
    )


def _funds_floor_drop(
    address: str,
    funds: FundsSnapshot,
    reason: str,
    min_funds: float,
    max_funds: float | None = None,
) -> FunnelResult:
    return FunnelResult(
        bucket="lane-a-cool",
        dropped=True,
        drop_reason=reason,
        heat=0,
        src_confidence="low",
        ir_confidence="low",
        stage_trace=[_funds_trace(funds, min_funds, max_funds)],
        notes=[
            "Lane A is noise-kill + ranking, not a verdict.",
            reason,
            "Source fetch and analysis skipped — live funds are outside this list's range.",
        ],
        funds_usd=funds.total_usd,
        funds_breakdown=list(funds.to_dict().get("breakdown") or []),
        funds_status=funds.status,
        funds_checked_at=funds.checked_at,
    )


def run_batch(
    addresses: list[str],
    *,
    settings: Optional[Settings] = None,
    store: Optional[ScanStore] = None,
    source_path: Optional[Path] = None,
    tvl_usd: Optional[float] = None,
) -> list[tuple[str, FunnelResult]]:
    settings = settings or load_settings()
    store = store or open_store(settings)
    out: list[tuple[str, FunnelResult]] = []
    for raw in addresses:
        addr = normalize_address(raw)
        result = run_one(
            addr,
            settings=settings,
            store=store,
            source_path=source_path,
            tvl_usd=tvl_usd,
        )
        out.append((addr, result))
    return out


def claim_and_run(limit: int = 10, *, settings: Optional[Settings] = None) -> list[tuple[str, FunnelResult]]:
    settings = settings or load_settings()
    store = open_store(settings)
    claimed = store.claim_pending(limit, settings.worker_id)
    out: list[tuple[str, FunnelResult]] = []
    for row in claimed:
        result = run_one(row["address"], settings=settings, store=store, tvl_usd=_as_float(row.get("tvl_usd")))
        out.append((row["address"], result))
    return out


def claim_and_drain(
    *,
    max_scans: int = 1000,
    workers: int = 8,
    deadline_monotonic: Optional[float] = None,
    settings: Optional[Settings] = None,
    store: Optional[ScanStore] = None,
    batch_size: Optional[int] = None,
) -> list[tuple[str, Any]]:
    """Claim pending targets and scan until empty, max_scans, or deadline.

    Uses a small thread pool (default 8). Etherscan KeyRotator is process-shared
    via per-call clients with min-interval; 429s already backoff inside ingest.
    Each worker opens its own store handle so HTTP clients stay thread-local.
    """
    settings = settings or load_settings()
    store = store or open_store(settings)
    workers = max(1, min(int(workers or 1), 32))
    max_scans = max(0, int(max_scans or 0))
    if max_scans <= 0:
        return []
    chunk = max(workers, int(batch_size or workers * 2))
    out: list[tuple[str, Any]] = []
    scanned = 0
    started = time.monotonic()

    while scanned < max_scans:
        now = time.monotonic()
        if deadline_monotonic is not None and now >= deadline_monotonic:
            break
        remaining = max_scans - scanned
        # After the first batch, leave headroom so in-flight Lane A work can
        # finish before the Actions job timeout. Scale headroom for short
        # deadlines (tests / manual runs) so we do not soft-stop immediately.
        if deadline_monotonic is not None and scanned > 0:
            left = deadline_monotonic - now
            budget = max(1.0, deadline_monotonic - started)
            headroom = min(90.0, max(5.0, budget * 0.05))
            if left < headroom:
                break
        claim_n = min(chunk, remaining)
        claimed = store.claim_pending(claim_n, settings.worker_id)
        if not claimed:
            break

        def _work(row: dict[str, Any]) -> tuple[str, Any]:
            addr = str(row.get("address") or "")
            local_store = open_store(settings)
            try:
                result = run_one(
                    addr,
                    settings=settings,
                    store=local_store,
                    tvl_usd=_as_float(row.get("tvl_usd")),
                )
                return addr, {
                    "address": addr,
                    "bucket": result.bucket,
                    "heat": result.heat,
                    "dropped": result.dropped,
                    "drop_reason": result.drop_reason,
                    "funds_usd": result.funds_usd,
                    "contract_class": result.contract_class,
                    "known_safe": result.known_safe,
                    "deployed_block": row.get("deployed_block"),
                    "heat_breakdown": dict(result.heat_breakdown or {}),
                    "engine_leads": list(result.engine_leads or []),
                    "confirmed_findings": list(result.confirmed_findings or []),
                    "engine_timing": dict(result.engine_timing or {}),
                    "notes": list(result.notes or [])[:12],
                }
            except Exception as exc:  # noqa: BLE001 — keep draining siblings
                return addr, {"address": addr, "error": str(exc)[:200], "deployed_block": row.get("deployed_block")}

        if workers == 1 or len(claimed) == 1:
            for row in claimed:
                out.append(_work(row))
        else:
            with ThreadPoolExecutor(max_workers=min(workers, len(claimed))) as pool:
                futs = [pool.submit(_work, row) for row in claimed]
                for fut in as_completed(futs):
                    out.append(fut.result())
        scanned += len(claimed)
        # Brief pause between batches so Alchemy/Etherscan recover after bursts.
        time.sleep(0.25)
    return out


def _ingest(
    address: str,
    *,
    settings: Settings,
    source_path: Optional[Path],
    source_text: Optional[str],
    bytecode: str,
) -> tuple[SourceArtifact, str, Optional[Path], bool, str]:
    """Return (artifact, bytecode, source_dir, incomplete, incomplete_reason)."""
    if source_path:
        p = Path(source_path)
        if p.is_file():
            text = p.read_text(encoding="utf-8", errors="replace")
            lang = "vyper" if p.suffix == ".vy" else "solidity"
            art = SourceArtifact(
                kind="source", language=lang, content=text,
                src_confidence="high", verified_match="exact", tool="local",
                notes=["local source (--source); treated as verified for dry-run"],
            )
            dest = settings.work_dir / "sources" / address
            art, src_dir = materialize_source(art, dest)
            return art, bytecode, src_dir, False, ""
        if p.is_dir():
            files = list(p.rglob("*.sol")) + list(p.rglob("*.vy"))
            text = "\n\n".join(f.read_text(encoding="utf-8", errors="replace") for f in files[:40])
            art = SourceArtifact(
                kind="source", language="solidity", content=text,
                src_confidence="high", verified_match="exact", tool="local",
                notes=["local source directory"],
            )
            return art, bytecode, p, False, ""

    if source_text:
        art = SourceArtifact(
            kind="source", language="solidity", content=source_text,
            src_confidence="high", verified_match="exact", tool="local",
        )
        dest = settings.work_dir / "sources" / address
        art, src_dir = materialize_source(art, dest)
        return art, bytecode, src_dir, False, ""

    code = bytecode
    if settings.eth_rpc_url and not code:
        try:
            code = fetch_rpc_code(settings.eth_rpc_url, address)
        except Exception as exc:  # noqa: BLE001 — read-only lookup; continue without code
            code = ""
            _ = exc

    if settings.etherscan_api_keys:
        client = EtherscanClient(settings.etherscan_api_keys, min_interval_s=settings.etherscan_min_interval_s)
        try:
            raw = client.get_source(address)
            art = parse_source_result(address, raw)
            if not code:
                try:
                    code = client.get_code(address)
                except RateLimitError as exc:
                    art.notes.append("eth_getCode rate-limited: %s" % exc)
                except IngestError:
                    pass
            impl_addr = art.implementation
            incomplete = False
            incomplete_reason = ""
            # Resolve implementation *before* decompile fallback so IR lifts impl source.
            if impl_addr:
                impl, impl_err = _fetch_impl(client, impl_addr)
                if impl is not None and impl.content:
                    impl.notes.append("resolved EIP-1967/etherscan implementation %s" % impl_addr)
                    art = select_ir_artifact(art, impl)
                else:
                    art.notes.append(
                        "implementation source fetch failed (%s); not treating proxy-only as a full surface"
                        % (impl_err or "empty")
                    )
                    incomplete = True
                    incomplete_reason = "implementation fetch failed for %s" % impl_addr
            if art.src_confidence == "low" or art.kind == "decompile" or not art.content:
                stub = decompile(address, code)
                if impl_addr:
                    stub.is_proxy = True
                    stub.implementation = impl_addr
                    stub.notes.append("decompile fallback; implementation %s source unavailable" % impl_addr)
                art = stub
            dest = settings.work_dir / "sources" / address
            art, src_dir = materialize_source(art, dest)
            return art, code, src_dir, incomplete, incomplete_reason
        except RateLimitError as exc:
            stub = decompile(address, code)
            stub.notes.append(
                "etherscan rate-limited after retries: %s — not a confirmed empty contract" % exc
            )
            return stub, code, None, True, "etherscan rate-limited"
        except IngestError as exc:
            stub = decompile(address, code)
            stub.notes.append("etherscan ingest failed: %s" % exc)
            return stub, code, None, True, "etherscan ingest failed"

    stub = decompile(address, code)
    stub.notes.append("no ETHERSCAN_API_KEYS and no --source; low-confidence stub")
    return stub, code, None, False, ""


def _fetch_impl(client: EtherscanClient, impl_addr: str) -> tuple[Optional[SourceArtifact], str]:
    last = ""
    for attempt in range(3):
        try:
            impl_raw = client.get_source(impl_addr)
            return parse_source_result(impl_addr, impl_raw), ""
        except RateLimitError as exc:
            last = str(exc)
            time.sleep(min(8.0, 1.5 * (attempt + 1)))
        except IngestError as exc:
            return None, str(exc)
    return None, last or "implementation fetch failed"


def _source_fingerprint(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="replace")).hexdigest()


def _as_float(v: object) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _flags_from_invariant_dicts(rows: list[dict[str, Any]]) -> tuple[bool, bool]:
    privileged = any(
        (r.get("status") or "").lower() == "failed"
        and str(r.get("id") or "").startswith("privileged-")
        for r in rows
    )
    eoa_admin = False
    for r in rows:
        if r.get("id") == "roles-owner":
            extras = r.get("extras") or {}
            if isinstance(extras, dict) and extras.get("kind") == "eoa":
                eoa_admin = True
    return privileged, eoa_admin
