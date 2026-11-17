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
        self.assertEqual(len(rows), 428)
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


class EnsembleLayers(unittest.TestCase):
    """New layers are evidence. Heat still requires a caller-profit witness."""

    def _layers(self, report):
        return report["layers"]

    def test_each_layer_is_cold_without_a_caller_profit_witness(self):
        report = run_blend(fixture="safe")
        self.assertEqual(report["heat"], 0)
        self.assertEqual(report["findings"], [])
        for name in ("facts", "spec", "symbolic", "fuzz", "mutation", "fusion"):
            block = self._layers(report)[name]
            self.assertEqual(block["heat_contribution"], 0, name)
            self.assertEqual(block["label"], "evidence only", name)
        self.assertIn("no-unprivileged-caller-profit", report["layers"]["spec"]["selected"])
        self.assertFalse(report["layers"]["fusion"]["proven_caller_profit"])
        self.assertGreater(report["drain_probability"], 0)

    def test_evidence_only_stays_labeled_and_cold(self):
        report = run_blend(fixture="evidence-only")
        self.assertEqual(report["heat"], 0)
        self.assertEqual(report["findings"][0]["label"], "evidence only")
        self.assertEqual(report["findings"][0]["kind"], "evidence-only")
        self.assertTrue(all(block["heat_contribution"] == 0 for block in report["layers"].values()))
        self.assertFalse(report["layers"]["fusion"]["proven_caller_profit"])

    def test_drain_proof_label_stays_on_the_witness_and_layers_stay_cold(self):
        leaky = run_blend(fixture="leaky")
        safe = run_blend(fixture="safe")
        proof = leaky["findings"][0]
        self.assertEqual(proof["kind"], "drain-proof")
        self.assertEqual(proof["label"], "drain proof")
        self.assertEqual(proof["agreement_count"], 4)
        self.assertGreater(leaky["heat"], 0)
        self.assertTrue(all(block["heat_contribution"] == 0 for block in leaky["layers"].values()))
        self.assertGreater(leaky["drain_probability"], safe["drain_probability"])
        self.assertIn("unprivileged-caller-profit", leaky["bug_classes"])
        self.assertTrue(leaky["layers"]["fusion"]["passes_agreeing"])

    def test_known_safe_contracts_stay_cold(self):
        from eth_scanner.known_safe import SAFE_ADDRESSES

        sand = "0x3845badade8e6dff049820680d1f14bd3903a5d0"
        hex_token = "0x2b591e99afe9f32eaa6214f7b7629768c40eeb39"
        bento = "0xf5bce5077908a1b7370b9ae04adc565ebd643966"
        for addr in (LINK, sand, hex_token, bento):
            self.assertIn(addr, SAFE_ADDRESSES)
        named = (
            (LINK, "LinkToken"),
            (sand, "SAND"),
            (hex_token, "HEX"),
            (bento, "BentoBoxV1"),
        )
        for addr, name in named:
            report = run_blend(
                logs=logs_for(FIXTURES["leaky"]),
                address=addr,
                contract_name=name,
                funds_usd=5_000_000,
            )
            self.assertEqual(report["heat"], 0, name)
            self.assertTrue(report["heat_breakdown"]["known_safe"], name)
            self.assertTrue(all(block["heat_contribution"] == 0 for block in report["layers"].values()), name)
            self.assertEqual(report["findings"][0]["label"], "drain proof")

    def test_facts_seed_erc4626_properties_and_the_harness(self):
        from eth_scanner.deep.blend.ensemble.facts import collect_facts
        from eth_scanner.deep.blend.ensemble.spec import build_spec

        source = (
            "contract Vault {"
            " function deposit(uint256 assets, address receiver) external {}"
            " function withdraw(uint256 assets) external {}"
            " function convertToAssets(uint256 shares) external view returns (uint256) { return shares; }"
            "}"
        )
        facts = collect_facts(source, "Vault", live=False)
        self.assertEqual(facts["shape"], "erc4626")
        self.assertEqual(facts["heat_contribution"], 0)
        spec = build_spec(facts)
        self.assertIn("erc4626-share-price", spec["selected"])
        self.assertIn("no-unprivileged-caller-profit", spec["selected"])
        self.assertTrue(spec["seeded_by"])
        self.assertEqual(spec["heat_contribution"], 0)
        with tempfile.TemporaryDirectory() as tmp:
            root = write_project(
                Path(tmp),
                [{"name": "Vault", "source": source}],
                facts=facts,
                properties=spec["selected"],
            )
            text = (root / "src" / "ConservationHarness.sol").read_text(encoding="utf-8")
            self.assertIn("deposit(uint256,address)", text)
            self.assertIn("convertToAssets(uint256)", text)
            self.assertIn("invariant_no_caller_profit", text)
            self.assertIn("property_erc4626_share_price", text)
            self.assertNotIn("broadcast", text.lower())

    def test_mutation_without_a_measured_delta_does_not_heat(self):
        from eth_scanner.deep.blend.ensemble.mutation import run_mutation

        cold = run_mutation(["no-unprivileged-caller-profit"], replay_delta=0)
        self.assertEqual(cold["heat_contribution"], 0)
        self.assertTrue(cold["killed"])
        self.assertEqual(cold["witnesses"], [])
        self.assertFalse(cold["vacuous"])

    def test_profit_relevant_survivor_is_routed_only_with_a_delta(self):
        from eth_scanner.deep.blend.ensemble import finalize_ensemble
        from eth_scanner.deep.blend.ensemble.mutation import run_mutation

        witnessed = run_mutation(["erc4626-share-price"], replay_delta=40)
        self.assertTrue(witnessed["witnesses"])
        self.assertEqual(witnessed["heat_contribution"], 0)
        self.assertTrue(witnessed["survivors"][0]["routed_to_fork_gate"])
        base = run_blend(fixture="safe")
        base["target"]["address"] = "0x" + "44" * 20
        base["target"]["funds_usd"] = 5_000
        base["target"]["contract_name"] = "OddVault"
        prepared = {name: base["layers"][name] for name in ("facts", "spec", "symbolic", "fuzz")}
        prepared["mutation"] = witnessed
        heated = finalize_ensemble(base, prepared=prepared)
        self.assertGreater(heated["heat"], 0)
        self.assertEqual(heated["layers"]["mutation"]["heat_contribution"], 0)
        self.assertTrue(heated["heat_breakdown"]["caller_profit_gate"])
        self.assertEqual(heated["findings"][0]["label"], "drain proof")

    def test_smt_and_foundry_skips_are_evidence(self):
        report = run_blend(fixture="safe")
        smt = report["layers"]["symbolic"]["smtchecker"]
        self.assertEqual(smt["heat_contribution"], 0)
        self.assertEqual(smt["caller_profit_delta"], 0)
        self.assertIn("chc", smt)
        self.assertIn("bmc", smt)
        self.assertEqual(report["layers"]["fuzz"]["foundry"]["heat_contribution"], 0)
        self.assertEqual(report["layers"]["fuzz"]["foundry"]["caller_profit_delta"], 0)

    def test_discovery_floor_is_100_and_env_configurable(self):
        from eth_scanner.config import Settings
        from eth_scanner.feed.runner import random_funds_bounds
        from eth_scanner.heat import HeatWeights
        from eth_scanner.ingest.funds import DEFAULT_DISCOVERY_MIN_USD, discovery_min_usd

        self.assertEqual(DEFAULT_DISCOVERY_MIN_USD, 100.0)
        settings = Settings(dry_run=True, work_dir=Path("/tmp/blend-discovery"), min_funds_usd=2000.0)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ETH_SCANNER_DISCOVERY_MIN_USD", None)
            os.environ.pop("ETH_SCANNER_DISCOVERY_MAX_USD", None)
            self.assertEqual(discovery_min_usd(), 100.0)
            low, high = random_funds_bounds(settings)
            self.assertEqual(low, 100.0)
            self.assertIsNone(high)
        with mock.patch.dict(os.environ, {"ETH_SCANNER_DISCOVERY_MIN_USD": "250"}, clear=False):
            self.assertEqual(discovery_min_usd(), 250.0)
            low, _high = random_funds_bounds(settings)
            self.assertEqual(low, 250.0)
        # Lane-B promotion floor tracks the live scanner floor ($100), and is
        # a separate knob from ETH_SCANNER_DISCOVERY_MIN_USD.
        self.assertEqual(HeatWeights().min_funds_for_lane_b, 100.0)

    def test_each_stage_is_persisted_and_a_failed_write_marks_the_run(self):
        from eth_scanner.deep.blend.journal import PersistError
        from eth_scanner.store.supabase import MemoryStore

        store = MemoryStore()
        report = run_blend(fixture="safe", store=store)
        stages = [row["stage"] for row in store.blend_stages]
        for name in ("intake", "facts", "spec", "symbolic", "fuzz", "mutation", "fusion", "decision"):
            self.assertIn(name, stages, name)
        for name in ("syzkaller", "restler", "daikon", "lithium", "jepsen", "randoop", "learnlib", "stateright", "pict", "openspiel", "picire"):
            self.assertIn("adapt-%s" % name, stages)
        self.assertEqual(report["persistence"]["mode"], "memory")
        run = next(row for row in store.test_runs if row["dedupe_key"] == report["persistence"]["dedupe_key"])
        self.assertEqual(run["status"], "done")
        self.assertEqual(run["discovery_source"], "blend")
        self.assertEqual(run["funds_usd"], 1000.0)
        self.assertEqual(run["blend_bucket"], "no")
        self.assertFalse(run["proven_caller_profit"])
        self.assertTrue(run["evidence_only"])
        self.assertIsNotNone(run["started_at"])
        self.assertTrue(store.test_findings)

        class BoomStore(MemoryStore):
            def save_blend_stage(self, row):
                if row.get("stage") == "spec":
                    raise RuntimeError("supabase write failed")
                return super().save_blend_stage(row)

        boom = BoomStore()
        with self.assertRaises(PersistError):
            run_blend(fixture="safe", store=boom)
        saved = [row["stage"] for row in boom.blend_stages]
        self.assertIn("intake", saved)
        self.assertIn("facts", saved)
        self.assertNotIn("spec", saved)
        marked = next(row for row in boom.test_runs if str(row.get("dedupe_key") or "").startswith("blend:"))
        self.assertEqual(marked["status"], "error")
        self.assertIn("supabase write failed", marked["error"])


if __name__ == "__main__":
    unittest.main()
