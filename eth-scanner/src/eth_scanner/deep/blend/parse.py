"""Turn Ityfuzz, Halmos, Medusa, and Echidna logs into comparable hits.

Compile errors and setUp crashes are skips. Calldata and counterexample
blobs are dropped. A positive caller_profit_delta is kept only as a number.
"""

from __future__ import annotations

import re
from typing import Any

from eth_scanner.deep.findings import sanitize_evidence

_SKIP = (
    "setup()",
    "setup failed",
    "failed to compile",
    "compilation failed",
    "could not compile",
    "constructor",
)
_DELTA_RX = re.compile(r"caller_profit_delta[=:](\d+)")
_PATH_RX = re.compile(r"call_path[=:]([A-Za-z0-9_./>-]+)")
_WHO_RX = re.compile(r"who_benefits[=:]([^\n;]+)")
_WHAT_RX = re.compile(r"what_breaks[=:]([^\n;]+)")
_MEDUSA_RX = re.compile(
    r"(?:\[FAIL[^\]]*\]|property failed:|Assertion (?:Failed|failed):?)\s*([A-Za-z0-9_]+)",
    re.I,
)
_ECHIDNA_RX = re.compile(r"([A-Za-z_][\w]*)(?:\([^)]*\))?\s*:\s*failed!?", re.I)
_HALMOS_RX = re.compile(r"\[FAIL[^\]]*\]\s*(check_\w+)", re.I)
_ITY_RX = re.compile(
    r"(?:Found (?:a )?(?:violation|bug)|Objective(?: found)?)\W+([A-Za-z0-9_]+)",
    re.I,
)
_INCENTIVE = (
    "first_caller",
    "front_run",
    "frontrun",
    "front_running",
    "reward",
    "time_order",
    "order_dependent",
    "incentive",
)
_PROFIT = (
    "no_caller_profit",
    "no_third_party_balance",
    "value_conservation",
    "profit_free_value",
    "caller_profit",
)


def is_setup_or_compile_failure(text: str) -> bool:
    """True when the log never reached a property with a real profit delta."""
    blob = text or ""
    low = blob.lower()
    if not any(tok in low for tok in _SKIP):
        return False
    match = _DELTA_RX.search(blob)
    if match and int(match.group(1)) > 0:
        return False
    return True


def _norm_key(rule: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", (rule or "").lower()).strip("_")
    return re.sub(r"^(test_|check_|echidna_)+", "", key)


def family_of(rule: str) -> str:
    key = _norm_key(rule)
    if any(tok in key for tok in _PROFIT):
        return "caller-profit"
    if any(tok in key for tok in _INCENTIVE):
        return "incentive"
    if "solvency" in key or "share_price" in key:
        return "solvency"
    return key or "unknown"


def canonical_rule(family: str, rules: list[str]) -> str:
    if family == "caller-profit":
        for pref in ("no_third_party_balance_drop", "no_caller_profit", "value_conservation"):
            if any(pref in _norm_key(rule) or pref in (rule or "").lower() for rule in rules):
                return pref
        return "no_caller_profit"
    if family == "solvency":
        return "solvency"
    if family == "incentive":
        for rule in rules:
            key = _norm_key(rule)
            if any(tok in key for tok in _INCENTIVE):
                return key
        return "incentive"
    cleaned = [_norm_key(rule) or rule for rule in rules if rule]
    return sorted(cleaned)[0] if cleaned else "unknown"


def root_cause(family: str, call_path: str) -> str:
    path = re.sub(r"[^a-z0-9.>]+", "", (call_path or "").lower()) or "-"
    return "%s|%s" % (family, path)


def _names(engine: str, text: str) -> list[str]:
    if engine == "echidna":
        found = _ECHIDNA_RX.findall(text)
    elif engine == "halmos":
        found = _HALMOS_RX.findall(text)
    elif engine == "ityfuzz":
        found = _ITY_RX.findall(text) or _MEDUSA_RX.findall(text)
    else:
        found = _MEDUSA_RX.findall(text)
    return [name.strip() for name in found if name and name.strip()]


def parse_engine_log(engine: str, text: str) -> tuple[str, list[dict[str, Any]]]:
    """Return (status, hits). status is ok or skipped. Skips carry no hits."""
    blob = text or ""
    if is_setup_or_compile_failure(blob):
        return "skipped", []
    delta_match = _DELTA_RX.search(blob)
    delta = int(delta_match.group(1)) if delta_match else 0
    path_match = _PATH_RX.search(blob)
    call_path = path_match.group(1) if path_match else ""
    who_match = _WHO_RX.search(blob)
    what_match = _WHAT_RX.search(blob)
    who = (who_match.group(1).strip() if who_match else "")
    what = (what_match.group(1).strip() if what_match else "")
    names = _names(engine, blob)
    if not names and delta > 0:
        names = ["no_third_party_balance_drop"]
    hits: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name in names:
        key = name.lower()
        if key in seen or any(tok in key for tok in ("setup", "constructor", "compil")):
            continue
        seen.add(key)
        family = family_of(name)
        if (who or what) and family not in {"caller-profit", "incentive"}:
            family = "incentive"
        profit_delta = delta if delta > 0 and family in {"caller-profit", "incentive"} else 0
        hits.append({
            "engine": engine,
            "rule": name,
            "family": family,
            "call_path": call_path,
            "caller_profit_delta": profit_delta,
            "who_benefits": who,
            "what_breaks": what,
            "evidence": sanitize_evidence(
                "property %s; caller_profit_delta=%s; call_path=%s"
                % (name, profit_delta, call_path or "-")
            ),
        })
    if not hits and (who or what):
        hits.append({
            "engine": engine,
            "rule": "incentive",
            "family": "incentive",
            "call_path": call_path,
            "caller_profit_delta": delta if delta > 0 else 0,
            "who_benefits": who,
            "what_breaks": what,
            "evidence": sanitize_evidence(
                "incentive; caller_profit_delta=%s; call_path=%s" % (delta if delta > 0 else 0, call_path or "-")
            ),
        })
    return "ok", hits
