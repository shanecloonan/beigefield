"""Historical calldata seeds. No network. Heat stays zero."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.chain.cu_budget import CuBudget
from eth_scanner.chain.trace_seeds import collect_seeds, write_corpora
from eth_scanner.deep.blend.harness import write_project
from eth_scanner.ingest.rpc_client import RpcTransientError

ADDR = "0x" + "ab" * 20
CALL = "0x" + "12" * 4 + "00" * 32


class _Rpc:
    def __init__(self, responses=None, errors=None):
        self.responses = responses or {}
        self.errors = errors or {}
        self.seen: list[str] = []

    def __call__(self, url, method, params, timeout_s=8.0):
        self.seen.append(method)
        if method in self.errors:
            raise self.errors[method]
        if method not in self.responses:
            raise RuntimeError("method not found: -32601")
        value = self.responses[method]
        return value(params) if callable(value) else value


class TraceSeeds(unittest.TestCase):
    def test_debug_trace_becomes_a_local_corpus(self):
        rpc = _Rpc(responses={
            "alchemy_getAssetTransfers": {"transfers": [{"hash": "0x" + "11" * 32}]},
            "debug_traceTransaction": {
                "to": ADDR,
                "input": CALL,
                "value": "0x10",
                "calls": [{
                    "to": ADDR,
                    "input": "0x" + "ab" * 4,
                    "value": "0x0",
                }],
            },
        })
        corpus = collect_seeds(ADDR, "https://eth-mainnet.g.alchemy.com/v2/test", budget=CuBudget(2500), rpc=rpc)
        self.assertEqual(corpus["heat_contribution"], 0)
        self.assertEqual(corpus["status"], "ok")
        self.assertEqual(len(corpus["seeds"]), 2)
        self.assertEqual(corpus["sequences"][0]["tx"], "0x" + "11" * 32)
        self.assertIn("debug_traceTransaction", corpus["sources"])
        self.assertLessEqual(corpus["cu"]["spent"], 2500)
        with tempfile.TemporaryDirectory() as tmp:
            root = write_project(Path(tmp), [{
                "name": "Vault",
                "source": "contract Vault { function skim() external {} }",
            }], seeds=corpus["seeds"], sequences=corpus["sequences"])
            text = (root / "src" / "ConservationHarness.sol").read_text(encoding="utf-8")
            self.assertIn('hex"%s"' % CALL[2:], text)
            self.assertNotIn("broadcast", text.lower())
            saved = json.loads((root / "corpus" / "echidna" / "seeds.json").read_text(encoding="utf-8"))
            self.assertEqual(len(saved["seeds"]), 2)
            self.assertTrue((root / "corpus" / "medusa" / "sequences.json").is_file())
            self.assertTrue((root / "corpus" / "ityfuzz" / "calls.txt").is_file())
            self.assertTrue((root / "corpus" / "forge" / "seeds.json").is_file())

    def test_missing_debug_falls_back_to_the_transaction_input(self):
        rpc = _Rpc(
            responses={
                "alchemy_getAssetTransfers": {"transfers": [{"hash": "0x" + "22" * 32}]},
                "eth_getTransactionByHash": {"to": ADDR, "input": CALL, "value": "0x2", "hash": "0x" + "22" * 32},
            },
            errors={"debug_traceTransaction": RuntimeError("method not found: -32601")},
        )
        corpus = collect_seeds(ADDR, "http://rpc", budget=CuBudget(2500), rpc=rpc)
        self.assertEqual(corpus["seeds"][0]["source"], "eth_getTransactionByHash")
        self.assertEqual(corpus["seeds"][0]["calldata"], CALL)
        self.assertNotIn("debug_traceTransaction", rpc.seen[2:])  # probed once, then stopped

    def test_rate_limit_degrades_without_raising(self):
        rpc = _Rpc(errors={"alchemy_getAssetTransfers": RpcTransientError("429 too many requests")})
        corpus = collect_seeds(ADDR, "http://rpc", budget=CuBudget(2500), rpc=rpc)
        self.assertEqual(corpus["seeds"], [])
        self.assertTrue(corpus["degraded"])
        self.assertEqual(corpus["heat_contribution"], 0)
        self.assertIn("rate limited", corpus["note"])

    def test_no_rpc_keeps_the_old_empty_corpus(self):
        corpus = collect_seeds(ADDR, "", budget=CuBudget(2500), rpc=_Rpc())
        self.assertEqual(corpus["status"], "skipped")
        self.assertEqual(corpus["seeds"], [])
        self.assertEqual(corpus["cu"]["spent"], 0)

    def test_budget_stops_before_a_trace(self):
        rpc = _Rpc(responses={"alchemy_getAssetTransfers": {"transfers": [{"hash": "0x" + "33" * 32}]}})
        corpus = collect_seeds(ADDR, "http://rpc", budget=CuBudget(120), rpc=rpc)
        self.assertEqual(corpus["seeds"], [])
        self.assertNotIn("debug_traceTransaction", rpc.seen)
        self.assertEqual(corpus["cu"]["spent"], 120)

    def test_trace_filter_when_alchemy_is_absent(self):
        rpc = _Rpc(responses={
            "eth_blockNumber": "0x1000",
            "trace_filter": [{
                "transactionHash": "0x" + "44" * 32,
                "type": "call",
            }],
            "eth_getTransactionByHash": {"to": ADDR, "input": CALL, "hash": "0x" + "44" * 32},
        }, errors={"debug_traceTransaction": RuntimeError("unsupported method")})
        corpus = collect_seeds(ADDR, "http://rpc", budget=CuBudget(2500), rpc=rpc)
        self.assertIn("trace_filter", corpus["sources"])
        self.assertEqual(corpus["seeds"][0]["calldata"], CALL)

    def test_write_corpora_is_heatless(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_corpora(Path(tmp), {"seeds": [{"calldata": CALL}], "sequences": [], "cu": {"spent": 17}})
            self.assertGreaterEqual(len(paths), 4)


if __name__ == "__main__":
    unittest.main()
