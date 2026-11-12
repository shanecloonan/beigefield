"""Phase A deep-engine normalize / dedupe / agreement — no live binaries required."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.deep.findings import (
    agreement_summary,
    apply_agreement,
    dedupe_findings,
    heat_eligible_clusters,
    make_finding,
)
from eth_scanner.deep.parsers import parse_aderyn, parse_halmos, parse_mythril, parse_slither
from eth_scanner.deep.worker import run_deep_one
from eth_scanner.store.supabase import MemoryStore
from eth_scanner.types import Target


SLITHER_JSON = json.dumps({
    "success": True,
    "results": {
        "detectors": [
            {
                "check": "reentrancy-eth",
                "impact": "High",
                "confidence": "Medium",
                "description": "Reentrancy in withdraw()",
                "elements": [{
                    "type": "function",
                    "name": "withdraw",
                    "source_mapping": {
                        "filename_relative": "Vault.sol",
                        "lines": [42],
                    },
                    "type_specific_fields": {"parent": {"name": "Vault"}},
                }],
            },
            {
                "check": "naming-convention",
                "impact": "Informational",
                "confidence": "High",
                "description": "style only",
                "elements": [],
            },
        ]
    },
})

ADERYN_JSON = json.dumps({
    "high_issues": {
        "issues": [{
            "detector_name": "reentrancy",
            "title": "Reentrancy",
            "description": "State after external call",
            "instances": [{"contract_path": "Vault.sol", "line_no": 42}],
        }]
    },
    "low_issues": {"issues": []},
})

MYTHRIL_JSON = json.dumps({
    "issues": [{
        "swc-id": "107",
        "title": "Reentrancy",
        "severity": "High",
        "description": "Call state dependency",
        "filename": "Vault.sol",
        "lineno": 42,
        "function": "withdraw",
        "tx_sequence": "MUST_BE_ELIDED_0x" + ("ab" * 80),
    }]
})


class ParseAndSanitize(unittest.TestCase):
    def test_slither_allowlist_style_marked_generic(self):
        rows = parse_slither(SLITHER_JSON)
        self.assertEqual(len(rows), 2)
        generic = [r for r in rows if r.rule == "naming-convention"][0]
        self.assertTrue(generic.generic)
        reent = [r for r in rows if "reentrancy" in r.rule][0]
        self.assertEqual(reent.funds_class, "reentrancy")
        self.assertEqual(reent.function, "withdraw")

    def test_mythril_elides_calldata_blobs(self):
        rows = parse_mythril(MYTHRIL_JSON)
        self.assertEqual(len(rows), 1)
        # description has no long hex; ensure sanitize path works on evidence
        self.assertNotIn("ababab", rows[0].evidence)

    def test_halmos_text(self):
        rows = parse_halmos("check_solvency: failed with counterexample")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].funds_class, "invariant-violation")
        self.assertIn("elided", rows[0].evidence.lower())


class Agreement(unittest.TestCase):
    def test_multi_engine_raises_confidence_not_generic(self):
        a = parse_slither(SLITHER_JSON)
        b = parse_aderyn(ADERYN_JSON)
        merged = apply_agreement(dedupe_findings(a + b))
        summary = agreement_summary(merged)
        eligible = heat_eligible_clusters(summary)
        self.assertGreaterEqual(summary["multi_engine_clusters"], 1)
        self.assertTrue(any(c["heat_eligible"] for c in eligible))
        # naming-convention alone never heat-eligible
        self.assertFalse(any(
            c["heat_eligible"] and "naming" in ",".join(c.get("titles") or []).lower()
            for c in summary["clusters"]
        ))

    def test_single_engine_generic_not_heat_eligible(self):
        only = apply_agreement(dedupe_findings(parse_slither(SLITHER_JSON)))
        summary = agreement_summary(only)
        # Only one engine → no heat-eligible clusters
        self.assertEqual(summary["heat_eligible_clusters"], 0)

    def test_make_finding_cluster_key_stable(self):
        a = make_finding(engine="slither", rule="reentrancy-eth", title="r", function="withdraw")
        b = make_finding(engine="aderyn", rule="reentrancy", title="r", function="withdraw")
        c = make_finding(engine="mythril", rule="SWC-107", title="r", function="withdraw")
        self.assertEqual(a.cluster_key, b.cluster_key)
        self.assertEqual(a.cluster_key, c.cluster_key)


class DeepWorkerDry(unittest.TestCase):
    def test_local_source_without_binaries_still_persists(self):
        store = MemoryStore()
        addr = "0x1111111111111111111111111111111111111111"
        store.upsert_target(Target(address=addr, status="pending"))
        store.targets[addr]["bucket"] = "lane-b-queue"
        source = (
            "pragma solidity ^0.8.20;\n"
            "contract Vault { function withdraw() external {} }\n"
        )
        # Point engines at missing bins via empty PATH fragment — runners skip.
        import os
        old = os.environ.get("PATH")
        try:
            os.environ["PATH"] = "/tmp/no-such-bins"
            for k in (
                "ETH_SCANNER_SLITHER_BIN",
                "ETH_SCANNER_ADERYN_BIN",
                "ETH_SCANNER_MYTHRIL_BIN",
                "ETH_SCANNER_HALMOS_BIN",
            ):
                os.environ.pop(k, None)
            report = run_deep_one(addr, store=store, source_text=source, engines=["slither", "aderyn"])
        finally:
            if old is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = old
        self.assertEqual(report["status"], "done")
        self.assertEqual(report["findings"], [])
        self.assertTrue(any(a.get("kind") == "report" for a in store.artifacts))
        self.assertEqual(store.targets[addr].get("deep_status"), "done")


if __name__ == "__main__":
    unittest.main()
