"""Already-drained detection. No network. The flag does not add heat."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.chain.cu_budget import CuBudget
from eth_scanner.chain.liveness import assess_outflows, scan_liveness
from eth_scanner.ingest.rpc_client import RpcTransientError

ADDR = "0x" + "11" * 20
EOA = "0x" + "22" * 20
CONTRACT = "0x" + "33" * 20


class _Rpc:
    def __init__(self, responses=None, errors=None):
        self.responses = responses or {}
        self.errors = errors or {}

    def __call__(self, url, method, params, timeout_s=8.0):
        if method in self.errors:
            raise self.errors[method]
        if method not in self.responses:
            raise RuntimeError("method not found: -32601")
        value = self.responses[method]
        return value(params) if callable(value) else value


class Liveness(unittest.TestCase):
    def test_collapsed_eoa_outflow_is_dead_and_heatless(self):
        row = assess_outflows(
            [{"category": "external", "to": EOA, "value": 5, "hash": "0x" + "ab" * 32}],
            0,
            {EOA: "0x"},
        )
        self.assertEqual(row["status"], "dead")
        self.assertEqual(row["heat_contribution"], 0)
        self.assertGreaterEqual(row["outflow_wei"], 10**18)

    def test_remaining_dust_is_already_exploited(self):
        row = assess_outflows(
            [{"category": "external", "to": EOA, "value": 2, "hash": "0x1"}],
            10**16,
            {EOA: "0x"},
        )
        self.assertEqual(row["status"], "already-exploited")

    def test_a_contract_recipient_is_not_flagged(self):
        row = assess_outflows(
            [{"category": "external", "to": CONTRACT, "value": 50, "hash": "0x1"}],
            0,
            {CONTRACT: "0x60806040"},
        )
        self.assertEqual(row["status"], "live")

    def test_a_small_outflow_stays_live(self):
        row = assess_outflows(
            [{"category": "external", "to": EOA, "value": 0.1, "hash": "0x1"}],
            0,
            {EOA: "0x"},
        )
        self.assertEqual(row["status"], "live")

    def test_scan_confirms_code_before_flagging(self):
        rpc = _Rpc(responses={
            "alchemy_getAssetTransfers": {"transfers": [
                {"category": "external", "to": EOA, "value": 4, "hash": "0x" + "cd" * 32},
            ]},
            "eth_getCode": "0x",
            "eth_getBalance": "0x0",
        })
        row = scan_liveness(ADDR, "http://rpc", budget=CuBudget(400), rpc=rpc)
        self.assertEqual(row["status"], "dead")
        self.assertEqual(row["heat_contribution"], 0)
        self.assertLessEqual(row["cu"]["spent"], 400)

    def test_missing_api_does_not_flag(self):
        rpc = _Rpc(errors={"alchemy_getAssetTransfers": RuntimeError("method not found: -32601")})
        row = scan_liveness(ADDR, "http://rpc", budget=CuBudget(400), rpc=rpc)
        self.assertEqual(row["status"], "unknown")
        self.assertTrue(row["degraded"])

    def test_rate_limit_does_not_flag(self):
        rpc = _Rpc(errors={"alchemy_getAssetTransfers": RpcTransientError("429 too many requests")})
        row = scan_liveness(ADDR, "http://rpc", budget=CuBudget(400), rpc=rpc)
        self.assertEqual(row["status"], "unknown")
        self.assertTrue(row["degraded"])


if __name__ == "__main__":
    unittest.main()
