"""CLI: lane-a, lane-b, enqueue, surface, list, receipt, research.

Defensive analysis only. No exploit / PoC / live fund-moving commands.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

from eth_scanner.config import Settings, load_settings
from eth_scanner.heuristics.invariant_pass import main as surface_main
from eth_scanner.lane_a import worker as lane_a
from eth_scanner.lane_b import worker as lane_b
from eth_scanner.receipt import default_receipt_dir, pick_source_artifact, write_run_receipt
from eth_scanner.store.supabase import normalize_address, open_store
from eth_scanner.types import FunnelResult, to_plain


def _add_receipt_flags(sp: argparse.ArgumentParser) -> None:
    sp.add_argument(
        "--receipt",
        help="write this Markdown receipt file (single address) or a directory of .md files",
    )
    sp.add_argument(
        "--receipt-dir",
        help="directory for Markdown receipts (default: <work>/receipts/)",
    )
    sp.add_argument(
        "--no-receipt",
        action="store_true",
        help="skip writing a Markdown receipt",
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    p = argparse.ArgumentParser(
        prog="eth-scanner",
        description="Ethereum-only defensive invariant scanner (Lane A/B). "
                    "Emits buckets, never a human verdict. No PoCs.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("lane-a", help="S0–S5 cheap skim + S6 gate")
    a.add_argument("--address", action="append", default=[], help="0x… (repeatable)")
    a.add_argument("--file", help="text file of addresses, one per line")
    a.add_argument("--source", help="local .sol/.vy file or directory (dry-run / no Etherscan)")
    a.add_argument("--tvl", type=float, default=None, help="TVL USD override")
    a.add_argument("--claim", type=int, default=0, help="claim N pending rows from the store")
    a.add_argument("--dry-run", action="store_true", help="force local work/ store")
    _add_receipt_flags(a)

    b = sub.add_parser("lane-b", help="S7 on lane-b-queue + manual-review")
    b.add_argument("--address", action="append", default=[], help="0x… (repeatable)")
    b.add_argument("--source", help="optional local source for heuristic re-scan")
    b.add_argument("--tvl", type=float, default=None)
    b.add_argument("--claim", type=int, default=5)
    b.add_argument("--dry-run", action="store_true")
    _add_receipt_flags(b)

    e = sub.add_parser("enqueue", help="upsert addresses as pending targets")
    e.add_argument("addresses", nargs="+")
    e.add_argument("--tvl", type=float, default=None)
    e.add_argument("--dry-run", action="store_true")

    ls = sub.add_parser("list", help="list targets / results")
    ls.add_argument("--bucket", default=None)
    ls.add_argument("--results", action="store_true")
    ls.add_argument("--dry-run", action="store_true")

    rec = sub.add_parser("receipt", help="rebuild a Markdown receipt from the store")
    rec.add_argument("--address", required=True, help="0x…")
    rec.add_argument("--lane", default="A", choices=("A", "B", "a", "b"))
    rec.add_argument("--receipt", help="write this .md file")
    rec.add_argument("--receipt-dir", help="directory for the .md (default: <work>/receipts/)")
    rec.add_argument("--dry-run", action="store_true")

    sub.add_parser("surface", help="run invariant_pass heuristics (passthrough)")
    sub.add_parser("research", help="Phase 2 research audit stack (defensive; see eth_scanner.research)")

    deep = sub.add_parser(
        "deep",
        help="Phase A deep engines (Slither/Aderyn/Mythril|Halmos) on lane-b-queue",
    )
    deep.add_argument("--address", action="append", default=[], help="0x… (repeatable)")
    deep.add_argument("--source", help="local Solidity file (skips Etherscan)")
    deep.add_argument("--claim", type=int, default=0, help="claim N lane-b / manual-review rows")
    deep.add_argument(
        "--engines",
        default="slither,aderyn,mythril,halmos",
        help="comma list of engines to attempt",
    )
    deep.add_argument("--timeout", type=int, default=90, help="per-engine timeout seconds")
    deep.add_argument("--json", action="store_true", help="print JSON report(s)")
    deep.add_argument("--dry-run", action="store_true")

    fp = sub.add_parser(
        "fork-props",
        help="Phase B read-only fork/eth_call properties (held|violated; no attack sequences)",
    )
    fp.add_argument("--address", required=True, help="0x…")
    fp.add_argument("--class", dest="contract_class", default="vault", help="contract class")
    fp.add_argument("--forge", action="store_true", help="also run defensive Foundry mock suite if forge is installed")
    fp.add_argument("--timeout", type=int, default=60)
    fp.add_argument("--json", action="store_true")
    fp.add_argument("--dry-run", action="store_true")

    pg = sub.add_parser(
        "protocol-graph",
        help="Phase C protocol context graph + risk factors (read-only)",
    )
    pg.add_argument("--address", required=True, help="0x…")
    pg.add_argument("--source", help="optional local Solidity for static edges")
    pg.add_argument("--class", dest="contract_class", default="unknown")
    pg.add_argument("--funds", type=float, default=None, help="funds USD for weighting")
    pg.add_argument("--json", action="store_true")
    pg.add_argument("--dry-run", action="store_true")

    ai = sub.add_parser(
        "explain",
        help="Phase E optional LLM triage note (skipped without API key; never adds heat)",
    )
    ai.add_argument("--finding-json", required=True, help="path to a finding JSON object")
    ai.add_argument("--address", default="")
    ai.add_argument("--json", action="store_true")
    ai.add_argument("--dry-run", action="store_true")

    mon = sub.add_parser(
        "monitor",
        help="Seed recent deployments + upgrade/funds-delta watch (read-only)",
    )
    mon.add_argument("--limit", type=int, default=1000, help="max creates to discover/enqueue (default 1000)")
    mon.add_argument("--persist", action="store_true", help="write alerts to eth_scan_alerts when remote store")
    mon.add_argument("--no-discover", action="store_true", help="skip recent-deploy seeding (legacy watchlist only)")
    mon.add_argument(
        "--lookback-hours",
        type=int,
        default=2,
        help="dense RPC lookback for creates since last run (default 2h)",
    )
    mon.add_argument("--max-blocks", type=int, default=800, help="max blocks to walk during discovery")
    mon.add_argument(
        "--scan",
        type=int,
        default=1000,
        help="max Lane A scans after seeding; drains pending until empty/deadline (default 1000)",
    )
    mon.add_argument(
        "--workers",
        type=int,
        default=8,
        help="parallel Lane A workers (default 8; respects Etherscan/Alchemy pacing)",
    )
    mon.add_argument(
        "--deadline-minutes",
        type=float,
        default=40.0,
        help="stop claiming new scan batches this many minutes after start (default 40)",
    )
    mon.add_argument(
        "--allow-unverified",
        action="store_true",
        help="keep unverified creates even when ETHERSCAN_API_KEYS is set",
    )
    mon.add_argument("--json", action="store_true")
    mon.add_argument("--dry-run", action="store_true")

    disc = sub.add_parser(
        "discover",
        help="Seed queue from recent mainnet contract creations (read-only)",
    )
    disc.add_argument("--lookback-hours", type=int, default=2)
    disc.add_argument("--max-blocks", type=int, default=800)
    disc.add_argument("--max-results", type=int, default=1000)
    disc.add_argument("--enqueue", action="store_true", help="upsert discoveries as pending targets")
    disc.add_argument("--allow-unverified", action="store_true", help="keep creates even when not verified")
    disc.add_argument("--json", action="store_true")
    disc.add_argument("--dry-run", action="store_true")

    args, rest = p.parse_known_args(argv)
    if args.cmd == "surface":
        return surface_main(rest)
    if args.cmd == "research":
        from eth_scanner.research.cli import main as research_main
        return research_main(rest)

    settings = load_settings()
    if getattr(args, "dry_run", False):
        settings.dry_run = True
    store = open_store(settings)

    if args.cmd == "deep":
        from eth_scanner.deep.worker import run_deep_claim, run_deep_one
        engines = [e.strip() for e in str(args.engines or "").split(",") if e.strip()]
        reports: list[dict[str, Any]] = []
        source_text: Optional[str] = None
        if args.source:
            source_text = Path(args.source).read_text(encoding="utf-8", errors="replace")
        if args.claim and args.claim > 0:
            reports.extend(run_deep_claim(
                limit=int(args.claim),
                settings=settings,
                store=store,
                engines=engines,
                timeout_s=int(args.timeout),
            ))
        for raw in args.address:
            reports.append(run_deep_one(
                raw,
                settings=settings,
                store=store,
                source_text=source_text,
                engines=engines,
                timeout_s=int(args.timeout),
            ))
        if not reports:
            print("deep: pass --claim N and/or --address 0x…", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(reports if len(reports) > 1 else reports[0], indent=2))
        else:
            for rep in reports:
                print(
                    "%s status=%s findings=%d multi_engine=%s"
                    % (
                        rep.get("address"),
                        rep.get("status"),
                        len(rep.get("findings") or []),
                        (rep.get("agreement") or {}).get("multi_engine_clusters"),
                    )
                )
        return 0

    if args.cmd == "fork-props":
        from eth_scanner.fork_props.runner import run_fork_properties
        rows = run_fork_properties(
            args.address,
            contract_class=str(args.contract_class or "vault"),
            rpc_url=getattr(settings, "eth_rpc_url", "") or "",
            run_forge=bool(args.forge),
            timeout_s=float(args.timeout),
        )
        payload = [r.to_dict() for r in rows]
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            for r in payload:
                print("%s %s %s — %s" % (r["status"], r["id"], r["severity"], r["evidence"][:120]))
        return 0

    if args.cmd == "protocol-graph":
        from eth_scanner.protocol_graph.builder import build_protocol_graph
        from eth_scanner.protocol_graph.risk import score_graph_risks
        source_text = ""
        if args.source:
            source_text = Path(args.source).read_text(encoding="utf-8", errors="replace")
        graph = build_protocol_graph(
            args.address,
            source=source_text,
            contract_class=str(args.contract_class or "unknown"),
            rpc_url=getattr(settings, "eth_rpc_url", "") or "",
        )
        risks = score_graph_risks(graph, funds_usd=args.funds, source=source_text)
        payload = {"graph": graph.to_dict(), "risks": risks}
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print("nodes=%d edges=%d factors=%d max_likelihood=%s" % (
                len(graph.nodes), len(graph.edges),
                len(risks.get("factors") or []), risks.get("max_likelihood"),
            ))
            for f in risks.get("factors") or []:
                print("- %s (L=%s): %s" % (f.get("id"), f.get("likelihood"), f.get("detail")))
        return 0

    if args.cmd == "explain":
        from eth_scanner.triage_ai.explain import explain_finding
        finding = json.loads(Path(args.finding_json).read_text(encoding="utf-8"))
        out = explain_finding(finding, context={"address": args.address})
        if args.json:
            print(json.dumps(out, indent=2))
        else:
            print("%s: %s" % (out.get("status"), out.get("explanation")))
        return 0 if out.get("status") in {"ok", "skipped"} else 1

    if args.cmd == "discover":
        from eth_scanner.monitor.watch import seed_recent_deployments
        from eth_scanner.discover.recent import discover_recent_deployments
        keys = ",".join(getattr(settings, "etherscan_api_keys", None) or []) or (
            os.environ.get("ETHERSCAN_API_KEYS") or ""
        )
        prefer_verified: Optional[bool] = False if args.allow_unverified else None
        if args.enqueue:
            rows, stats = seed_recent_deployments(
                store,
                rpc_url=getattr(settings, "eth_rpc_url", "") or "",
                etherscan_keys=keys,
                lookback_hours=int(args.lookback_hours),
                max_blocks=int(args.max_blocks),
                max_results=int(args.max_results),
                prefer_verified=prefer_verified,
            )
        else:
            rows, stats = discover_recent_deployments(
                rpc_url=getattr(settings, "eth_rpc_url", "") or "",
                etherscan_keys=keys or (os.environ.get("ETHERSCAN_API_KEYS") or ""),
                lookback_hours=int(args.lookback_hours),
                max_blocks=int(args.max_blocks),
                max_results=int(args.max_results),
                prefer_verified=prefer_verified,
            )
        payload = {
            "stats": stats.to_dict(),
            "enqueued": bool(args.enqueue),
            "contracts": [r.to_dict() for r in rows],
        }
        # Always log summary counts (even with --json on stderr).
        print(
            "discovery creates_found=%d verified_kept=%d unverified_skipped=%d "
            "known_safe_skipped=%d prefer_verified=%s keys=%s kept=%d"
            % (
                stats.creates_found,
                stats.verified_kept,
                stats.unverified_skipped,
                stats.known_safe_skipped,
                stats.prefer_verified,
                stats.keys_configured,
                len(rows),
            ),
            file=sys.stderr,
        )
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print("discovered=%d enqueue=%s" % (len(rows), bool(args.enqueue)))
            for r in payload["contracts"][:20]:
                print("%s block=%s verified=%s name=%s" % (
                    r["address"], r["deployed_block"], r.get("verified"), r.get("contract_name") or "—",
                ))
        return 0

    if args.cmd == "monitor":
        import time as _time
        from eth_scanner.monitor.watch import scan_watchlist
        prefer_verified = False if args.allow_unverified else None
        started = _time.monotonic()
        alerts, disc_stats, discovered = scan_watchlist(
            store,
            rpc_url=getattr(settings, "eth_rpc_url", "") or "",
            limit=int(args.limit),
            seed_discoveries=not bool(args.no_discover),
            lookback_hours=int(args.lookback_hours),
            max_blocks=int(getattr(args, "max_blocks", 800) or 800),
            prefer_verified=prefer_verified,
        )
        scan_results: list[dict[str, Any]] = []
        workers = max(1, int(getattr(args, "workers", 8) or 8))
        deadline_min = float(getattr(args, "deadline_minutes", 40.0) or 40.0)
        deadline = started + max(60.0, deadline_min * 60.0)
        if int(args.scan or 0) > 0:
            drained = lane_a.claim_and_drain(
                max_scans=int(args.scan),
                workers=workers,
                deadline_monotonic=deadline,
                settings=settings,
                store=store,
            )
            scan_results = [row for _addr, row in drained]
        duration_s = round(_time.monotonic() - started, 1)
        if args.persist:
            persist_fn = getattr(store, "save_alerts", None)
            if callable(persist_fn):
                persist_fn([a.to_dict() for a in alerts])
            else:
                print("monitor: store cannot persist alerts", file=sys.stderr)
        summary = {
            "creates_found": disc_stats.creates_found,
            "verified_kept": disc_stats.verified_kept,
            "unverified_skipped": disc_stats.unverified_skipped,
            "known_safe_skipped": disc_stats.known_safe_skipped,
            "prefer_verified": disc_stats.prefer_verified,
            "keys_configured": disc_stats.keys_configured,
            "discovered_enqueued": len(discovered),
            "scanned": len(scan_results),
            "alerts": len(alerts),
            "workers": workers,
            "duration_s": duration_s,
        }
        # Human-readable counts always on stderr for Actions logs.
        print(
            "monitor creates_found=%(creates_found)d verified_kept=%(verified_kept)d "
            "unverified_skipped=%(unverified_skipped)d discovered_enqueued=%(discovered_enqueued)d "
            "scanned=%(scanned)d workers=%(workers)d duration_s=%(duration_s)s "
            "prefer_verified=%(prefer_verified)s keys=%(keys_configured)s"
            % summary,
            file=sys.stderr,
        )
        payload = {
            "summary": summary,
            "discovery_stats": disc_stats.to_dict(),
            "alerts": [a.to_dict() for a in alerts],
            "scans": scan_results,
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(
                "alerts=%d scans=%d creates_found=%d verified_kept=%d unverified_skipped=%d duration_s=%s"
                % (
                    len(alerts),
                    len(scan_results),
                    disc_stats.creates_found,
                    disc_stats.verified_kept,
                    disc_stats.unverified_skipped,
                    duration_s,
                )
            )
            for a in alerts:
                print("%s %s %s" % (a.kind, a.address, a.detail))
            for s in scan_results:
                print(
                    "scan %s bucket=%s heat=%s drop=%s funds=%s"
                    % (s.get("address"), s.get("bucket"), s.get("heat"), s.get("drop_reason"), s.get("funds_usd"))
                )
        return 0

    if args.cmd == "enqueue":
        from eth_scanner.types import Target
        for raw in args.addresses:
            t = Target(address=normalize_address(raw), tvl_usd=args.tvl, status="pending")
            store.upsert_target(t)
            print(t.address)
        print("store=%s" % ("remote" if settings.persist_remote else "dry-run %s" % settings.work_dir), file=sys.stderr)
        return 0

    if args.cmd == "list":
        if args.results:
            rows = store.list_results()
        else:
            rows = store.list_targets(bucket=args.bucket)
        print(json.dumps(rows, indent=2))
        return 0

    if args.cmd == "receipt":
        addr = normalize_address(args.address)
        rows = store.list_results(addr, limit=1)
        if not rows:
            print("receipt: no stored result for %s" % addr, file=sys.stderr)
            return 2
        dest_dir, dest_file = _receipt_dest(args, settings, n_results=1)
        path = write_run_receipt(
            address=addr,
            lane=args.lane.upper(),
            result=rows[0],
            artifact=pick_source_artifact(store.list_artifacts(addr)),
            target=store.get_target(addr),
            dest_dir=dest_dir,
            dest_file=dest_file,
            worker_id=settings.worker_id,
        )
        print(path)
        print("receipt %s" % path, file=sys.stderr)
        return 0

    if args.cmd == "lane-a":
        addrs = list(args.address)
        if args.file:
            addrs.extend(_read_addrs(Path(args.file)))
        source = Path(args.source) if args.source else None
        results = []
        if addrs:
            results = lane_a.run_batch(addrs, settings=settings, store=store, source_path=source, tvl_usd=args.tvl)
        elif args.claim:
            results = lane_a.claim_and_run(args.claim, settings=settings)
        else:
            print("lane-a: pass --address, --file, or --claim N", file=sys.stderr)
            return 2
        paths = _emit_receipts(results, settings, store, args, lane="A")
        _print_results(results, settings, paths)
        return 0

    if args.cmd == "lane-b":
        addrs = list(args.address)
        source_text = Path(args.source).read_text(encoding="utf-8") if args.source else None
        results = []
        if addrs:
            for raw in addrs:
                r = lane_b.run_one(raw, settings=settings, store=store, source_text=source_text, tvl_usd=args.tvl)
                results.append((normalize_address(raw), r))
        else:
            results = lane_b.claim_and_run(args.claim, settings=settings)
        paths = _emit_receipts(results, settings, store, args, lane="B")
        _print_results(results, settings, paths)
        return 0

    p.error("unknown command")
    return 2


def _read_addrs(path: Path) -> list[str]:
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


def _receipt_dest(args: Any, settings: Settings, n_results: int) -> tuple[Optional[Path], Optional[Path]]:
    raw = getattr(args, "receipt", None)
    dest_dir = getattr(args, "receipt_dir", None)
    dest_file: Optional[Path] = None
    if dest_dir:
        return Path(dest_dir), None
    if raw:
        p = Path(raw)
        if n_results > 1 or p.is_dir() or str(raw).endswith(("/", "\\")):
            return p, None
        if p.suffix.lower() == ".md" or n_results == 1:
            return p.parent if str(p.parent) != "" else default_receipt_dir(settings.work_dir), p
        return p, None
    return default_receipt_dir(settings.work_dir), dest_file


def _emit_receipts(results, settings: Settings, store, args: Any, *, lane: str) -> list[Optional[Path]]:
    if getattr(args, "no_receipt", False):
        return [None] * len(results)
    dest_dir, dest_file = _receipt_dest(args, settings, n_results=len(results))
    paths: list[Optional[Path]] = []
    for addr, res in results:
        this_file = dest_file if dest_file is not None and len(results) == 1 else None
        artifact = pick_source_artifact(store.list_artifacts(addr))
        target = store.get_target(addr)
        path = write_run_receipt(
            address=addr,
            lane=lane,
            result=res if isinstance(res, FunnelResult) else res,
            artifact=artifact,
            target=target,
            dest_dir=None if this_file else dest_dir,
            dest_file=this_file,
            worker_id=settings.worker_id,
        )
        paths.append(path)
    return paths


def _print_results(results, settings, paths: Optional[list[Optional[Path]]] = None) -> None:
    payload = []
    paths = paths or [None] * len(results)
    for (addr, res), path in zip(results, paths):
        payload.append({
            "address": addr,
            "bucket": res.bucket,
            "dropped": res.dropped,
            "drop_reason": res.drop_reason,
            "heat": res.heat,
            "src_confidence": res.src_confidence,
            "ir_confidence": res.ir_confidence,
            "value_movers": res.value_movers,
            "contract_class": res.contract_class,
            "scope": res.scope,
            "stage_trace": to_plain(res.stage_trace),
            "notes": res.notes,
            "funds_usd": getattr(res, "funds_usd", None),
            "funds_breakdown": getattr(res, "funds_breakdown", None) or [],
            "funds_status": getattr(res, "funds_status", None),
            "funds_checked_at": getattr(res, "funds_checked_at", None),
            "invariant_results": getattr(res, "invariant_results", None) or [],
            "heat_breakdown": getattr(res, "heat_breakdown", None) or {},
            "known_safe": bool(getattr(res, "known_safe", False)),
            "contract_name": getattr(res, "contract_name", None),
            "receipt_path": str(path) if path else None,
        })
    print(json.dumps(payload, indent=2))
    mode = "supabase" if settings.persist_remote else "dry-run:%s" % settings.work_dir
    print("wrote %d result(s) via %s" % (len(results), mode), file=sys.stderr)
    for path in paths:
        if path:
            print("receipt %s" % path, file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
