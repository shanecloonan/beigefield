"""Pyrometer range analysis. Apache-2.0, invoked as a CLI, not vendored.

The static pass asks the installed ``pyrometer`` binary for value ranges.
Only a high-confidence funds-related precision-loss, rounding, or
overflow bound becomes static evidence. Every other range is a lead and
adds no heat. Source lines from the report are not kept.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional

PIN = {
    "url": "https://github.com/nascentxyz/pyrometer",
    "license": "Apache-2.0",
    "link": False,
}

_FUNC = re.compile(r"\bfunction\s+([A-Za-z_][A-Za-z0-9_]*)")
_BOUND = re.compile(
    r'"?(?P<name>[A-Za-z_][A-Za-z0-9_]*)"?\s*(?:∈|in)\s*\[\s*(?P<lo>[^,\]]+?)\s*,\s*(?P<hi>[^\]]+?)\]',
)
_VALUE_FN = frozenset({
    "withdraw", "deposit", "redeem", "mint", "burn", "transfer", "transferfrom",
    "swap", "borrow", "repay", "liquidate", "liquidationcall", "skim", "harvest",
    "claim", "stake", "unstake",
})
_VALUE_NAME = re.compile(
    r"share|asset|amount|balance|price|reserve|debt|collateral|convert",
    re.I,
)
_UINT_MAX = "115792089237316195423570985008687907853269984665640564039457"
_POW = re.compile(r"2\s*(?:\*\*|\^)\s*(\d+)")


def pyrometer_bin() -> Optional[str]:
    override = (os.environ.get("ETH_SCANNER_PYROMETER_BIN") or "").strip()
    if override and Path(override).is_file():
        return override
    return shutil.which("pyrometer")


def run_pyrometer(
    source: str,
    *,
    runner: Optional[Callable[[str], str]] = None,
    which: Optional[Callable[[str], Optional[str]]] = None,
    timeout_s: int = 20,
) -> dict[str, Any]:
    """Range leads for one source. A missing binary is a skip."""
    report: dict[str, Any] = {
        "engine": "pyrometer",
        "evidence_only": True,
        "status": "skipped",
        "ranges": [],
        "heat_contribution": 0,
        "note": "pyrometer is not installed. Ranges were not analyzed.",
    }
    located = which("pyrometer") if which is not None else pyrometer_bin()
    if runner is None and not located:
        return report
    budget = max(5, min(25, int(timeout_s or 20)))
    try:
        raw = runner(source) if runner is not None else _run_cli(source, timeout_s=budget)
    except subprocess.TimeoutExpired:
        report["status"] = "error"
        report["note"] = "pyrometer timed out. No ranges were kept."
        return report
    except Exception as exc:  # noqa: BLE001 — a range crash is not a scan failure
        report["status"] = "error"
        report["note"] = "pyrometer failed (%s). No ranges were kept." % type(exc).__name__
        return report
    ranges = parse_pyrometer(raw)
    report["ranges"] = ranges
    report["status"] = "ok"
    report["heat_contribution"] = sum(int(row.get("weight") or 0) for row in ranges)
    report["note"] = "High-confidence funds ranges are static evidence. Source lines were not kept."
    return report


def parse_pyrometer(raw: str) -> list[dict[str, Any]]:
    """Keep kind, function, and the interval. Drop the underlined source."""
    function = ""
    window: list[str] = []
    kept: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for line in (raw or "").splitlines():
        found = _FUNC.search(line)
        if found:
            function = found.group(1)
        match = _BOUND.search(line)
        if match is None:
            window.append(line)
            window = window[-4:]
            continue
        kind = _kind(match.group("name"), "\n".join(window + [line]))
        window.append(line)
        window = window[-4:]
        if not kind:
            continue
        name = match.group("name")
        lo = _compact(match.group("lo"))
        hi = _compact(match.group("hi"))
        funds = _funds(function, name)
        high = funds and _number(lo) is not None and _number(hi) is not None
        key = (function or name, kind)
        if key in seen:
            continue
        seen.add(key)
        kept.append({
            "kind": kind,
            "function": function[:80],
            "name": name[:80],
            "low": lo[:80],
            "high": hi[:80],
            "confidence": "high" if high else "low",
            "funds_related": funds,
            "weight": 3 if high else 0,
        })
    return kept


def as_static_findings(report: dict[str, Any]) -> list[dict[str, Any]]:
    """The rows that may add heat. Low-confidence ranges stay out."""
    rows = []
    for item in report.get("ranges") or []:
        if int(item.get("weight") or 0) <= 0:
            continue
        rows.append({
            "engine": "pyrometer",
            "rule": str(item.get("kind") or ""),
            "severity": "high",
            "confidence": "high",
            "funds_class": "value",
            "function": str(item.get("function") or ""),
            "evidence": "%s [%s, %s]" % (item.get("name") or "value", item.get("low") or "?", item.get("high") or "?"),
            "generic": False,
        })
    return rows


def _kind(name: str, window: str) -> str:
    text = window or ""
    lower = text.lower()
    matches = list(_BOUND.finditer(text))
    hi = matches[-1].group("hi") if matches else ""
    overflow = "overflow" in lower or "underflow" in lower or _full_range(hi)
    arith = bool(re.search(r"[+*]", text))
    if overflow and (arith or "overflow" in lower or "underflow" in lower):
        return "overflow-bound"
    if "/" in text or "precision" in lower or "truncat" in lower:
        return "precision-loss"
    if not _full_range(hi) and ("round" in lower or _VALUE_NAME.search(name or "")):
        return "rounding-bound"
    return ""


def _funds(function: str, name: str) -> bool:
    if (function or "").lower() in _VALUE_FN:
        return True
    return bool(_VALUE_NAME.search(name or "") or _VALUE_NAME.search(function or ""))


def _full_range(hi: str) -> bool:
    number = _number(hi)
    if number is not None and number >= 2 ** 255:
        return True
    compact = re.sub(r"[\s_]", "", hi or "")
    return compact.startswith(_UINT_MAX) or bool(re.search(r"2\s*(?:\*\*|\^)\s*256", hi or ""))


def _number(text: str) -> Optional[int]:
    raw = re.sub(r"[\s_]", "", text or "")
    if re.fullmatch(r"\d+", raw):
        try:
            return int(raw)
        except ValueError:
            return None
    power = _POW.fullmatch(raw)
    if power:
        exp = int(power.group(1))
        if 0 <= exp <= 256:
            return 2 ** exp
    return None


def _compact(text: str) -> str:
    return " ".join((text or "").split())


def _run_cli(source: str, *, timeout_s: int) -> str:
    exe = pyrometer_bin()
    if not exe:
        raise FileNotFoundError("pyrometer")
    with tempfile.TemporaryDirectory(prefix="eth-scanner-pyrometer-") as tmp:
        path = Path(tmp) / "Target.sol"
        path.write_text(source or "", encoding="utf-8")
        proc = subprocess.run(
            [exe, str(path)],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    return (proc.stdout or "") + "\n" + (proc.stderr or "")
