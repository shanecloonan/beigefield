"""Blend lane: four engines, one receipt, heat only on caller profit."""

from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.deep.blend.fixtures import FIXTURES, logs_for
from eth_scanner.deep.blend.harness import write_project
from eth_scanner.deep.blend.ityfuzz_runner import ityfuzz_argv
from eth_scanner.deep.blend.orchestrator import EngineOutput, run_blend, schedule
from eth_scanner.deep.blend.versions import PINNED
from eth_scanner.feed.lists import catalog, load_list2, select_deep
from eth_scanner.known_safe import SAFE_ADDRESSES

LINK = "0x514910771af9ca656af840dff83e8264ecf986ca"


class BlendFixtures(unittest.TestCase):
    def test_pins(self):
        self.assertEqual(PINNED["medusa"]["version"], "1.5.1")
        self.assertEqual(PINNED["echidna"]["version"], "2.4.0")
        self.assertEqual(PINNED["halmos"]["version"], "0.3.3")
        self.assertTrue(PINNED["ityfuzz"]["version"].startswith("nightly-"))

    def test_leaky_vault_is_a_drain_proof(self):
        report = run_blend(fixture="leaky")
        self.assertEqual(report["bucket"], "drain-found")
        self.assertGreaterEqual(report["heat"], 3)
        proofs = [row for row in report["findings"] if row["kind"] == "drain-proof"]
        self.assertEqual(len(proofs), 1)
        self.assertGreater(proofs[0]["caller_profit_delta"], 0)
        self.assertEqual(proofs[0]["agreement_count"], 4)
        self.assertEqual(proofs[0]["agreement_score"], 1.0)
        self.assertEqual(sorted(proofs[0]["engines_agreeing"]), ["echidna", "halmos", "ityfuzz", "medusa"])
        self.assertEqual(proofs[0]["label"], "drain proof")
        self.assertNotIn("0x", proofs[0]["evidence"])
        self.assertTrue(report["heat_breakdown"]["caller_profit_gate"])

    def test_safe_vault_stays_cold(self):
        report = run_blend(fixture="safe")
        self.assertEqual(report["heat"], 0)
        self.assertEqual(report["bucket"], "no")
        self.assertEqual(report["findings"], [])
        self.assertFalse(report["heat_breakdown"]["caller_profit_gate"])

    def test_multi_contract_strategy_is_a_drain_proof(self):
        report = run_blend(fixture="leaky-strategy")
        self.assertEqual(report["target"]["contracts"], ["StrategyVault", "Strategy"])
        self.assertEqual(report["bucket"], "drain-found")
        self.assertGreater(report["heat"], 0)
        proof = report["findings"][0]
        self.assertEqual(proof["kind"], "drain-proof")
        self.assertEqual(proof["call_path"], "skim")
        self.assertGreater(proof["caller_profit_delta"], 0)

    def test_evidence_only_adds_zero_heat(self):
        report = run_blend(fixture="evidence-only")
        self.assertEqual(report["heat"], 0)
        self.assertEqual(report["bucket"], "maybe")
        self.assertEqual(len(report["findings"]), 1)
        finding = report["findings"][0]
        self.assertEqual(finding["kind"], "evidence-only")
        self.assertEqual(finding["label"], "evidence only")
        self.assertEqual(finding["heat_contribution"], 0)
        self.assertEqual(finding["agreement_score"], 1.0)
        self.assertEqual(finding["confidence"], "high")
        self.assertFalse(report["heat_breakdown"]["caller_profit_gate"])
        self.assertGreaterEqual(len(report["groups"]), 4)

    def test_setup_failure_is_a_skip(self):
        logs = {name: "setUp() failed to compile" for name in ("ityfuzz", "halmos", "medusa", "echidna")}
        report = run_blend(logs=logs, funds_usd=50_000, address="0x" + "11" * 20)
        self.assertEqual(report["heat"], 0)
        self.assertEqual(report["findings"], [])
        self.assertTrue(all(row["status"] == "skipped" for row in report["engines"]))

    def test_known_safe_stays_cold_even_with_a_profit_log(self):
        self.assertIn(LINK, SAFE_ADDRESSES)
        report = run_blend(
            logs=logs_for(FIXTURES["leaky"]),
            address=LINK,
            contract_name="LinkToken",
            funds_usd=5_000_000,
        )
        self.assertEqual(report["heat"], 0)
        self.assertTrue(report["heat_breakdown"]["known_safe"])
        self.assertGreater(report["findings"][0]["caller_profit_delta"], 0)

    def test_empty_balance_does_not_heat(self):
        report = run_blend(logs=logs_for(FIXTURES["leaky"]), funds_usd=0, address="0x" + "22" * 20)
        self.assertEqual(report["heat"], 0)
        self.assertEqual(report["heat_breakdown"]["gate_reason"], "no value held · heat 0")

    def test_incentive_without_profit_is_evidence(self):
        report = run_blend(fixture="incentive")
        self.assertEqual(report["heat"], 0)
        finding = report["findings"][0]
        self.assertEqual(finding["kind"], "incentive")
        self.assertEqual(finding["label"], "evidence only")
        self.assertEqual(finding["heat_contribution"], 0)
        self.assertIn("first caller", finding["incentive"]["who_benefits"])

    def test_missing_source_skips(self):
        report = run_blend(address="0x" + "ab" * 20, funds_usd=10_000)
        self.assertEqual(report["heat"], 0)
        self.assertTrue(all(row["status"] == "skipped" for row in report["engines"]))

    def test_fork_engines_do_not_overlap(self):
        state = {"fork": 0, "max": 0, "overlap": 0}
        lock = threading.Lock()

        def fork_runner(name):
            def run(_ctx):
                with lock:
                    state["fork"] += 1
                    state["max"] = max(state["max"], state["fork"])
                time.sleep(0.05)
                with lock:
                    state["fork"] -= 1
                return EngineOutput(name, "ok", log="")
            return run

        def halmos(_ctx):
            time.sleep(0.08)
            with lock:
                if state["fork"] > 0:
                    state["overlap"] += 1
            return EngineOutput("halmos", "ok", log="")

        runners = {
            "medusa": fork_runner("medusa"),
            "echidna": fork_runner("echidna"),
            "ityfuzz": fork_runner("ityfuzz"),
            "halmos": halmos,
        }
        schedule(runners)
        self.assertEqual(state["max"], 1)
        self.assertGreaterEqual(state["overlap"], 1)

    def test_ityfuzz_argv_stays_on_loopback(self):
        argv = ityfuzz_argv("ityfuzz", ["0x" + "11" * 20], "http://127.0.0.1:8545")
        blob = " ".join(argv)
        self.assertNotIn("flashloan", blob)
        self.assertNotIn("broadcast", blob)
        self.assertIn("-c", argv)
        self.assertIn("local", argv)
        with self.assertRaises(ValueError):
            ityfuzz_argv("ityfuzz", ["0x" + "11" * 20], "https://eth.llamarpc.com")

    def test_harness_names_the_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = write_project(Path(tmp), [
                {"name": "StrategyVault", "source": "contract StrategyVault { function skim() external {} }"},
                {"name": "Strategy", "source": "contract Strategy { function skim() external {} }"},
            ])
            text = (root / "test" / "Conservation.t.sol").read_text(encoding="utf-8")
            self.assertIn("StrategyVault", text)
            self.assertIn("Strategy", text)
            self.assertNotIn("broadcast", text.lower())
            self.assertTrue((root / "medusa.json").is_file())
            self.assertTrue((root / "echidna.yaml").is_file())


class BlendLists(unittest.TestCase):
    def test_list2_band_and_list1_strong_rules(self):
        rows, dropped = load_list2()
        self.assertEqual(dropped, 2)
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(50 <= row["est_usd_held"] <= 1900 for row in rows))
        info = catalog()
        by_id = {row["id"]: row for row in info["lists"]}
        self.assertGreater(by_id["list-1"]["count"], 100)
        self.assertGreater(by_id["list-1"]["deep_count"], 0)
        self.assertEqual(by_id["list-2"]["min_usd"], 50)
        self.assertEqual(by_id["list-2"]["max_usd"], 1900)
        strong = select_deep("list-1")
        self.assertTrue(all(row["deep_lane"] for row in strong))
        self.assertLess(len(strong), by_id["list-1"]["count"])
        demanded = select_deep("list-2", address="0x" + "cd" * 20)
        self.assertEqual(len(demanded), 1)
        self.assertTrue(demanded[0]["deep_lane"])
        self.assertEqual(demanded[0]["source"], "on-demand")


if __name__ == "__main__":
    unittest.main()
