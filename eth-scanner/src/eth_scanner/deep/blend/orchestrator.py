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
from eth_scanner.deep.blend.ityfuzz_runner import ityfuzz_argv, local_rpc, resolve_bin
from eth_scanner.deep.blend.parse import parse_engine_log
from eth_scanner.deep.blend.receipt import receipt_from_hits
from eth_scanner.deep.blend.versions import BLEND_ENGINES, FORK_ENGINES, SYMBOLIC_ENGINES, pin_version
from eth_scanner.deep.runners import echidna_bin, halmos_bin, medusa_bin

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
    return apply_adaptations(report, fixture=fixture)


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


def _default_runners(project: Optional[Path], rpc: str) -> dict[str, Runner]:
    """Shell out only when a binary exists. Missing tools skip. No broadcast."""

    def _medusa(_ctx: dict[str, Any]) -> EngineOutput:
        if medusa_bin() is None or project is None:
            return EngineOutput("medusa", "skipped", note="medusa not on PATH" if medusa_bin() is None else "no project")
        return EngineOutput("medusa", "skipped", note="medusa binary present; campaign not started without a built harness")

    def _echidna(_ctx: dict[str, Any]) -> EngineOutput:
        if echidna_bin() is None or project is None:
            return EngineOutput("echidna", "skipped", note="echidna not on PATH" if echidna_bin() is None else "no project")
        return EngineOutput("echidna", "skipped", note="echidna binary present; campaign not started without a built harness")

    def _halmos(_ctx: dict[str, Any]) -> EngineOutput:
        if halmos_bin() is None:
            return EngineOutput("halmos", "skipped", note="halmos not on PATH")
        return EngineOutput("halmos", "skipped", note="halmos binary present; symbolic campaign needs a compiled check_ harness")

    def _ityfuzz(_ctx: dict[str, Any]) -> EngineOutput:
        binary = resolve_bin()
        if not binary:
            return EngineOutput("ityfuzz", "skipped", note="ityfuzz not on PATH")
        if not local_rpc(rpc):
            return EngineOutput("ityfuzz", "skipped", note="ityfuzz skipped — no local anvil fork")
        try:
            ityfuzz_argv(binary, ["0x0000000000000000000000000000000000000001"], rpc)
        except ValueError as exc:
            return EngineOutput("ityfuzz", "skipped", note=str(exc))
        return EngineOutput("ityfuzz", "skipped", note="ityfuzz pinned argv checked; campaign waits for a forked harness")

    return {"medusa": _medusa, "echidna": _echidna, "halmos": _halmos, "ityfuzz": _ityfuzz}


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
) -> dict[str, Any]:
    """Run the four engines, or replay fixture/log input through the same receipt."""
    del timeout_s  # wall clock is owned by each engine runner; fixtures do not block
    if fixture:
        spec = FIXTURES.get(fixture)
        if spec is None:
            raise ValueError("unknown fixture %s" % fixture)
        outputs = _outputs_from_logs(logs_for(spec))
        return _receipt_for_outputs(
            outputs,
            address=str(spec["address"]),
            funds_usd=float(spec["funds_usd"]),
            contract_name=str(spec["contract_name"]),
            contracts=list(spec["contracts"]),
            list_id=list_id,
            fixture=fixture,
        )
    if logs is not None:
        outputs = _outputs_from_logs(logs)
        return _receipt_for_outputs(
            outputs,
            address=address,
            funds_usd=funds_usd,
            contract_name=contract_name,
            contracts=list(contracts or []),
            list_id=list_id,
            fixture=None,
        )
    if runners is not None:
        outputs = schedule(runners, {"fork_url": fork_url, "address": address})
        return _receipt_for_outputs(
            outputs,
            address=address,
            funds_usd=funds_usd,
            contract_name=contract_name,
            contracts=list(contracts or []),
            list_id=list_id,
            fixture=None,
        )
    if not source and not contracts:
        outputs = _skip_all("no verified source — compile not attempted")
        return _receipt_for_outputs(
            outputs,
            address=address,
            funds_usd=funds_usd,
            contract_name=contract_name,
            contracts=[],
            list_id=list_id,
            fixture=None,
        )
    # A source bundle still does not run a campaign when forge is absent.
    # That is a skip, never a finding.
    from eth_scanner.deep.runners import forge_bin
    if not forge_bin():
        outputs = _skip_all("forge not on PATH — harness not compiled")
    else:
        outputs = schedule(_default_runners(Path("."), fork_url), {"fork_url": fork_url})
    return _receipt_for_outputs(
        outputs,
        address=address,
        funds_usd=funds_usd,
        contract_name=contract_name,
        contracts=list(contracts or ([contract_name] if contract_name else [])),
        list_id=list_id,
        fixture=None,
    )
