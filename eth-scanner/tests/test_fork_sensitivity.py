"""A view comparison stays on a local fork and does not add heat."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.advanced.fork_sensitivity import compare_view

ADDR = "0x" + "ab" * 20


class ForkSensitivity(unittest.TestCase):
    def test_a_public_url_is_refused_before_any_call(self):
        def rpc(*_args):
            raise AssertionError("rpc was called")

        result = compare_view("https://eth-mainnet.g.alchemy.com/v2/x", ADDR, rpc=rpc)
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["heat_contribution"], 0)
        self.assertEqual(result["calls"], [])

    def test_a_local_fork_uses_eth_call_and_adds_no_heat(self):
        methods = []

        def rpc(url, method, params):
            methods.append((method, params[0]["data"]))
            self.assertTrue(url.startswith("http://127.0.0.1"))
            if len(params) == 3:
                self.assertIn("stateDiff", next(iter(params[2].values())))
            return "0x01" if len(params) == 2 else "0x02"

        result = compare_view(
            "http://127.0.0.1:8545",
            ADDR,
            slot="0x" + "11" * 32,
            word="0x" + "22" * 32,
            rpc=rpc,
        )
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["changed"])
        self.assertEqual(result["heat_contribution"], 0)
        self.assertEqual(methods, [("eth_call", "0x01e1d114"), ("eth_call", "0x01e1d114")])
        self.assertNotIn("eth_sendTransaction", result["calls"])


if __name__ == "__main__":
    unittest.main()
