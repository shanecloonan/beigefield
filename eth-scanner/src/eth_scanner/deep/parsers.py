"""Parse engine JSON/text into EngineFinding rows. Defensive — elide calldata."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from eth_scanner.deep.findings import EngineFinding, make_finding
from eth_scanner.research.slither_runner import slither_severity


def _safe_json(text: str) -> Any:
    t = (text or "").strip()
    if not t:
        return None
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        start = t.find("{")
        end = t.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(t[start : end + 1])
            except json.JSONDecodeError:
                return None
        return None


def parse_slither(text: str) -> list[EngineFinding]:
    data = _safe_json(text)
    if not isinstance(data, dict):
        return []
    results = data.get("results") if isinstance(data.get("results"), dict) else {}
    detectors = results.get("detectors") if isinstance(results, dict) else None
    if detectors is None:
        detectors = data.get("detectors")
    if not isinstance(detectors, list):
        return []
    out: list[EngineFinding] = []
    for d in detectors:
        if not isinstance(d, dict):
            continue
        elements = d.get("elements") if isinstance(d.get("elements"), list) else []
        fn = next((e for e in elements if isinstance(e, dict) and e.get("type") == "function"), None)
        if fn is None and elements and isinstance(elements[0], dict):
            fn = elements[0]
        sm = (fn or {}).get("source_mapping") if isinstance(fn, dict) else {}
        if not isinstance(sm, dict):
            sm = {}
        tsf = (fn or {}).get("type_specific_fields") if isinstance(fn, dict) else {}
        parent = (tsf or {}).get("parent") if isinstance(tsf, dict) else {}
        lines = sm.get("lines") if isinstance(sm.get("lines"), list) else []
        rule = str(d.get("check") or d.get("detector") or "unknown")
        out.append(make_finding(
            engine="slither",
            rule=rule,
            title=rule,
            severity=slither_severity(rule, str(d.get("impact") or "")),
            confidence=d.get("confidence"),
            file=sm.get("filename_relative") or sm.get("filename_short"),
            line=int(lines[0]) if lines else None,
            contract=(parent or {}).get("name") if isinstance(parent, dict) else None,
            function=(fn or {}).get("name") if isinstance(fn, dict) and fn.get("type") == "function" else None,
            evidence=d.get("description") or d.get("markdown") or rule,
        ))
    return out


def parse_aderyn(text: str) -> list[EngineFinding]:
    data = _safe_json(text)
    if not isinstance(data, dict):
        return []
    out: list[EngineFinding] = []
    for bucket, severity in (
        ("critical_issues", "critical"),
        ("high_issues", "high"),
        ("medium_issues", "medium"),
        ("low_issues", "low"),
    ):
        group = data.get(bucket)
        if not isinstance(group, dict):
            continue
        issues = group.get("issues") if isinstance(group.get("issues"), list) else []
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            rule = str(issue.get("detector_name") or issue.get("title") or "aderyn")
            instances = issue.get("instances") if isinstance(issue.get("instances"), list) else []
            rows = instances[:20] if instances else [{}]
            for inst in rows:
                if not isinstance(inst, dict):
                    inst = {}
                out.append(make_finding(
                    engine="aderyn",
                    rule=rule,
                    title=str(issue.get("title") or rule),
                    severity=severity,
                    confidence="medium",
                    file=inst.get("contract_path"),
                    line=int(inst["line_no"]) if isinstance(inst.get("line_no"), int) else None,
                    evidence=issue.get("description") or rule,
                ))
    return out


def parse_mythril(text: str) -> list[EngineFinding]:
    data = _safe_json(text)
    if not isinstance(data, dict):
        return []
    issues = data.get("issues") if isinstance(data.get("issues"), list) else []
    out: list[EngineFinding] = []
    for i in issues:
        if not isinstance(i, dict):
            continue
        swc = str(i.get("swc-id") or i.get("swcID") or "")
        rule = ("SWC-%s" % swc.replace("SWC-", "")) if swc else str(i.get("title") or "mythril")
        out.append(make_finding(
            engine="mythril",
            rule=rule,
            title=str(i.get("title") or rule),
            severity=i.get("severity"),
            confidence="medium",
            file=i.get("filename"),
            line=int(i["lineno"]) if isinstance(i.get("lineno"), int) else None,
            contract=i.get("contract"),
            function=i.get("function"),
            evidence=i.get("description") or i.get("description_head") or rule,
            class_hint=("swc-%s" % swc.replace("SWC-", "")) if swc else None,
        ))
    return out


def parse_halmos(text: str) -> list[EngineFinding]:
    """Halmos text: failing check_* lines only. No counterexample calldata kept."""
    out: list[EngineFinding] = []
    for line in (text or "").splitlines():
        m = re.search(r"\b(check_[\w]+)\b.*\b(fail|counterexample|violat)", line, re.I)
        if not m:
            continue
        name = m.group(1)
        out.append(make_finding(
            engine="halmos",
            rule=name,
            title="Property %s violated" % name,
            severity="high",
            confidence="high",
            function=name,
            evidence="Halmos reported a violation of %s — state summary only (inputs elided)." % name,
            class_hint="invariant-violation",
        ))
    return out


PARSERS = {
    "slither": parse_slither,
    "aderyn": parse_aderyn,
    "mythril": parse_mythril,
    "halmos": parse_halmos,
}


def parse_engine(engine: str, text: str) -> list[EngineFinding]:
    fn = PARSERS.get((engine or "").lower())
    if not fn:
        return []
    return fn(text)
