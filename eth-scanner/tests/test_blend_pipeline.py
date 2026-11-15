"""Blend lane: four engines, one receipt, heat only on caller profit."""

from __future__ import annotations

import os
import stat
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

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
            text = (root / "src" / "ConservationHarness.sol").read_text(encoding="utf-8")
            self.assertIn("StrategyVault", text)
            self.assertIn("Strategy", text)
            self.assertIn("check_no_caller_profit", text)
            self.assertIn("echidna_no_caller_profit", text)
            self.assertNotIn("broadcast", text.lower())
            self.assertTrue((root / "medusa.json").is_file())
            self.assertTrue((root / "echidna.yaml").is_file())


def _tool(path: Path, line: str) -> None:
    path.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$@\" >> \"$BLEND_ARGV\"\n" + line + "\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


class RealBinaryInvocation(unittest.TestCase):
    """The campaign shells out. These stand-ins prove the argv and the parser.

    A live pin check runs only when the real binary is already installed.
    """

    def _run(self, line: str, *, funds: float = 4_000.0):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            argv_log = root / "argv.txt"
            bins = {}
            for name in ("medusa", "echidna", "halmos", "ityfuzz"):
                dest = root / name
                _tool(dest, line)
                bins[name] = dest
            env = {
                "ETH_SCANNER_MEDUSA_BIN": str(bins["medusa"]),
                "ETH_SCANNER_ECHIDNA_BIN": str(bins["echidna"]),
                "ETH_SCANNER_HALMOS_BIN": str(bins["halmos"]),
                "ETH_SCANNER_ITYFUZZ_BIN": str(bins["ityfuzz"]),
                "ETH_SCANNER_BLEND_ANVIL": "0",
                "BLEND_ARGV": str(argv_log),
            }
            with mock.patch.dict(os.environ, env, clear=False):
                report = run_blend(
                    address="0x" + "11" * 20,
                    contract_name="Target",
                    source="contract Target { function skim() external {} }",
                    funds_usd=funds,
                    fork_url="http://127.0.0.1:8545",
                    timeout_s=10,
                )
            recorded = argv_log.read_text(encoding="utf-8") if argv_log.is_file() else ""
            return report, recorded

    def test_shells_out_and_evidence_without_profit_stays_cold(self):
        report, recorded = self._run("echo '[FAIL] no_third_party_balance_drop caller_profit_delta=0'")
        notes = " ".join(row.get("note") or "" for row in report["engines"])
        self.assertIn("invoked", notes)
        self.assertNotIn("campaign not started", notes)
        self.assertIn("fuzz", recorded)
        self.assertIn("ConservationHarness", recorded)
        self.assertIn("check_no_caller_profit", recorded)
        self.assertIn("-c", recorded)
        self.assertIn("local", recorded)
        self.assertNotIn("flashloan", recorded.lower())
        self.assertNotIn("broadcast", recorded.lower())
        self.assertEqual(report["heat"], 0)
        self.assertTrue(report["findings"])
        self.assertTrue(all(row["label"] == "evidence only" for row in report["findings"]))
        self.assertTrue(all(row["heat_contribution"] == 0 for row in report["findings"]))

    def test_shell_out_profit_still_uses_the_caller_profit_gate(self):
        report, _recorded = self._run(
            "echo '[FAIL] no_third_party_balance_drop caller_profit_delta=9'",
            funds=8_000.0,
        )
        proofs = [row for row in report["findings"] if row["kind"] == "drain-proof"]
        self.assertTrue(proofs)
        self.assertGreater(proofs[0]["caller_profit_delta"], 0)
        self.assertGreater(report["heat"], 0)
        self.assertTrue(report["heat_breakdown"]["caller_profit_gate"])
        self.assertEqual(report["heat_breakdown"]["engine_heat"], 0)

    def test_real_binary_versions_when_installed(self):
        import shutil
        import subprocess

        expected = {
            "medusa": "1.5.1",
            "echidna": "2.4.0",
            "halmos": "0.3.3",
        }
        for name, version in expected.items():
            path = shutil.which(name)
            if not path:
                continue
            proc = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=20, check=False)
            if proc.returncode != 0 and name == "medusa":
                proc = subprocess.run([path, "version"], capture_output=True, text=True, timeout=20, check=False)
            blob = (proc.stdout or "") + (proc.stderr or "")
            self.assertIn(version, blob, name)
        ity = shutil.which("ityfuzz")
        if ity:
            proc = subprocess.run([ity, "--help"], capture_output=True, text=True, timeout=20, check=False)
            self.assertEqual(proc.returncode, 0)


class FullGauntletOnTheDefaultScan(unittest.TestCase):
    def test_lane_a_then_engines_and_adaptations_do_not_add_heat(self):
        from eth_scanner.config import Settings
        from eth_scanner.feed import runner as feed
        from eth_scanner.types import FunnelResult

        result = FunnelResult(
            bucket="lane-a-cool",
            dropped=False,
            drop_reason=None,
            heat=0,
            src_confidence="high",
            ir_confidence="med",
            funds_usd=4000.0,
            contract_name="Target",
        )
        report = {
            "bucket": "no",
            "heat": 0,
            "heat_breakdown": {"caller_profit_gate": False, "engine_heat": 0},
            "engines": [
                {"engine": name, "status": "ok"}
                for name in ("ityfuzz", "halmos", "medusa", "echidna")
            ],
            "adaptations": {
                name: {"heat_contribution": 0}
                for name in ("syzkaller", "restler", "daikon", "lithium", "jepsen")
            },
            "findings": [],
        }
        settings = Settings(dry_run=True, work_dir=Path("/tmp/blend-gauntlet"))
        with mock.patch("eth_scanner.lane_a.worker.run_one", return_value=result), \
             mock.patch("eth_scanner.feed.runner.open_store", return_value=object()), \
             mock.patch("eth_scanner.deep.blend.orchestrator.run_blend", return_value=report) as blend:
            out = feed._default_scan("0x" + "11" * 20, settings)
        blend.assert_called_once()
        self.assertEqual(out.heat, 0)
        summary = out.blend_summary
        self.assertEqual(
            [row["engine"] for row in summary["engines"]],
            ["ityfuzz", "halmos", "medusa", "echidna"],
        )
        self.assertEqual(summary["adaptations"]["syzkaller"]["heat_contribution"], 0)
        self.assertEqual(summary["adaptations"]["lithium"]["heat_contribution"], 0)
        self.assertEqual(summary["adaptations"]["jepsen"]["heat_contribution"], 0)
        self.assertFalse(summary["caller_profit_gate"])


class BlendLists(unittest.TestCase):
    def test_list2_band_and_list1_strong_rules(self):
        rows, dropped = load_list2()
        self.assertEqual(dropped, 0)
        self.assertEqual(len(rows), 214)
        self.assertTrue(all(50 <= row["est_usd_held"] <= 1900 for row in rows))
        self.assertTrue(all(row["deep_lane"] for row in rows))
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
