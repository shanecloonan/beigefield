"""Shell out to the pinned Ityfuzz, Halmos, Medusa, and Echidna binaries.

Halmos is symbolic and does not take the anvil fork. Medusa, Echidna, and
Ityfuzz share one local anvil and run one after another. A missing binary,
a compile error, or a setUp crash is a skip. Nothing is broadcast. Calldata
stays in the raw log only long enough to parse a property name and a
caller_profit_delta number; the receipt elides calldata.
"""

from __future__ import annotations

import os
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

from eth_scanner.deep.blend.ityfuzz_runner import ityfuzz_argv, ityfuzz_env, local_rpc
from eth_scanner.deep.blend.parse import is_setup_or_compile_failure
from eth_scanner.deep.runners import anvil_bin, echidna_bin, halmos_bin, ityfuzz_bin, medusa_bin

_UNSAFE = ("flashloan", "broadcast", "private-key", "private_key", "sendrawtransaction")


def _which(engine: str) -> Optional[str]:
    return {
        "medusa": medusa_bin(),
        "echidna": echidna_bin(),
        "halmos": halmos_bin(),
        "ityfuzz": ityfuzz_bin(),
    }.get(engine)


def _anvil_wanted() -> bool:
    raw = (os.environ.get("ETH_SCANNER_BLEND_ANVIL") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _free_port() -> int:
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


class LocalAnvil:
    """One loopback anvil. Fork mode only simulates; it does not send transactions."""

    def __init__(self, fork_url: str = ""):
        self.fork_url = (fork_url or "").strip()
        self.url = ""
        self.proc: Optional[subprocess.Popen[str]] = None
        self.note = ""

    def start(self) -> str:
        if local_rpc(self.fork_url):
            self.url = self.fork_url
            self.note = "using the loopback RPC already supplied"
            return self.url
        if not _anvil_wanted():
            self.note = "anvil disabled"
            return ""
        binary = anvil_bin()
        if not binary:
            self.note = "anvil not on PATH"
            return ""
        port = _free_port()
        cmd = [binary, "--host", "127.0.0.1", "--port", str(port), "--silent"]
        if self.fork_url and not local_rpc(self.fork_url):
            # Local fork of a read endpoint. Anvil does not broadcast.
            cmd.extend(["--fork-url", self.fork_url])
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                start_new_session=True,
            )
        except OSError as exc:
            self.note = "anvil failed to start: %s" % str(exc)[:120]
            return ""
        self.url = "http://127.0.0.1:%d" % port
        if not _wait_ready(self.url, self.proc):
            self.stop()
            self.url = ""
            self.note = "anvil did not answer on loopback"
            return ""
        self.note = "anvil loopback"
        return self.url

    def stop(self) -> None:
        proc = self.proc
        self.proc = None
        if proc is None or proc.poll() is not None:
            return
        try:
            os.killpg(proc.pid, 15)
        except OSError:
            proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, 9)
            except OSError:
                proc.kill()


def _wait_ready(url: str, proc: subprocess.Popen[str]) -> bool:
    import json
    import urllib.request

    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []}).encode()
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
        try:
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=1) as resp:
                body = json.loads(resp.read().decode("utf-8", errors="replace"))
            if str(body.get("result") or "").startswith("0x"):
                return True
        except Exception:  # noqa: BLE001
            time.sleep(0.15)
    return False


def _local_block(rpc: str) -> str:
    """Head of the loopback anvil. Falls back to 0, which a fresh anvil accepts."""
    import json
    import urllib.request

    if not local_rpc(rpc):
        return "0"
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_blockNumber",
        "params": [],
    }).encode()
    try:
        req = urllib.request.Request(
            rpc,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
        raw = str(body.get("result") or "0x0")
        return str(int(raw, 16))
    except Exception:  # noqa: BLE001
        return "0"


def _argv(engine: str, binary: str, project: Path, rpc: str, address: str) -> list[str]:
    if engine == "medusa":
        return [binary, "fuzz", "--timeout", "20", "--test-limit", "50", "--workers", "1"]
    if engine == "echidna":
        sol = project / "src" / "ConservationHarness.sol"
        return [
            binary,
            str(sol),
            "--contract",
            "ConservationHarness",
            "--config",
            str(project / "echidna.yaml"),
        ]
    if engine == "halmos":
        return [
            binary,
            "--root",
            str(project),
            "--contract",
            "ConservationHarness",
            "--function",
            "check_no_caller_profit",
            "--solver-timeout-assertion",
            "8000",
            "--loop",
            "1",
        ]
    if engine == "ityfuzz":
        if not local_rpc(rpc):
            raise ValueError("ityfuzz refuses a non-local RPC")
        target = (address or "").strip().lower()
        if not (target.startswith("0x") and len(target) == 42):
            raise ValueError("ityfuzz needs the target address")
        return ityfuzz_argv(binary, [target], rpc, block=_local_block(rpc))
    raise ValueError("unknown engine %s" % engine)


def _refuse(argv: list[str]) -> Optional[str]:
    blob = " ".join(argv).lower()
    for token in _UNSAFE:
        if token in blob:
            return token
    return None


def _per_engine_timeout(timeout_s: int) -> int:
    return max(10, min(40, int(timeout_s or 30)))


def run_campaign(project: Path, *, address: str, fork_url: str, timeout_s: int, journal: Any = None) -> list:
    """Halmos beside the fork lane. Medusa, Echidna, then Ityfuzz on one anvil."""
    from eth_scanner.deep.blend.orchestrator import schedule

    anvil = LocalAnvil(fork_url)
    rpc = anvil.start()
    try:
        def make(engine: str):
            def run(_ctx: dict) -> EngineOutput:
                output = invoke_engine(
                    engine,
                    project=project,
                    rpc=rpc,
                    address=address,
                    timeout_s=timeout_s,
                )
                # Persist this engine before the next fork engine starts.
                if journal is not None:
                    journal.stage("engine-%s" % engine, {
                        "status": output.status,
                        "note": output.note,
                        "heat_contribution": 0,
                        "label": "evidence only",
                        "engine": engine,
                        "findings": [],
                    }, status=output.status if output.status in {"ok", "skipped", "error"} else "ok")
                return output
            return run

        return schedule(
            {name: make(name) for name in ("medusa", "echidna", "ityfuzz", "halmos")},
            {"fork_url": rpc, "address": address},
        )
    finally:
        anvil.stop()


def invoke_engine(
    engine: str,
    *,
    project: Path,
    rpc: str = "",
    address: str = "",
    timeout_s: int = 30,
):
    """Run one pinned binary. Skip on missing tool, unsafe argv, or compile/setUp failure."""
    from eth_scanner.deep.blend.orchestrator import EngineOutput

    binary = _which(engine)
    if not binary:
        return EngineOutput(engine, "skipped", note="%s not on PATH" % engine)
    try:
        argv = _argv(engine, binary, project, rpc, address)
    except ValueError as exc:
        return EngineOutput(engine, "skipped", note=str(exc)[:180])
    blocked = _refuse(argv)
    if blocked:
        return EngineOutput(engine, "skipped", note="refused unsafe argv (%s)" % blocked)
    env = os.environ.copy()
    if engine == "ityfuzz":
        try:
            env = ityfuzz_env(rpc)
        except ValueError as exc:
            return EngineOutput(engine, "skipped", note=str(exc)[:180])
    elif rpc and local_rpc(rpc):
        env["ETH_RPC_URL"] = rpc
    limit = _per_engine_timeout(timeout_s)
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            argv,
            cwd=str(project),
            env=env,
            capture_output=True,
            text=True,
            timeout=limit,
            check=False,
        )
        text = (proc.stdout or "") + "\n" + (proc.stderr or "")
        code = proc.returncode
    except subprocess.TimeoutExpired as exc:
        text = "%s\n%s" % (exc.stdout or "", exc.stderr or "")
        if is_setup_or_compile_failure(text):
            return EngineOutput(engine, "skipped", note="compile or setUp skipped", log="")
        return EngineOutput(
            engine,
            "skipped",
            note="invoked %s; timed out after %ss" % (Path(binary).name, limit),
            log="",
        )
    except OSError as exc:
        return EngineOutput(engine, "skipped", note="invoked %s failed: %s" % (engine, str(exc)[:140]))
    elapsed = int((time.monotonic() - t0) * 1000)
    if is_setup_or_compile_failure(text):
        return EngineOutput(
            engine,
            "skipped",
            note="invoked %s; compile or setUp skipped" % Path(binary).name,
            log="",
            duration_ms=elapsed,
        )
    return EngineOutput(
        engine,
        "ok",
        note="invoked %s exit=%s" % (Path(binary).name, code),
        log=text,
        duration_ms=elapsed,
    )
