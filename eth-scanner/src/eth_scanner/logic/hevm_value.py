"""hevm symbolic check: can a non-owner move value out of a shortlist contract.

hevm is AGPL-3.0. This module does not import it, vendor it, or link it.
It shells out to the unmodified ``hevm symbolic`` binary against a loopback
fork only. A missing binary is a skip. A reachable path is not heat. Heat
is added only when a local eth_call trace shows the non-owner's balance up
and the contract's balance down by more than dust. Calldata is not stored.
"""

from __future__ import annotations

import json
import re
import subprocess
import urllib.request
from typing import Any, Callable, Optional

from eth_scanner.research.symbolic import VALUE_SIGS, hevm_value_argv

PIN = {
    "url": "https://github.com/argotorg/hevm",
    "license": "AGPL-3.0",
    "link": False,
}
DUST = 1000
DEFAULT_TIMEOUT_S = 30
NON_OWNER = "0x000000000000000000000000000000000000bEEF"
_ALT_CALLER = "0x000000000000000000000000000000000000cAFE"
_HEX = re.compile(r"0x[0-9a-fA-F]{8,}")
_HIT = re.compile(r"\[validated\]", re.IGNORECASE)
_TIMEOUT = re.compile(r"\btimed out\b|smt timeout", re.IGNORECASE)
_PROBE_AMOUNT = 10**15

Runner = Callable[[list[str], int], tuple[int, str]]
Confirmer = Callable[[str, str, str, str], Optional[tuple[int, int]]]
CodeReader = Callable[[str, str], str]


def parse_hevm_reachable(text: str) -> bool:
    """True only for a validated assertion hit. A timeout is not a hit."""
    return bool(_HIT.search(text or ""))


def redact(text: str) -> str:
    return _HEX.sub("0x…", text or "")


def trace_deltas(trace: Any, target: str, caller: str) -> tuple[int, int]:
    """ETH or token units that left the target for the caller. No calldata kept."""
    target_l = (target or "").lower()
    caller_l = (caller or "").lower()
    eth_up = 0
    token_up = 0

    def walk(node: Any) -> None:
        nonlocal eth_up, token_up
        if not isinstance(node, dict):
            return
        src = str(node.get("from") or "").lower()
        dst = str(node.get("to") or "").lower()
        value = _int(node.get("value"))
        if src == target_l and dst == caller_l and value > eth_up:
            eth_up = value
        moved = _token_to_caller(str(node.get("input") or ""), caller_l, target_l)
        if src == target_l and moved > token_up:
            token_up = moved
        for child in node.get("calls") or []:
            walk(child)

    if isinstance(trace, dict) and ("pre" in trace or "post" in trace):
        eth_up = _balance_move(trace, target_l, caller_l)
    else:
        walk(trace)
    moved = max(eth_up, token_up)
    return moved, moved if moved else 0


def _balance_move(trace: dict[str, Any], target: str, caller: str) -> int:
    pre = trace.get("pre") if isinstance(trace.get("pre"), dict) else {}
    post = trace.get("post") if isinstance(trace.get("post"), dict) else {}

    def bal(side: dict[str, Any], addr: str) -> Optional[int]:
        row = None
        for key, value in side.items():
            if str(key).lower() == addr and isinstance(value, dict):
                row = value
                break
        if row is None or "balance" not in row:
            return None
        return _int(row.get("balance"))

    before_caller = bal(pre, caller)
    after_caller = bal(post, caller)
    before_target = bal(pre, target)
    after_target = bal(post, target)
    if None in {before_caller, after_caller, before_target, after_target}:
        return 0
    up = int(after_caller) - int(before_caller)
    down = int(before_target) - int(after_target)
    if up > 0 and down > 0:
        return min(up, down)
    return 0


def _token_to_caller(data: str, caller: str, target: str) -> int:
    raw = data.lower()
    if raw.startswith("0x"):
        raw = raw[2:]
    if len(raw) < 8:
        return 0
    selector, rest = raw[:8], raw[8:]
    caller_word = caller[2:].rjust(64, "0") if caller.startswith("0x") else caller.rjust(64, "0")
    target_word = target[2:].rjust(64, "0") if target.startswith("0x") else target.rjust(64, "0")
    if selector == "a9059cbb" and len(rest) >= 128 and rest[:64] == caller_word:
        return _int("0x" + rest[64:128])
    if selector == "23b872dd" and len(rest) >= 192 and rest[:64] == target_word and rest[64:128] == caller_word:
        return _int("0x" + rest[128:192])
    return 0


def _int(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(str(value), 16) if str(value).startswith(("0x", "0X")) else int(value)
    except (TypeError, ValueError):
        return 0


def _clamp(timeout_s: int) -> int:
    try:
        value = int(timeout_s)
    except (TypeError, ValueError):
        value = DEFAULT_TIMEOUT_S
    return max(15, min(45, value))


def _address(value: str) -> str:
    raw = (value or "").strip().lower()
    if raw.startswith("0x"):
        raw = raw[2:]
    if len(raw) != 40 or any(ch not in "0123456789abcdef" for ch in raw):
        raise ValueError("address")
    return "0x" + raw


def _caller(owner: str) -> str:
    if owner and owner.lower() == NON_OWNER.lower():
        return _ALT_CALLER
    return NON_OWNER


def _sigs_for(bytecode: str) -> list[tuple[str, str]]:
    blob = (bytecode or "").lower().removeprefix("0x")
    if not blob:
        return list(VALUE_SIGS)
    return [row for row in VALUE_SIGS if row[1] in blob]


def _default_runner(argv: list[str], timeout: int) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 124, "timed out"
    except OSError:
        return 1, ""
    return proc.returncode, redact((proc.stdout or "") + "\n" + (proc.stderr or ""))[:2000]


def _rpc(url: str, method: str, params: list[Any]) -> Any:
    from eth_scanner.deep.blend.ityfuzz_runner import local_rpc

    if not local_rpc(url):
        raise ValueError("local fork required")
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        body = json.loads(resp.read().decode("utf-8", errors="replace"))
    if body.get("error"):
        raise ValueError("rpc error")
    return body.get("result")


def _probe_data(selector: str, caller: str, target: str) -> str:
    sel = selector.lower()
    amount = hex(_PROBE_AMOUNT)[2:].rjust(64, "0")
    who = caller.lower().removeprefix("0x").rjust(64, "0")
    held = target.lower().removeprefix("0x").rjust(64, "0")
    if sel == "3ccfd60b":
        return "0x" + sel
    if sel in {"2e1a7d4d", "db006a75"}:
        return "0x" + sel + amount
    if sel in {"b460af94", "ba087652"}:
        return "0x" + sel + amount + who + who
    if sel == "23b872dd":
        return "0x" + sel + held + who + amount
    return ""


def _default_confirmer(url: str, target: str, selector: str, caller: str) -> Optional[tuple[int, int]]:
    data = _probe_data(selector, caller, target)
    if not data:
        return None
    try:
        traced = _rpc(
            url,
            "debug_traceCall",
            [{"from": caller, "to": target, "data": data}, "latest", {"tracer": "callTracer"}],
        )
    except (OSError, ValueError, TimeoutError):
        return None
    return trace_deltas(traced, target, caller)


def _default_code(url: str, target: str) -> str:
    try:
        code = _rpc(url, "eth_getCode", [target, "latest"])
    except (OSError, ValueError, TimeoutError):
        return ""
    return code if isinstance(code, str) else ""


def run_hevm_value(
    *,
    address: str,
    on_shortlist: bool = False,
    fork_url: str = "",
    bytecode: str = "",
    owner: str = "",
    timeout_s: int = DEFAULT_TIMEOUT_S,
    output: Optional[str] = None,
    runner: Optional[Runner] = None,
    confirmer: Optional[Confirmer] = None,
    code_reader: Optional[CodeReader] = None,
) -> dict[str, Any]:
    """Symbolic value check for one shortlist contract on a local fork."""
    from eth_scanner.deep.blend.ityfuzz_runner import local_rpc
    from eth_scanner.deep.runners import hevm_bin
    from eth_scanner.heat import evidence_heat

    report: dict[str, Any] = {
        "status": "skipped",
        "address": "",
        "ran": False,
        "confirmed": False,
        "selector": "",
        "attacker_up": 0,
        "target_down": 0,
        "heat": 0,
        "heat_contribution": 0,
        "pin": dict(PIN),
        "note": "",
    }
    try:
        report["address"] = _address(address)
        owner_addr = _address(owner) if owner else ""
    except ValueError:
        report["status"] = "invalid"
        report["note"] = "Address is not 20 bytes of hex."
        return report
    if not on_shortlist:
        report["note"] = "hevm runs only for a shortlist contract."
        return report
    if not local_rpc(fork_url):
        report["note"] = "hevm runs only against a local fork."
        return report
    if output is None and runner is None and hevm_bin() is None:
        report["note"] = "hevm is not installed. The check was not run."
        return report

    caller = _caller(owner_addr)
    code = bytecode
    if not code and output is None:
        code = (code_reader or _default_code)(fork_url, report["address"])
    sigs = _sigs_for(code)
    if code and not sigs:
        report["note"] = "No value-moving selector in the bytecode."
        return report

    budget = _clamp(timeout_s)
    text = output
    hit_sig = ""
    if text is None:
        binary = hevm_bin()
        chosen = runner or _default_runner
        for signature, selector in sigs:
            try:
                argv = hevm_value_argv(
                    binary or "hevm",
                    rpc=fork_url,
                    address=report["address"],
                    caller=caller,
                    signature=signature,
                    timeout_s=min(15, budget),
                )
            except ValueError:
                report["note"] = "hevm runs only against a local fork."
                return report
            code_rc, text = chosen(argv, min(15, budget))
            report["ran"] = True
            if parse_hevm_reachable(text) and not _TIMEOUT.search(text or ""):
                hit_sig = signature
                report["selector"] = signature
                break
            if code_rc == 124 or _TIMEOUT.search(text or ""):
                report["status"] = "timeout"
                report["note"] = "hevm timed out. No heat."
                text = None
                break
            text = None
            budget -= 5
            if budget < 10:
                break
    else:
        report["ran"] = True
        if parse_hevm_reachable(text) and not _TIMEOUT.search(text):
            hit_sig = sigs[0][0]
            report["selector"] = hit_sig

    if report["status"] == "timeout":
        heat, breakdown = evidence_heat(funds_usd=None, invariant_results=[], hevm=report)
        report["heat"] = heat
        report["heat_breakdown"] = _breakdown(breakdown)
        return report

    if not hit_sig:
        report["status"] = "held" if report["ran"] else "skipped"
        report["note"] = "hevm found no validated value path." if report["ran"] else report["note"]
        heat, breakdown = evidence_heat(funds_usd=None, invariant_results=[], hevm=report)
        report["heat"] = heat
        report["heat_breakdown"] = _breakdown(breakdown)
        return report

    selector = dict(VALUE_SIGS).get(hit_sig, "")
    measured = (confirmer or _default_confirmer)(fork_url, report["address"], selector, caller)
    up, down = measured if measured else (0, 0)
    report["attacker_up"] = int(up)
    report["target_down"] = int(down)
    if up > DUST and down > DUST:
        report["confirmed"] = True
        report["status"] = "confirmed"
        report["note"] = "A local call confirmed a non-owner value move on %s." % hit_sig
        invariant = [{
            "id": "non-owner-value",
            "status": "failed",
            "source": "fork-simulation",
            "evidence": report["note"],
        }]
    else:
        report["status"] = "lead"
        report["note"] = "hevm reached %s. The local call did not measure a value move." % hit_sig
        invariant = []
    heat, breakdown = evidence_heat(funds_usd=None, invariant_results=invariant, hevm=report)
    report["heat"] = heat
    report["heat_breakdown"] = _breakdown(breakdown)
    report["note"] = redact(report["note"])
    return report


def _breakdown(breakdown: dict[str, Any]) -> dict[str, Any]:
    return {
        "hevm": breakdown.get("hevm"),
        "invariants_failed": breakdown.get("invariants_failed"),
        "total": breakdown.get("total"),
    }
