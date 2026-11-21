"""Local Solana simulation stays on loopback and adds no heat."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.chains.solana_sim import plan_sim, validator_argv

PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
LOCAL = "http://127.0.0.1:8899"


class SolanaSim(unittest.TestCase):
    def test_mainnet_url_is_refused(self):
        calls = []
        for url in (
            "https://api.mainnet-beta.solana.com",
            "https://solana-mainnet.g.alchemy.com/v2/example",
            "",
        ):
            report = plan_sim(PROGRAM, rpc=url, execute=True, runner=lambda argv: calls.append(argv))
            self.assertTrue(report["refused"])
            self.assertFalse(report["executed"])
            self.assertIsNone(report["argv"])
            self.assertEqual(report["heat_contribution"], 0)
        self.assertEqual(calls, [])

    def test_loopback_plan_does_not_start_a_process(self):
        calls = []
        report = plan_sim(PROGRAM, rpc=LOCAL, runner=lambda argv: calls.append(argv))
        self.assertFalse(report["executed"])
        self.assertTrue(report["skipped"])
        self.assertEqual(calls, [])
        self.assertEqual(report["heat_contribution"], 0)
        argv = report["argv"]
        self.assertIsNotNone(argv)
        self.assertIn(LOCAL, argv)
        self.assertNotIn("sendTransaction", argv)
        joined = " ".join(argv)
        self.assertNotIn("mainnet", joined)
        self.assertNotIn("sendTransaction", joined)

    def test_validator_argv_rejects_a_public_url(self):
        with self.assertRaises(ValueError):
            validator_argv("solana-test-validator", PROGRAM, "https://api.mainnet-beta.solana.com", [])

    def test_execute_uses_only_the_local_argv(self):
        seen = []

        def runner(argv):
            seen.append(list(argv))
            return {"returncode": 0, "sent": False}

        report = plan_sim(
            PROGRAM,
            rpc="http://localhost:8899",
            clones=["So11111111111111111111111111111111111111112"],
            execute=True,
            runner=runner,
            binary="solana-test-validator",
        )
        self.assertTrue(report["executed"])
        self.assertEqual(len(seen), 1)
        self.assertNotIn("sendTransaction", seen[0])
        self.assertTrue(all(not item.startswith("https://") for item in seen[0]))
        self.assertEqual(report["heat_contribution"], 0)
        self.assertFalse(report["result"]["sent"])

    def test_missing_binary_skips_even_when_run_is_set(self):
        calls = []
        report = plan_sim(
            PROGRAM,
            rpc=LOCAL,
            execute=True,
            binary="",
            runner=lambda argv: calls.append(argv),
        )
        self.assertTrue(report["skipped"])
        self.assertFalse(report["executed"])
        self.assertEqual(calls, [])
        self.assertIn("not installed", report["reason"])


if __name__ == "__main__":
    unittest.main()
