"""Public incident addresses only. No writeup text and no heat."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.benchmark import incident_recall as recall
from eth_scanner.research.keccak import selector4
from eth_scanner.research.proxy import (
    OZ_LEGACY_IMPLEMENTATION_SLOT,
    encode_address_array,
    encode_bytes4_array,
    follow_runtime_addresses,
)


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

    def test_a_lead_past_200k_characters_still_counts(self):
        source = "/* " + ("a" * 200_000) + " */\ncontract C { function f(address target) public { target.call(''); } }"
        self.assertTrue(recall.score_source("0x" + "11" * 20, source))

    def test_a_token_is_not_followed_to_another_address(self):
        token = (
            "contract T { function transfer(address a, uint256 n) public {} "
            "function approve(address a, uint256 n) public {} }"
        )
        calls: list = []

        def storage(addr, slot):
            calls.append(slot)
            return "0x" + "22" * 32

        self.assertEqual(
            follow_runtime_addresses("0x" + "11" * 20, token, get_storage=storage),
            [],
        )
        self.assertEqual(calls, [])

    def test_a_legacy_proxy_follows_the_zeppelin_slot(self):
        source = (
            "contract TokenProxy { function upgradeTo(address n) public {} "
            "function changeAdmin(address a) public {} }"
        )
        impl = "0x" + "22" * 20

        def storage(addr, slot):
            if slot == OZ_LEGACY_IMPLEMENTATION_SLOT:
                return "0x" + "00" * 12 + "22" * 20
            return "0x" + "00" * 32

        self.assertEqual(
            follow_runtime_addresses("0x" + "11" * 20, source, get_storage=storage),
            [impl],
        )

    def test_a_diamond_follows_the_loupe(self):
        source = "contract Diamond { fallback() external payable {} }"
        facet = selector4("facetAddresses()")

        def caller(addr, data):
            if data == facet:
                return encode_address_array(["0x" + "33" * 20])
            return encode_bytes4_array([])

        self.assertEqual(
            follow_runtime_addresses("0x" + "11" * 20, source, eth_call_fn=caller),
            ["0x" + "33" * 20],
        )

    def test_mark_scored_includes_the_implementation_source(self):
        proxy = "0x" + "11" * 20
        rows = [{
            "chain": "ethereum",
            "address": proxy,
            "pre_incident": True,
            "classification": "",
            "technique": "",
        }]
        proxy_src = "contract TokenProxy { function upgradeTo(address n) public {} }"
        impl_src = "contract Impl { function f(address t) public { t.call(''); } }"

        def fetch(chain, address):
            return proxy_src if address == proxy else ""

        original = recall.assemble_runtime_source

        def assemble(chain, address, source, **kwargs):
            return source + "\n" + impl_src

        recall.assemble_runtime_source = assemble
        try:
            recall.mark_scored(rows, fetch_source=fetch, rpc_for=lambda chain: "http://rpc")
        finally:
            recall.assemble_runtime_source = original
        self.assertTrue(rows[0]["scored"])
        self.assertTrue(rows[0]["hot"])

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
