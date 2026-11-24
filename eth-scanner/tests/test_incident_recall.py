"""Public incident addresses only. No writeup text and no heat."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.benchmark import incident_recall as recall


class IncidentRecall(unittest.TestCase):
    def test_join_keeps_chain_and_address_only(self):
        hacks = [{
            "date": 1700000000,
            "name": "Example",
            "defillamaId": "7",
            "chain": ["Ethereum"],
            "description": "the attacker flash-borrows and calls withdraw",
        }]
        protocols = [{
            "id": "7",
            "name": "Example",
            "address": "ethereum:0x1111111111111111111111111111111111111111",
            "description": "attack writeup",
        }]
        rows = recall.resolve_incidents(hacks, protocols)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["chain"], "ethereum")
        self.assertEqual(rows[0]["address"], "0x1111111111111111111111111111111111111111")
        self.assertNotIn("description", rows[0])
        blob = str(rows[0])
        self.assertNotIn("flash-borrows", blob)
        self.assertEqual(rows[0]["heat_contribution"], 0)

    def test_a_missing_address_is_not_resolved(self):
        rows = recall.resolve_incidents(
            [{"defillamaId": "1", "chain": ["Base"], "name": "Gone"}],
            [{"id": "1", "address": ""}],
        )
        self.assertEqual(rows, [])

    def test_recall_is_undefined_until_a_row_is_scored(self):
        report = recall.recall_report([
            {"pre_incident": True, "scored": False, "hot": False},
        ], incidents=3)
        self.assertIsNone(report["recall"])
        self.assertEqual(report["heat_contribution"], 0)
        self.assertEqual(report["scored"], 0)

    def test_recall_counts_detector_leads(self):
        rows = [
            {"chain": "ethereum", "pre_incident": True, "scored": True, "hot": True},
            {"chain": "bsc", "pre_incident": True, "scored": True, "hot": False},
            {"chain": "arbitrum", "pre_incident": False, "scored": True, "hot": True},
        ]
        report = recall.recall_report(rows, incidents=10)
        self.assertEqual(report["scored"], 2)
        self.assertEqual(report["hot"], 1)
        self.assertEqual(report["recall"], 0.5)
        self.assertEqual(report["legacy"]["scored"], 2)
        self.assertEqual(report["legacy"]["recall"], 0.5)
        self.assertEqual(report["pre_incident"], 2)

    def test_offchain_labels_leave_the_denominator(self):
        rows = [
            {"chain": "ethereum", "pre_incident": True, "scored": True, "hot": True, "bucket": "protocol"},
            {"chain": "ethereum", "pre_incident": True, "scored": True, "hot": False, "bucket": "token"},
            {
                "chain": "ethereum",
                "pre_incident": True,
                "scored": True,
                "hot": False,
                "classification": "Key Compromise",
                "technique": "Private Key Compromised",
            },
        ]
        report = recall.recall_report(rows, incidents=3)
        self.assertEqual(report["legacy"]["scored"], 3)
        self.assertEqual(report["legacy"]["hot"], 1)
        self.assertAlmostEqual(report["legacy"]["recall"], 1 / 3)
        self.assertEqual(report["scored"], 2)
        self.assertEqual(report["hot"], 1)
        self.assertEqual(report["recall"], 0.5)
        self.assertEqual(report["buckets"]["off_chain"]["scored"], 1)
        self.assertFalse(report["buckets"]["off_chain"]["in_denominator"])
        self.assertEqual(report["buckets"]["off_chain"]["label"], "off-chain label")
        self.assertEqual(report["buckets"]["token"]["scored"], 1)
        self.assertTrue(report["buckets"]["token"]["in_denominator"])
        self.assertEqual(report["buckets"]["protocol"]["hot"], 1)
        self.assertEqual(report["buckets"]["protocol"]["label"], "scored source is a protocol contract")
        self.assertEqual(report["heat_contribution"], 0)

    def test_a_token_source_is_not_a_pool(self):
        token = (
            "contract T { function transfer(address a, uint256 n) public {} "
            "function approve(address a, uint256 n) public {} }"
        )
        commented = (
            "contract T { // function deposit(uint256 n) public {}\n"
            "function transfer(address a, uint256 n) public {} "
            "function approve(address a, uint256 n) public {} }"
        )
        vault = token + " function deposit(uint256 n) public {}"
        self.assertTrue(recall.is_token_source(token))
        self.assertTrue(recall.is_token_source(commented))
        self.assertFalse(recall.is_token_source(vault))
        self.assertFalse(recall.is_token_source("contract D { fallback() external payable {} }"))
        self.assertTrue(recall.is_offchain_label("Key Compromise", "Private Key Compromised"))
        self.assertTrue(recall.is_offchain_label("Rugpull", "Backdoor Contract"))
        self.assertTrue(recall.is_offchain_label("Frontend & Infrastructure", "DNS Hijack"))
        self.assertTrue(recall.is_offchain_label("Social Engineering", "Phishing"))
        self.assertTrue(recall.is_offchain_label("", "Validator Key Compromised"))
        self.assertFalse(recall.is_offchain_label("Reentrancy", "Reentrancy"))
        self.assertEqual(recall.assign_bucket({"classification": "Oracle Manipulation"}, token), "token")
        self.assertEqual(recall.assign_bucket({"classification": "Reentrancy"}, vault), "protocol")
        self.assertEqual(
            recall.assign_bucket(
                {"classification": "Key Compromise", "technique": "Hot Wallet Key Compromised"},
                vault,
            ),
            "off_chain",
        )

    def test_join_keeps_the_class_and_drops_the_writeup(self):
        rows = recall.resolve_incidents(
            [{
                "date": 1700000000,
                "name": "Example",
                "defillamaId": "7",
                "chain": ["Ethereum"],
                "classification": "Reentrancy",
                "technique": "Reentrancy",
                "description": "the attacker flash-borrows and calls withdraw",
            }],
            [{"id": "7", "name": "Example", "address": "0x1111111111111111111111111111111111111111"}],
        )
        self.assertEqual(rows[0]["classification"], "Reentrancy")
        self.assertEqual(rows[0]["technique"], "Reentrancy")
        self.assertNotIn("description", rows[0])
        self.assertNotIn("flash-borrows", str(rows[0]))

    def test_unchecked_call_is_a_lead(self):
        source = "contract C { function f(address target) public { target.call(''); } }"
        self.assertTrue(recall.score_source("0x" + "11" * 20, source))
        self.assertFalse(recall.score_source("0x" + "11" * 20, "contract C { function f() public {} }"))

    def test_immutable_runtime_is_code_without_a_proxy_slot(self):
        rows = [{
            "chain": "ethereum",
            "address": "0x" + "ab" * 20,
            "pre_incident": False,
        }]
        calls: list = []

        def fake_batch(url, batch):
            calls.append(url)
            return {"0": "0x6080", "1": "0x" + "0" * 64}

        original = recall._batch
        recall._batch = fake_batch
        try:
            recall.mark_immutable(rows, rpc_for=lambda chain: "http://rpc")
        finally:
            recall._batch = original
        self.assertTrue(rows[0]["pre_incident"])
        self.assertEqual(calls, ["http://rpc"])

    def test_a_proxy_slot_or_clone_is_not_pre_incident(self):
        self.assertTrue(recall._is_proxy_slot("0x" + "0" * 24 + "ab"))
        self.assertFalse(recall._is_proxy_slot("0x" + "0" * 64))
        self.assertTrue(recall._is_clone("0x363d3d373d3d3d363d73abcd"))
        self.assertEqual(
            recall._source_from_sourcify({"stdJsonInput": {"sources": {"A.sol": {"content": "contract A {}"}}}}),
            "contract A {}",
        )


if __name__ == "__main__":
    unittest.main()
