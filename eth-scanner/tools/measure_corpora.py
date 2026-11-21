#!/usr/bin/env python3
"""Measure beigefield eth-scanner recall on known-vulnerable corpora.

Read-only. Does not send transactions or persist to Supabase.

Two views are recorded for every contract:

1. Production path (local --source, no TVL override): Lane A as the scanner
   runs on a fixture. Local fixtures have no on-chain funds, so the $100
   funds floor skips advanced engines. That is expected.
2. Ungated detectors: the same Slither allowlist + custom detectors the
   research/deep pipeline would run if the funds floor were passed. The
   class gate is recorded separately (engines_would_run_if_funded) but does
   not block this catch rate. solc-select is pointed at a pragma-compatible
   compiler via SOLC_VERSION so the global default is left alone.

CI uses this catch rate as a recall benchmark. The job fails only when
SmartBugs ungated catch falls below ETH_SCANNER_CORPUS_MIN_SMARTBUGS
(default 90 of 143 — a generous floor so small wobble does not break main).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Optional

# Repo eth-scanner root. Override with ETH_SCANNER_ROOT if needed.
ROOT = Path(os.environ.get("ETH_SCANNER_ROOT") or Path(__file__).resolve().parents[1])
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.config import Settings
from eth_scanner.deep.findings import classify_finding
from eth_scanner.engines.fuzz_harness import detect_solc_version
from eth_scanner.heuristics.class_gate import class_gate_allows
from eth_scanner.lane_a.worker import run_one as lane_a_one
from eth_scanner.research.detectors import run_custom_detectors
from eth_scanner.research.pipeline import should_proceed
from eth_scanner.research.slither_runner import SLITHER_ALLOWLIST, run_slither
from eth_scanner.store.supabase import MemoryStore

# Local box default; CI sets ETH_SCANNER_CORPORA_DIR to the fetched checkout.
CORPORA = Path(os.environ.get("ETH_SCANNER_CORPORA_DIR") or "/workspace/vulncorpora")
OUT_DIR = Path(os.environ.get("ETH_SCANNER_CORPORA_OUT") or (CORPORA / "results"))
ORIGINAL_SOLC = os.environ.get("SOLC_VERSION")
WORK = Path(os.environ.get("ETH_SCANNER_CORPORA_WORK") or (CORPORA / "work"))
DEFAULT_MIN_SMARTBUGS = 90

# Detector-id -> SmartBugs DASP category.
# Mapping is by detector / check id only (not free-text evidence). Evidence
# contains words like "now" or "owner" that made classify_finding too noisy.
DETECTOR_TO_DASP = {
    "reentrancy-eth": "reentrancy",
    "reentrancy-no-eth": "reentrancy",
    "reentrancy-benign": "reentrancy",
    "reentrancy-unlimited-gas": "reentrancy",
    "arbitrary-send": "access_control",
    "arbitrary-send-eth": "access_control",
    "arbitrary-send-erc20": "access_control",
    "tx-origin": "access_control",
    "suicidal": "access_control",
    "controlled-delegatecall": "access_control",
    "uncontrolled-delegatecall": "access_control",
    "uninitialized-storage": "access_control",
    "uninitialized-state": "access_control",
    "unchecked-transfer": "unchecked_low_level_calls",
    "unchecked-lowlevel": "unchecked_low_level_calls",
    "unchecked-send": "unchecked_low_level_calls",
    "unused-return": "unchecked_low_level_calls",
    "locked-ether": "denial_of_service",
    "msg-value-loop": "denial_of_service",
    "delegatecall-loop": "denial_of_service",
    "divide-before-multiply": "arithmetic",
    "incorrect-equality": "arithmetic",
    "encode-packed-collision": "other",
    "weak-prng": "bad_randomness",
    "timestamp": "time_manipulation",
    "calls-loop": "denial_of_service",
    "costly-loop": "denial_of_service",
    "msg-value-loop": "denial_of_service",
    "locked-ether": "denial_of_service",
    "multiple-constructors": "access_control",
    "protected-vars": "access_control",
    "unprotected-upgrade": "access_control",
    "incorrect-shift": "arithmetic",
    "incorrect-exp": "arithmetic",
    "incorrect-unary": "arithmetic",
    "custom:weak-auth-value-move": "access_control",
    "weak-auth-value-move": "access_control",
    "arbitrary-send-erc20-permit": "access_control",
    "pre08-arithmetic": "arithmetic",
    "custom:pre08-arithmetic": "arithmetic",
    "weak-entropy": "bad_randomness",
    "custom:weak-entropy": "bad_randomness",
    "unchecked-low-level": "unchecked_low_level_calls",
    "custom:unchecked-low-level": "unchecked_low_level_calls",
    "unchecked-delegatecall": "access_control",
    "custom:unchecked-delegatecall": "access_control",
    "hash-preimage-payout": "front_running",
    "custom:hash-preimage-payout": "front_running",
    "unbounded-storage-loop": "denial_of_service",
    "custom:unbounded-storage-loop": "denial_of_service",
}

NSSC_FOLDER_TO_DASP = {
    "reentrancy": "reentrancy",
    "unprotected_function": "access_control",
    "wrong_constructor_name": "access_control",
    "integer_overflow": "arithmetic",
    "bad_randomness": "bad_randomness",
    "denial_of_service": "denial_of_service",
    "forced_ether_reception": "other",
    "unchecked_external_call": "unchecked_low_level_calls",
    "incorrect_interface": "other",
    "race_condition": "front_running",
    "variable shadowing": "other",
    "honeypots": "other",
}

# DeFiVulnLabs filename stem -> category (from desk/corpora.ts + folder names).
DVL_STEM_TO_CAT = {
    "reentrancy": "reentrancy",
    "readonlyreentrancy": "reentrancy",
    "erc777-reentrancy": "reentrancy",
    "visibility": "access_control",
    "txorigin": "access_control",
    "unprotected-callback": "access_control",
    "overflow": "arithmetic",
    "overflow2": "arithmetic",
    "unsafe-downcast": "arithmetic",
    "precision-loss": "arithmetic",
    "divmultiply": "arithmetic",
    "first-deposit": "arithmetic",
    "price_manipulation": "other",
    "flashloan-flaw": "other",
    "oracle-stale": "other",
    "returnvalue": "unchecked_low_level_calls",
    "unsafecall": "unchecked_low_level_calls",
    "fee-on-transfer": "other",
    "phantom-permit": "other",
    "returnfalse": "other",
    "signaturereplay": "other",
    "signaturereplaynba": "other",
    "ecrecover": "other",
    "delegatecall": "access_control",
    "storage-collision": "access_control",
    "storage-collision-audio": "access_control",
    "uninitialized_variables": "access_control",
    "slippage-deadline": "front_running",
    "selfdestruct": "access_control",
    "selfdestruct2": "access_control",
    "dos": "denial_of_service",
    "randomness": "bad_randomness",
    "invariant": "other",
}


def installed_solcs() -> list[str]:
    try:
        proc = subprocess.run(
            ["solc-select", "versions"], capture_output=True, text=True, check=False, timeout=20
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    versions = []
    for line in (proc.stdout or "").splitlines():
        m = re.search(r"(0\.\d+\.\d+)", line)
        if m:
            versions.append(m.group(1))
    return versions


INSTALLED = installed_solcs()


def vtuple(v: str) -> tuple[int, int, int]:
    parts = (v.split(".") + ["0", "0", "0"])[:3]
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return (0, 0, 0)


def caret_upper(ver: str) -> tuple[int, int, int]:
    x, y, z = vtuple(ver)
    if x > 0:
        return (x + 1, 0, 0)
    return (x, y + 1, 0)


def pragma_spec_ok(ver: str, spec: str) -> bool:
    spec = (spec or "").strip()
    if not spec:
        return True
    tokens = [t for t in re.split(r"\s+", spec) if t]
    vt = vtuple(ver)
    for tok in tokens:
        if tok.startswith("^"):
            base = tok[1:]
            if vt < vtuple(base) or vt >= caret_upper(base):
                return False
        elif tok.startswith(">="):
            if vt < vtuple(tok[2:]):
                return False
        elif tok.startswith("<="):
            if vt > vtuple(tok[2:]):
                return False
        elif tok.startswith(">"):
            if vt <= vtuple(tok[1:]):
                return False
        elif tok.startswith("<"):
            if vt >= vtuple(tok[1:]):
                return False
        elif tok.startswith("="):
            if vt != vtuple(tok[1:]):
                return False
        elif re.match(r"0\.\d+\.\d+$", tok):
            if vt != vtuple(tok):
                return False
        else:
            return False
    return True


def extract_pragma(source: str) -> str:
    m = re.search(r"pragma\s+solidity\s+([^;]+);", source or "", re.I)
    return m.group(1).strip() if m else ""


def pick_solc(source: str, pragma: str = "") -> str:
    pragma = pragma or extract_pragma(source)
    if pragma:
        matching = [v for v in INSTALLED if pragma_spec_ok(v, pragma)]
        if matching:
            return sorted(matching, key=vtuple)[-1]
    detected = detect_solc_version(source=source, default="")
    if detected and detected in INSTALLED:
        return detected
    # Last resort: if pragma is 0.4.x, use highest 0.4 installed.
    if pragma and "0.4." in pragma:
        fours = [v for v in INSTALLED if v.startswith("0.4.")]
        if fours:
            return sorted(fours, key=vtuple)[-1]
    if "0.8.28" in INSTALLED:
        return "0.8.28"
    return INSTALLED[-1] if INSTALLED else ""


def fake_addr(key: str) -> str:
    return "0x" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:40]


def settings() -> Settings:
    return Settings(
        etherscan_api_keys=[],
        supabase_url="",
        supabase_service_role_key="",
        eth_rpc_url="",
        dry_run=True,
        work_dir=WORK,
    )


def _norm_det(detector: str = "", rule: str = "") -> str:
    raw = (detector or rule or "").strip()
    raw = raw.replace("slither:", "").replace("custom:", "")
    return raw.lower()


def dasp_of_finding(detector: str = "", title: str = "", evidence: str = "", rule: str = "") -> str:
    """Map a scanner finding to a DASP category by detector id, not evidence text."""
    candidates = []
    for raw in (detector, rule):
        if not raw:
            continue
        s = str(raw).strip()
        candidates.append(s)
        candidates.append(s.replace("slither:", "").replace("custom:", ""))
        if ":" in s:
            candidates.append(s.split(":", 1)[-1])
        candidates.append("custom:" + s.replace("custom:", "").replace("slither:", ""))
    for c in candidates:
        if c in DETECTOR_TO_DASP:
            return DETECTOR_TO_DASP[c]
        cl = c.lower()
        if cl in DETECTOR_TO_DASP:
            return DETECTOR_TO_DASP[cl]
    # Fallback: family prefixes for allowlisted slither checks.
    joined = " ".join(candidates).lower()
    if "reentr" in joined:
        return "reentrancy"
    if "unchecked" in joined or "unused-return" in joined:
        return "unchecked_low_level_calls"
    if "tx-origin" in joined or "suicidal" in joined or "arbitrary-send" in joined:
        return "access_control"
    if "locked-ether" in joined or "msg-value-loop" in joined:
        return "denial_of_service"
    return ""


def load_smartbugs() -> list[dict[str, Any]]:
    root = CORPORA / "smartbugs-curated"
    entries = json.loads((root / "vulnerabilities.json").read_text(encoding="utf-8"))
    rows = []
    for ent in entries:
        path = root / ent["path"]
        cats = sorted({v["category"] for v in ent.get("vulnerabilities") or [] if v.get("category")})
        category = cats[0] if cats else Path(ent["path"]).parts[1]
        rows.append({
            "corpus": "smartbugs-curated",
            "name": ent.get("name") or path.name,
            "path": str(path),
            "relpath": ent["path"],
            "category": category,
            "pragma_label": ent.get("pragma") or "",
        })
    return rows


def load_nssc() -> list[dict[str, Any]]:
    root = CORPORA / "not-so-smart-contracts"
    rows = []
    for sol in sorted(root.rglob("*.sol")):
        # Skip exploit helpers; we want the vulnerable contracts.
        if "exploit" in sol.name.lower():
            continue
        # Folder immediately under repo root is the category.
        try:
            rel = sol.relative_to(root)
        except ValueError:
            continue
        folder = rel.parts[0]
        category = NSSC_FOLDER_TO_DASP.get(folder, "other")
        rows.append({
            "corpus": "not-so-smart-contracts",
            "name": sol.name,
            "path": str(sol),
            "relpath": str(rel),
            "category": category,
            "pragma_label": "",
        })
    return rows


def load_defivulnlabs() -> list[dict[str, Any]]:
    root = CORPORA / "defivulnlabs" / "src" / "test"
    rows = []
    for sol in sorted(root.glob("*.sol")):
        stem = sol.stem.lower()
        # Skip obvious exploit-only / challenge walkthroughs without a clean label.
        category = DVL_STEM_TO_CAT.get(stem)
        if category is None:
            # Keep but label other so we still measure compile/gating.
            category = "other"
        rows.append({
            "corpus": "defivulnlabs",
            "name": sol.name,
            "path": str(sol),
            "relpath": str(sol.relative_to(CORPORA / "defivulnlabs")),
            "category": category,
            "pragma_label": "",
        })
    return rows


def analyze_one(item: dict[str, Any]) -> dict[str, Any]:
    path = Path(item["path"])
    source = path.read_text(encoding="utf-8", errors="replace")
    pragma = item.get("pragma_label") or extract_pragma(source)
    solc = pick_solc(source, pragma)
    addr = fake_addr(item["corpus"] + ":" + item["relpath"])
    category = item["category"]

    # Point solc-select at the matching compiler for this process only.
    if solc:
        os.environ["SOLC_VERSION"] = solc

    t0 = time.monotonic()
    store = MemoryStore(work_dir=None)
    lane = lane_a_one(
        addr,
        settings=settings(),
        store=store,
        source_path=path,
        tvl_usd=None,
    )
    proceed, gate_reason = should_proceed(lane)
    engine_timing = dict(lane.engine_timing or {})
    engine_notes = [n for n in (lane.notes or []) if "engine" in n.lower() or "slither" in n.lower() or "funds below" in n.lower() or "money-at-risk" in n.lower() or "skip engines" in n.lower()]
    engines_ran = bool(engine_timing.get("slither_executed") or engine_timing.get("ran_slither") or lane.engine_leads)
    skip_reason = ""
    if not engines_ran:
        if lane.funds_usd is None or (lane.funds_status in {"skipped", "unknown", None}):
            skip_reason = "funds-gate: local fixture has no funds_usd (advanced engines require >= $100)"
        elif lane.funds_usd is not None and lane.funds_usd < 100:
            skip_reason = "funds-gate: funds below $100 floor"
        if lane.dropped:
            skip_reason = (skip_reason + "; " if skip_reason else "") + "dropped: %s" % (lane.drop_reason or "unknown")
        allowed, gate_reason = class_gate_allows(
            lane.contract_class or "unknown",
            source=source,
        )
        if not allowed:
            skip_reason = (skip_reason + "; " if skip_reason else "") + "scope-gate: %s" % gate_reason
        if not skip_reason:
            skip_reason = "engines did not run (%s)" % "; ".join((engine_notes or lane.notes or [])[:3])

    would_run_if_funded = (
        (lane.src_confidence in {"high", "med"})
        and class_gate_allows(lane.contract_class or "unknown", source=source)[0]
    )

    # Ungated detector pass: scanner's own Slither allowlist + custom detectors.
    findings, slither_skip, slither_notes = run_slither(
        address=addr, source=source, timeout_s=90
    )
    custom = run_custom_detectors(address=addr, source=source, role=lane.contract_class or "unknown")
    slither_status = "skipped" if slither_skip else "ok"
    slither_reason = ""
    if slither_skip:
        slither_reason = slither_skip.reason
        slither_status = "compile-failed" if "compile" in (slither_skip.reason or "").lower() or "solc" in (slither_skip.reason or "").lower() or "no JSON" in (slither_skip.reason or "") else "skipped"
    compile_failed = slither_status == "compile-failed"

    slither_detectors = []
    mapped = set()
    catch_sources = []
    finding_rows = []
    for f in findings:
        det = (f.detector or "").replace("slither:", "")
        slither_detectors.append(det)
        cat = dasp_of_finding(detector=f.detector, title=f.title, evidence=f.evidence, rule=det)
        mapped.add(cat)
        finding_rows.append({"engine": "slither", "detector": det, "title": f.title, "severity": f.severity, "mapped": cat})
        if cat == category:
            catch_sources.append("slither:%s" % det)
    custom_dets = []
    for f in custom:
        det = f.detector or ""
        custom_dets.append(det)
        cat = dasp_of_finding(detector=det, title=f.title, evidence=f.evidence)
        mapped.add(cat)
        finding_rows.append({"engine": "custom", "detector": det, "title": f.title, "severity": f.severity, "mapped": cat})
        if cat == category:
            catch_sources.append(det)

    # Production-path catch (only if engines actually ran on this fixture).
    prod_catch = []
    for lead in list(lane.engine_leads or []) + list(lane.confirmed_findings or []):
        rule = str(lead.get("rule") or lead.get("id") or "")
        cat = dasp_of_finding(
            detector=str(lead.get("engine") or ""),
            title=str(lead.get("title") or ""),
            evidence=str(lead.get("evidence") or ""),
            rule=rule,
        )
        if cat == category:
            prod_catch.append("%s:%s" % (lead.get("engine"), rule))

    caught = bool(catch_sources)
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    pattern_ids = [str(p.get("id") or "") for p in (lane.pattern_leads or [])]

    return {
        "corpus": item["corpus"],
        "name": item["name"],
        "relpath": item["relpath"],
        "category": category,
        "pragma": pragma,
        "solc_used": solc,
        "address": addr,
        "lane_a_dropped": bool(lane.dropped),
        "drop_reason": lane.drop_reason or "",
        "scope": lane.scope or "",
        "contract_class": lane.contract_class or "",
        "bucket": lane.bucket or "",
        "heat": int(lane.heat or 0),
        "src_confidence": lane.src_confidence or "",
        "ir_confidence": lane.ir_confidence or "",
        "funds_status": lane.funds_status or "",
        "funds_usd": "" if lane.funds_usd is None else lane.funds_usd,
        "research_would_proceed": bool(proceed),
        "research_gate_reason": gate_reason or "",
        "engines_ran": bool(engines_ran),
        "engines_skip_reason": skip_reason,
        "engines_would_run_if_funded": bool(would_run_if_funded),
        "slither_status": slither_status,
        "slither_skip_reason": slither_reason,
        "compile_failed": bool(compile_failed),
        "n_slither_findings": len(findings),
        "slither_detectors": ",".join(sorted(set(slither_detectors))),
        "n_custom_findings": len(custom),
        "custom_detectors": ",".join(sorted(set(custom_dets))),
        "mapped_categories": ",".join(sorted(mapped)),
        "ungated_caught": caught,
        "catch_source": ";".join(catch_sources),
        "production_caught": bool(prod_catch),
        "production_catch_source": ";".join(prod_catch),
        "pattern_leads": ",".join(pattern_ids),
        "elapsed_ms": elapsed_ms,
        "slither_notes": " | ".join(slither_notes)[:500],
        "findings_json": json.dumps(finding_rows, ensure_ascii=False),
    }


CSV_FIELDS = [
    "corpus", "name", "relpath", "category", "pragma", "solc_used", "address",
    "lane_a_dropped", "drop_reason", "scope", "contract_class", "bucket", "heat",
    "src_confidence", "ir_confidence", "funds_status", "funds_usd",
    "research_would_proceed", "research_gate_reason",
    "engines_ran", "engines_skip_reason", "engines_would_run_if_funded",
    "slither_status", "slither_skip_reason", "compile_failed",
    "n_slither_findings", "slither_detectors", "n_custom_findings", "custom_detectors",
    "mapped_categories", "ungated_caught", "catch_source",
    "production_caught", "production_catch_source", "pattern_leads",
    "elapsed_ms", "slither_notes", "findings_json",
]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def _truthy(v: Any) -> bool:
    if v is True:
        return True
    if v is False or v is None:
        return False
    s = str(v).strip().lower()
    return s in {"1", "true", "yes", "y"}


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_corpus: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_corpus[r["corpus"]].append(r)
    out: dict[str, Any] = {"corpora": {}, "overall_note": ""}
    for corpus, items in by_corpus.items():
        labeled = [r for r in items if r["category"]]
        cats = sorted({r["category"] for r in labeled})
        per_cat = {}
        for cat in cats:
            subset = [r for r in labeled if r["category"] == cat]
            per_cat[cat] = {
                "total": len(subset),
                "ungated_caught": sum(1 for r in subset if _truthy(r["ungated_caught"])),
                "production_caught": sum(1 for r in subset if _truthy(r["production_caught"])),
                "compile_failed": sum(1 for r in subset if _truthy(r["compile_failed"])),
                "research_would_proceed": sum(1 for r in subset if _truthy(r["research_would_proceed"])),
                "engines_ran": sum(1 for r in subset if _truthy(r["engines_ran"])),
                "engines_would_run_if_funded": sum(1 for r in subset if _truthy(r["engines_would_run_if_funded"])),
                "lane_a_dropped": sum(1 for r in subset if _truthy(r["lane_a_dropped"])),
                "misses": [r["relpath"] for r in subset if not _truthy(r["ungated_caught"])],
            }
        n = len(labeled)
        out["corpora"][corpus] = {
            "n": n,
            "ungated_caught": sum(1 for r in labeled if _truthy(r["ungated_caught"])),
            "ungated_recall": (sum(1 for r in labeled if _truthy(r["ungated_caught"])) / n) if n else None,
            "production_caught": sum(1 for r in labeled if _truthy(r["production_caught"])),
            "compile_failed": sum(1 for r in labeled if _truthy(r["compile_failed"])),
            "research_would_proceed": sum(1 for r in labeled if _truthy(r["research_would_proceed"])),
            "engines_ran": sum(1 for r in labeled if _truthy(r["engines_ran"])),
            "engines_would_run_if_funded": sum(1 for r in labeled if _truthy(r["engines_would_run_if_funded"])),
            "lane_a_dropped": sum(1 for r in labeled if _truthy(r["lane_a_dropped"])),
            "drop_reasons": dict(Counter(r["drop_reason"] or "(none)" for r in labeled)),
            "scopes": dict(Counter(r["scope"] or "?" for r in labeled)),
            "classes": dict(Counter(r["contract_class"] or "?" for r in labeled)),
            "per_category": per_cat,
        }
    return out



def _print_table(summary: dict[str, Any]) -> None:
    print()
    print("corpus recall (ungated detectors; funds floor does not apply)")
    print("%-28s %8s %10s %8s %12s %14s" % (
        "corpus", "n", "caught", "recall", "compile_fail", "if_funded",
    ))
    for name, block in (summary.get("corpora") or {}).items():
        n = int(block.get("n") or 0)
        caught = int(block.get("ungated_caught") or 0)
        rec = block.get("ungated_recall")
        rec_s = ("%.1f%%" % (100.0 * rec)) if rec is not None else "—"
        print("%-28s %8d %10d %8s %12d %14d" % (
            name, n, caught, rec_s,
            int(block.get("compile_failed") or 0),
            int(block.get("engines_would_run_if_funded") or 0),
        ))
    print()


def _threshold_exit(summary: dict[str, Any], args: argparse.Namespace) -> int:
    floor = int(getattr(args, "min_smartbugs", DEFAULT_MIN_SMARTBUGS) or 0)
    if floor <= 0:
        print("threshold: disabled")
        return 0
    block = (summary.get("corpora") or {}).get("smartbugs-curated") or {}
    if not block:
        print("threshold: no SmartBugs rows in this run (ok)")
        return 0
    caught = int(block.get("ungated_caught") or 0)
    n = int(block.get("n") or 0)
    print("threshold: SmartBugs %d/%d vs min %d" % (caught, n, floor))
    if caught < floor:
        print("FAIL: SmartBugs catch %d is below ETH_SCANNER_CORPUS_MIN_SMARTBUGS=%d" % (caught, floor))
        return 1
    print("PASS: SmartBugs catch is at or above the generous floor")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--corpus", action="append", default=[], help="smartbugs-curated, not-so-smart-contracts, defivulnlabs")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--only", default="", help="substring filter on relpath")
    p.add_argument(
        "--min-smartbugs",
        type=int,
        default=int(os.environ.get("ETH_SCANNER_CORPUS_MIN_SMARTBUGS") or DEFAULT_MIN_SMARTBUGS),
        help="Fail if SmartBugs ungated catches fall below this (default 90). 0 disables.",
    )
    args = p.parse_args(argv)

    wanted = set(args.corpus) or {"smartbugs-curated", "not-so-smart-contracts"}
    items: list[dict[str, Any]] = []
    if "smartbugs-curated" in wanted:
        items.extend(load_smartbugs())
    if "not-so-smart-contracts" in wanted:
        items.extend(load_nssc())
    if "defivulnlabs" in wanted:
        items.extend(load_defivulnlabs())
    if args.only:
        items = [i for i in items if args.only in i["relpath"] or args.only in i["name"]]
    if args.limit:
        items = items[: args.limit]

    print("installed solc:", ", ".join(INSTALLED), file=sys.stderr)
    print("targets:", len(items), "corpora:", ",".join(sorted(wanted)), file=sys.stderr)

    rows: list[dict[str, Any]] = []
    tag = "+".join(sorted(wanted))
    if args.limit:
        tag += "-limit%s" % args.limit
    csv_path = OUT_DIR / ("results-%s.csv" % tag)
    try:
        for i, item in enumerate(items, 1):
            try:
                row = analyze_one(item)
            except Exception as exc:  # noqa: BLE001
                row = {
                    "corpus": item["corpus"],
                    "name": item["name"],
                    "relpath": item["relpath"],
                    "category": item["category"],
                    "pragma": item.get("pragma_label") or "",
                    "solc_used": "",
                    "lane_a_dropped": "",
                    "drop_reason": "exception: %s" % exc,
                    "ungated_caught": False,
                    "production_caught": False,
                    "compile_failed": False,
                    "slither_status": "error",
                    "slither_skip_reason": str(exc)[:400],
                    "engines_ran": False,
                    "research_would_proceed": False,
                    "engines_would_run_if_funded": False,
                    "findings_json": "[]",
                }
            rows.append(row)
            write_csv(csv_path, rows)
            flag = "CATCH" if row.get("ungated_caught") else ("COMPILE_FAIL" if row.get("compile_failed") else "MISS")
            print(
                "[%d/%d] %s %s %s class=%s scope=%s dropped=%s proceed=%s slither=%s %s"
                % (
                    i, len(items), flag, item["category"], item["relpath"],
                    row.get("contract_class"), row.get("scope"),
                    row.get("lane_a_dropped"), row.get("research_would_proceed"),
                    row.get("slither_status"), row.get("catch_source") or row.get("slither_skip_reason") or "",
                ),
                file=sys.stderr, flush=True,
            )
    finally:
        if ORIGINAL_SOLC is None:
            os.environ.pop("SOLC_VERSION", None)
        else:
            os.environ["SOLC_VERSION"] = ORIGINAL_SOLC

    summary = summarize(rows)
    summary["csv"] = str(csv_path)
    summary["n"] = len(rows)
    summary_path = OUT_DIR / ("summary-%s.json" % tag)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print("csv %s" % csv_path, file=sys.stderr)
    print("summary %s" % summary_path, file=sys.stderr)
    _print_table(summary)
    return _threshold_exit(summary, args)


if __name__ == "__main__":
    raise SystemExit(main())
