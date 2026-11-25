"""Mined receipts only. A flash-loan shape enqueues clones and adds no heat."""

from __future__ import annotations

import json
import unittest

from eth_scanner.chain.cu_budget import CuBudget
from eth_scanner.monitor.shaped import (
    creations_from_receipts,
    fetch_receipts,
    flash_topics,
    plan_watch,
    prioritize,
    queue_rows,
    refuse_mempool,
    shaped_transactions,
)
from eth_scanner.research.keccak import keccak256

WATCHED = "0x2222222222222222222222222222222222222222"
CLONE = "0x3333333333333333333333333333333333333333"
FRESH_RICH = "0x4444444444444444444444444444444444444444"
FRESH_FLAT = "0x5555555555555555555555555555555555555555"


def _topic() -> str:
    return "0x" + keccak256(b"FlashLoan(address,address,uint256,uint256)").hex()


def _receipt() -> dict:
    topic = _topic()
    logs = [{"address": WATCHED, "topics": [topic]}]
    logs.extend({"address": "0x" + "ab" * 20, "topics": ["0x" + "11" * 32]} for _ in range(8))
    return {
        "transactionHash": "0x" + "aa" * 32,
        "blockNumber": "0x10",
        "to": WATCHED,
        "status": "0x1",
        "input": "0xdeadbeefcafebabe",
        "logs": logs,
    }


class ShapedWatchTests(unittest.TestCase):
    def test_topics_match_the_public_signatures(self):
        self.assertEqual(len(flash_topics()), 3)
        self.assertIn(_topic(), flash_topics())

    def test_tvl_gain_is_scanned_before_a_flat_deploy(self):
        ranked = prioritize([
            {"address": FRESH_FLAT, "funds_usd": 100, "prev_funds_usd": 100, "age_hours": 1},
            {"address": FRESH_RICH, "funds_usd": 5000, "prev_funds_usd": 100, "age_hours": 2},
        ])
        self.assertEqual(ranked[0]["address"], FRESH_RICH)
        self.assertEqual(ranked[0]["funds_gain"], 4900)
        self.assertEqual(ranked[0]["heat_contribution"], 0)

    def test_a_mined_flash_loan_enqueues_clones_and_drops_calldata(self):
        created = creations_from_receipts([
            {"status": "0x1", "contractAddress": FRESH_RICH},
            {"status": "0x0", "contractAddress": FRESH_FLAT},
        ])
        self.assertEqual(created, [FRESH_RICH])
        report = plan_watch(
            creates=[
                {"address": FRESH_RICH, "funds_usd": 8000, "prev_funds_usd": 100, "age_hours": 1},
                {"address": FRESH_FLAT, "funds_usd": 100, "prev_funds_usd": 100, "age_hours": 1},
            ],
            receipts=[_receipt(), {"blockNumber": None, "logs": _receipt()["logs"]}],
            watched=[WATCHED],
            hashes={WATCHED: "abc"},
            clone_index=[{"address": CLONE, "runtime_hash": "abc"}, {"address": WATCHED, "runtime_hash": "abc"}],
        )
        self.assertEqual(report["heat_contribution"], 0)
        self.assertTrue(report["shaped"])
        self.assertEqual(report["hits"][0]["touched"], [WATCHED])
        self.assertEqual(report["clones"][0]["address"], CLONE)
        self.assertEqual(report["queue"][0]["address"], WATCHED)
        queued = queue_rows(report)
        self.assertEqual(queued[0]["discovery_source"], "fresh-deploy")
        self.assertEqual(queued[0]["reason"], "shaped")
        self.assertEqual(queued[0]["heat_contribution"], 0)
        blob = json.dumps(report)
        self.assertNotIn("deadbeef", blob)
        self.assertNotIn("input", blob)
        pending = shaped_transactions([{"blockNumber": None, "logs": _receipt()["logs"]}], [WATCHED])
        self.assertEqual(pending, [])

    def test_mempool_is_refused_and_receipts_drop_the_input(self):
        with self.assertRaises(ValueError):
            refuse_mempool("txpool_content")
        budget = CuBudget(200)
        seen: list[str] = []

        def caller(method: str, _params: list) -> dict:
            seen.append(method)
            return _receipt()

        rows = fetch_receipts(caller, ["0x" + "aa" * 32], budget, limit=1)
        self.assertEqual(seen, ["eth_getTransactionReceipt"])
        self.assertNotIn("input", rows[0])
        self.assertEqual(budget.spent, 100)


if __name__ == "__main__":
    unittest.main()
