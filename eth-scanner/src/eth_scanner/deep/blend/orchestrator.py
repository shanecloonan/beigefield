"""One orchestrator for Ityfuzz, Halmos, Medusa, and Echidna.

Halmos runs beside the fork lane. Medusa, Echidna, and Ityfuzz share one
local anvil and run one after another. setUp or compile failures are skips.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from eth_scanner.deep.blend.fixtures import FIXTURES, logs_for
from eth_scanner.deep.blend.parse import parse_engine_log
from eth_scanner.deep.blend.receipt import receipt_from_hits
from eth_scanner.deep.blend.versions import BLEND_ENGINES, FORK_ENGINES, SYMBOLIC_ENGINES, pin_version

Runner = Callable[[dict[str, Any]], "EngineOutput"]


@dataclass
class EngineOutput:
    engine: str
    status: str
    note: str = ""
    log: str = ""
    duration_ms: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "id": self.engine,
            "status": self.status,
            "note": self.note,
            "version_pin": pin_version(self.engine),
            "duration_ms": self.duration_ms,
        }


def _output_from_log(engine: str, log: str, *, note: str = "", duration_ms: int = 0) -> EngineOutput:
    status, _hits = parse_engine_log(engine, log)
    if status == "skipped":
        return EngineOutput(engine, "skipped", note=note or "compile or setUp skipped", log=log, duration_ms=duration_ms)
    return EngineOutput(engine, "ok", note=note, log=log, duration_ms=duration_ms)


def schedule(runners: dict[str, Runner], ctx: Optional[dict[str, Any]] = None) -> list[EngineOutput]:
    """Halmos in parallel. Fork engines sequential so they share one anvil."""
    context = dict(ctx or {})

    def fork_lane() -> list[EngineOutput]:
        out: list[EngineOutput] = []
        for name in FORK_ENGINES:
            fn = runners.get(name)
            if fn is None:
                out.append(EngineOutput(name, "skipped", note="runner missing"))
                continue
            out.append(fn(context))
        return out

    def symbolic_lane() -> list[EngineOutput]:
        out: list[EngineOutput] = []
        for name in SYMBOLIC_ENGINES:
            fn = runners.get(name)
            if fn is None:
                out.append(EngineOutput(name, "skipped", note="runner missing"))
                continue
            out.append(fn(context))
        return out

    with ThreadPoolExecutor(max_workers=2) as pool:
        fork_job = pool.submit(fork_lane)
        symbolic_job = pool.submit(symbolic_lane)
        return fork_job.result() + symbolic_job.result()


def _hits_and_engines(outputs: list[EngineOutput]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    hits: list[dict[str, Any]] = []
    engines: list[dict[str, Any]] = []
    for output in outputs:
        status, rows = parse_engine_log(output.engine, output.log)
        if output.status == "skipped" or status == "skipped":
            output.status = "skipped"
            rows = []
        hits.extend(rows)
        engines.append(output.as_dict())
    return hits, engines


def _receipt_for_outputs(
    outputs: list[EngineOutput],
    *,
    address: str,
    funds_usd: Optional[float],
    contract_name: str,
    contracts: list[str],
    list_id: Optional[str],
    fixture: Optional[str],
    source: str = "",
    prepared: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    hits, engines = _hits_and_engines(outputs)
    report = receipt_from_hits(
        hits,
        engines=engines,
        address=address,
        funds_usd=funds_usd,
        contract_name=contract_name,
        contracts=contracts,
        list_id=list_id,
        fixture=fixture,
    )
    from eth_scanner.deep.blend.adapt import apply_adaptations
    from eth_scanner.deep.blend.ensemble import finalize_ensemble
    report = apply_adaptations(report, fixture=fixture)
    return finalize_ensemble(
        report,
        prepared=prepared,
        source=source,
        contract_name=contract_name,
    )


def _outputs_from_logs(logs: dict[str, str]) -> list[EngineOutput]:
    outputs: list[EngineOutput] = []
    for name in BLEND_ENGINES:
        if name not in logs:
            outputs.append(EngineOutput(name, "skipped", note="no log"))
            continue
        outputs.append(_output_from_log(name, logs[name]))
    return outputs


def _skip_all(note: str) -> list[EngineOutput]:
    return [EngineOutput(name, "skipped", note=note) for name in BLEND_ENGINES]


def _default_runners(
    project: Optional[Path],
    rpc: str,
    *,
    address: str = "",
    timeout_s: int = 30,
) -> dict[str, Runner]:
    """Shell out to the pinned binaries. Missing tools skip. No broadcast."""
    from eth_scanner.deep.blend.invoke import invoke_engine

    def make(engine: str) -> Runner:
        def run(_ctx: dict[str, Any]) -> EngineOutput:
            if project is None:
                return EngineOutput(engine, "skipped", note="no project")
            return invoke_engine(
                engine,
                project=project,
                rpc=rpc,
                address=address or str(_ctx.get("address") or ""),
                timeout_s=timeout_s,
            )
        return run

    return {name: make(name) for name in ("medusa", "echidna", "halmos", "ityfuzz")}


def _journal_for(
    store: Any,
    *,
    address: str,
    funds_usd: Optional[float],
    contract_name: str,
    list_id: Optional[str],
    discovery_source: str,
):
    from eth_scanner.deep.blend.journal import BlendJournal
    return BlendJournal.open(
        store,
        address=address,
        funds_usd=funds_usd,
        contract_name=contract_name,
        list_id=list_id,
        discovery_source=discovery_source or "blend",
    )


def _persist_replay(journal: Any, report: dict[str, Any]) -> dict[str, Any]:
    """Write each computed layer. Used when the run is a fixture or a log replay."""
    layers = report.get("layers") if isinstance(report.get("layers"), dict) else {}
    for name in ("facts", "spec", "symbolic", "fuzz", "mutation", "fusion"):
        block = layers.get(name) if isinstance(layers.get(name), dict) else {
            "status": "skipped",
            "heat_contribution": 0,
            "label": "evidence only",
        }
        journal.stage(name, block, status=str(block.get("status") or "ok"))
    adaptations = report.get("adaptations") if isinstance(report.get("adaptations"), dict) else {}
    for name, block in adaptations.items():
        payload = dict(block) if isinstance(block, dict) else {"heat_contribution": 0}
        payload["heat_contribution"] = 0
        payload.setdefault("label", "evidence only")
        journal.stage("adapt-%s" % name, payload, status="ok")
    journal.finish(report)
    report["persistence"] = journal.summary()
    return report


def run_blend(
    *,
    address: str = "",
    funds_usd: Optional[float] = None,
    contract_name: str = "",
    contracts: Optional[list[str]] = None,
    list_id: Optional[str] = None,
    fixture: Optional[str] = None,
    logs: Optional[dict[str, str]] = None,
    runners: Optional[dict[str, Runner]] = None,
    fork_url: str = "",
    source: str = "",
    timeout_s: int = 90,
    store: Any = None,
    discovery_source: str = "blend",
) -> dict[str, Any]:
    """Run the gauntlet. Each layer is persisted before the next one starts.

    Heat still moves only through the caller-profit gate. A tool that fails
    to compile or start is a skip. A failed store write is not a skip.
    """
    from eth_scanner.deep.blend.journal import PersistError

    budget_s = max(10, int(timeout_s or 30))
    if fixture:
        spec_row = FIXTURES.get(fixture)
        if spec_row is None:
            raise ValueError("unknown fixture %s" % fixture)
        address = address or str(spec_row["address"])
        funds_usd = float(spec_row["funds_usd"]) if funds_usd is None else funds_usd
        contract_name = contract_name or str(spec_row["contract_name"])
    journal = _journal_for(
        store,
        address=address,
        funds_usd=funds_usd,
        contract_name=contract_name,
        list_id=list_id,
        discovery_source=discovery_source,
    )
    try:
        journal.open_run(status="running")
        journal.stage("intake", {
            "address": address,
            "chain": "ethereum",
            "discovery_source": discovery_source,
            "funds_usd": funds_usd,
            "list_id": list_id,
            "contract_name": contract_name,
            "fixture": fixture,
            "heat_contribution": 0,
            "label": "evidence only",
            "bug_classes": [],
        })
        if fixture:
            spec = FIXTURES.get(fixture)
            if spec is None:
                raise ValueError("unknown fixture %s" % fixture)
            outputs = _outputs_from_logs(logs_for(spec))
            report = _receipt_for_outputs(
                outputs,
                address=str(spec["address"]),
                funds_usd=float(spec["funds_usd"]),
                contract_name=str(spec["contract_name"]),
                contracts=list(spec["contracts"]),
                list_id=list_id,
                fixture=fixture,
                source="",
            )
            return _persist_replay(journal, report)
        if logs is not None:
            outputs = _outputs_from_logs(logs)
            report = _receipt_for_outputs(
                outputs,
                address=address,
                funds_usd=funds_usd,
                contract_name=contract_name,
                contracts=list(contracts or []),
                list_id=list_id,
                fixture=None,
                source=source,
            )
            return _persist_replay(journal, report)
        if runners is not None:
            outputs = schedule(runners, {"fork_url": fork_url, "address": address})
            report = _receipt_for_outputs(
                outputs,
                address=address,
                funds_usd=funds_usd,
                contract_name=contract_name,
                contracts=list(contracts or []),
                list_id=list_id,
                fixture=None,
                source=source,
            )
            return _persist_replay(journal, report)
        if not source and not contracts:
            outputs = _skip_all("no verified source — compile not attempted")
            report = _receipt_for_outputs(
                outputs,
                address=address,
                funds_usd=funds_usd,
                contract_name=contract_name,
                contracts=[],
                list_id=list_id,
                fixture=None,
                source="",
            )
            return _persist_replay(journal, report)
        return _run_live(
            journal,
            address=address,
            funds_usd=funds_usd,
            contract_name=contract_name,
            contracts=list(contracts or ([contract_name] if contract_name else [])),
            list_id=list_id,
            fork_url=fork_url,
            source=source,
            timeout_s=budget_s,
        )
    except PersistError:
        raise
    except Exception as exc:
        journal.fail(str(exc)[:400])
        raise


def _trace_seeds(address: str) -> dict[str, Any]:
    """Historical calldata for the harness. Empty when the RPC cannot trace."""
    import os

    from eth_scanner.chain.trace_seeds import collect_seeds

    try:
        return collect_seeds(address, os.environ.get("ETH_RPC_URL") or "")
    except Exception as exc:  # noqa: BLE001 — a seed failure must not stop the scan
        return {
            "status": "degraded",
            "heat_contribution": 0,
            "label": "evidence only",
            "note": "trace seeds skipped: %s" % str(exc)[:160],
            "seeds": [],
            "sequences": [],
            "degraded": True,
        }


def _storage_state(address: str, fork_url: str, seeds: dict[str, Any]) -> dict[str, Any]:
    """Copy traced slots onto the local anvil. Empty when the RPC cannot read them."""
    import os

    from eth_scanner.chain.storage_fidelity import load_storage

    hashes = []
    for sequence in seeds.get("sequences") or []:
        if isinstance(sequence, dict) and sequence.get("tx"):
            hashes.append(str(sequence["tx"]))
    try:
        return load_storage(
            address,
            os.environ.get("ETH_RPC_URL") or "",
            tx_hashes=hashes,
            local_rpc_url=fork_url or "",
        )
    except Exception as exc:  # noqa: BLE001 — storage preload must not stop the scan
        return {
            "status": "degraded",
            "heat_contribution": 0,
            "label": "evidence only",
            "note": "storage preload skipped: %s" % str(exc)[:160],
            "slots": [],
            "applied_local": False,
            "degraded": True,
        }


def _run_live(
    journal: Any,
    *,
    address: str,
    funds_usd: Optional[float],
    contract_name: str,
    contracts: list[str],
    list_id: Optional[str],
    fork_url: str,
    source: str,
    timeout_s: int,
) -> dict[str, Any]:
    """Facts seed the spec, the spec shapes the harness, then symbolic and fuzz."""
    import tempfile

    from eth_scanner.deep.blend.ensemble.facts import collect_facts
    from eth_scanner.deep.blend.ensemble.fuzz_foundry import run_foundry_invariant
    from eth_scanner.deep.blend.ensemble.mutation import run_mutation
    from eth_scanner.deep.blend.ensemble.spec import build_spec, try_scribble
    from eth_scanner.deep.blend.ensemble.symbolic import run_smtchecker
    from eth_scanner.deep.blend.harness import write_project
    from eth_scanner.deep.blend.invoke import run_campaign

    limit = max(2, min(8, int(timeout_s)))
    facts = collect_facts(source, contract_name, live=True, timeout_s=limit)
    journal.stage("facts", facts, status=str(facts.get("status") or "ok"))
    trace_seeds = _trace_seeds(address)
    journal.stage("trace-seeds", trace_seeds, status=str(trace_seeds.get("status") or "skipped"))
    spec = build_spec(facts)
    journal.stage("spec", spec, status="ok")
    label = "".join(ch for ch in (contract_name or "Target") if ch.isalnum() or ch == "_") or "Target"
    with tempfile.TemporaryDirectory(prefix="blend-") as tmp:
        project = write_project(Path(tmp), [{
            "name": label,
            "source": source,
            "address": address,
        }], facts=facts, properties=list(spec.get("selected") or []),
            seeds=list(trace_seeds.get("seeds") or []),
            sequences=list(trace_seeds.get("sequences") or []))
        storage = _storage_state(address, fork_url, trace_seeds)
        from eth_scanner.chain.storage_fidelity import write_evidence
        write_evidence(project, storage)
        journal.stage("storage-fidelity", storage, status=str(storage.get("status") or "skipped"))
        scribble = try_scribble(project, timeout_s=limit)
        spec["scribble"] = scribble
        # Replace the spec row now that Scribble has either instrumented or skipped.
        journal.stage("spec", spec, status=str(scribble.get("status") or "ok"))
        smt = run_smtchecker(project, live=True, timeout_s=limit)
        symbolic = {
            "status": smt.get("status") or "skipped",
            "note": smt.get("note") or "",
            "heat_contribution": 0,
            "label": "evidence only",
            "smtchecker": smt,
            "findings": list(smt.get("findings") or []),
        }
        journal.stage("symbolic", symbolic, status=str(symbolic.get("status") or "skipped"))
        outputs = run_campaign(
            project,
            address=address,
            fork_url=fork_url,
            timeout_s=timeout_s,
            journal=journal,
        )
        foundry = run_foundry_invariant(project, live=True, timeout_s=limit)
        journal.stage("fuzz-foundry", foundry, status=str(foundry.get("status") or "skipped"))
        mutation = run_mutation(
            list(spec.get("selected") or []),
            project=project,
            live=True,
            timeout_s=limit,
        )
        journal.stage("mutation", mutation, status="ok")
    prepared = {
        "facts": facts,
        "spec": spec,
        "symbolic": symbolic,
        "fuzz": {
            "status": "ok",
            "heat_contribution": 0,
            "label": "evidence only",
            "foundry": foundry,
            "seeded_properties": list(spec.get("selected") or []),
            "findings": list(foundry.get("findings") or []),
        },
        "mutation": mutation,
    }
    report = _receipt_for_outputs(
        outputs,
        address=address,
        funds_usd=funds_usd,
        contract_name=contract_name,
        contracts=contracts,
        list_id=list_id,
        fixture=None,
        source=source,
        prepared=prepared,
    )
    adaptations = report.get("adaptations") if isinstance(report.get("adaptations"), dict) else {}
    for name, block in adaptations.items():
        payload = dict(block) if isinstance(block, dict) else {"heat_contribution": 0}
        payload["heat_contribution"] = 0
        payload.setdefault("label", "evidence only")
        journal.stage("adapt-%s" % name, payload, status="ok")
    fusion = (report.get("layers") or {}).get("fusion") if isinstance(report.get("layers"), dict) else {}
    journal.stage("fusion", fusion if isinstance(fusion, dict) else {"heat_contribution": 0, "label": "evidence only"})
    journal.finish(report)
    report["persistence"] = journal.summary()
    return report
