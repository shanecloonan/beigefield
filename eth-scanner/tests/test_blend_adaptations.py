"""Adaptation layer: coverage without heat, heat only with a profit witness."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.deep.blend.adapt import apply_adaptations
from eth_scanner.deep.blend.adapt.daikon import mine, violations
from eth_scanner.deep.blend.adapt.jepsen import check_history, schedule
from eth_scanner.deep.blend.adapt.lithium import ddmin, still_profitable
from eth_scanner.deep.blend.adapt.restler import infer_edges
from eth_scanner.deep.blend.adapt.syzkaller import PROTOCOL, chain_is_legal, dependent_chains
from eth_scanner.deep.blend.adapt.versions import ADAPTATION_PINS
from eth_scanner.deep.blend.orchestrator import run_blend


class SubprocessEvidenceStaysCold(unittest.TestCase):
    def test_invoked_engine_output_without_profit_adds_no_adaptation_heat(self):
        import os
        import stat
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "engine"
            script.write_text(
                "#!/bin/sh\necho '[FAIL] solvency caller_profit_delta=0'\n",
                encoding="utf-8",
            )
            script.chmod(script.stat().st_mode | stat.S_IEXEC)
            env = {
                "ETH_SCANNER_MEDUSA_BIN": str(script),
                "ETH_SCANNER_ECHIDNA_BIN": str(script),
                "ETH_SCANNER_HALMOS_BIN": str(script),
                "ETH_SCANNER_ITYFUZZ_BIN": str(script),
                "ETH_SCANNER_BLEND_ANVIL": "0",
            }
            with mock.patch.dict(os.environ, env, clear=False):
                report = run_blend(
                    address="0x" + "33" * 20,
                    contract_name="Target",
                    source="contract Target { function skim() external {} }",
                    funds_usd=2_000,
                    fork_url="http://127.0.0.1:8545",
                    timeout_s=10,
                )
        self.assertEqual(report["heat"], 0)
        self.assertEqual(report["adaptations"]["syzkaller"]["heat_contribution"], 0)
        self.assertEqual(report["adaptations"]["daikon"]["heat_contribution"], 0)
        self.assertTrue(any("invoked" in (row.get("note") or "") for row in report["engines"]))


class AdaptationPins(unittest.TestCase):
    def test_pins_are_set(self):
        for name in ("syzkaller", "restler", "daikon", "lithium", "creduce", "jepsen"):
            self.assertTrue(ADAPTATION_PINS[name]["version"])
            self.assertTrue(ADAPTATION_PINS[name]["upstream"].startswith("https://github.com/"))


class SyzkallerDsl(unittest.TestCase):
    def test_chains_respect_resources_and_add_no_heat(self):
        report = run_blend(fixture="safe")
        chains = report["adaptations"]["syzkaller"]["sequences"]
        self.assertTrue(chains)
        self.assertTrue(all(chain_is_legal(chain, PROTOCOL) for chain in chains))
        harvest = next(chain for chain in chains if "Strategy.harvest" in chain)
        self.assertLess(harvest.index("Vault.deposit"), harvest.index("Strategy.harvest"))
        self.assertLess(harvest.index("Oracle.setAnswer"), harvest.index("Strategy.harvest"))
        self.assertEqual(report["adaptations"]["syzkaller"]["heat_contribution"], 0)
        self.assertEqual(report["heat"], 0)


class RestlerEdges(unittest.TestCase):
    def test_deposit_feeds_harvest_on_a_sibling(self):
        edges = infer_edges()
        hit = next(
            edge for edge in edges
            if edge["producer"] == "Vault.deposit" and edge["consumer"] == "Strategy.harvest"
        )
        self.assertEqual(hit["resource"], "shares")
        self.assertTrue(hit["sibling"])
        report = run_blend(fixture="safe")
        self.assertEqual(report["adaptations"]["restler"]["heat_contribution"], 0)
        self.assertEqual(report["heat"], 0)


class DaikonMining(unittest.TestCase):
    def test_mined_break_without_profit_adds_no_heat(self):
        report = run_blend(fixture="evidence-only")
        mined = report["adaptations"]["daikon"]
        self.assertTrue(any(row["kind"] == "equality" for row in mined["invariants"]))
        self.assertTrue(mined["properties"])
        self.assertTrue(mined["violations"])
        self.assertTrue(all(row["label"] == "evidence only" for row in mined["violations"]))
        self.assertEqual(mined["heat_contribution"], 0)
        self.assertEqual(report["heat"], 0)

    def test_profit_witness_on_a_mined_break_can_heat(self):
        held = [
            {"vault_assets": 10.0, "share_value": 10.0, "share_price": 1.0},
            {"vault_assets": 12.0, "share_value": 12.0, "share_price": 1.1},
        ]
        invariants = mine(held)
        broken = violations(invariants, {
            "vault_assets": 1.0,
            "share_value": 12.0,
            "share_price": 1.0,
            "caller_profit_delta": 40,
        })
        self.assertTrue(broken)
        self.assertEqual(broken[0]["kind"], "drain-proof")
        self.assertEqual(broken[0]["heat_contribution"], 0)
        cold = run_blend(fixture="safe")
        heated = apply_adaptations(cold, plan={
            "profit_calls": [],
            "script": ["view_price"],
            "sample": {
                "vault_assets": 1.0,
                "share_value": 12.0,
                "share_price": 1.0,
                "caller_profit_delta": 40,
            },
            "history_ops": [
                {"actor": "oracle", "call": "setAnswer"},
                {"actor": "attacker", "call": "view", "caller_profit_delta": 0},
            ],
            "seed": 2,
        })
        self.assertGreater(heated["heat"], 0)
        self.assertEqual(heated["adaptations"]["daikon"]["heat_contribution"], 0)


class LithiumReduce(unittest.TestCase):
    def test_one_minimal_profit_script_and_zero_heat_without_one(self):
        shrunk = ddmin(
            ["view_price", "noop", "Strategy.skim", "noop", "view_shares"],
            lambda seq: still_profitable(seq, ["Strategy.skim"]),
        )
        self.assertEqual(shrunk, ["Strategy.skim"])
        self.assertEqual(ddmin(["view_price", "noop"], lambda seq: still_profitable(seq, ["Strategy.skim"])), [])
        report = run_blend(fixture="leaky-strategy")
        self.assertEqual(report["adaptations"]["lithium"]["minimized_calls"], ["Strategy.skim"])
        self.assertEqual(report["adaptations"]["lithium"]["heat_contribution"], 0)
        self.assertGreater(report["heat"], 0)
        cold = run_blend(fixture="safe")
        self.assertEqual(cold["adaptations"]["lithium"]["minimized_calls"], [])
        self.assertEqual(cold["heat"], 0)


class JepsenHistory(unittest.TestCase):
    def test_seed_replay_and_ordering_without_profit_is_cold(self):
        ops = [
            {"actor": "keeper", "call": "harvest"},
            {"actor": "oracle", "call": "setAnswer"},
            {"actor": "victim", "call": "balance_drop"},
            {"actor": "attacker", "call": "view", "caller_profit_delta": 0},
        ]
        self.assertEqual(schedule(ops, 9), schedule(ops, 9))
        ordered = check_history([
            {"index": 0, "actor": "keeper", "call": "harvest", "caller_profit_delta": 0},
            {"index": 1, "actor": "oracle", "call": "setAnswer", "caller_profit_delta": 0},
        ])
        self.assertEqual(ordered["label"], "evidence only")
        self.assertEqual(ordered["heat_contribution"], 0)
        self.assertEqual(ordered["caller_profit_delta"], 0)
        report = run_blend(fixture="safe")
        self.assertTrue(report["adaptations"]["jepsen"]["replay_matches_seed"])
        self.assertEqual(report["adaptations"]["jepsen"]["heat_contribution"], 0)
        self.assertEqual(report["heat"], 0)


class CrossContractBundle(unittest.TestCase):
    def test_strategy_fixture_keeps_four_engines_and_the_five_passes(self):
        report = run_blend(fixture="leaky-strategy")
        self.assertEqual(report["target"]["contracts"], ["StrategyVault", "Strategy"])
        self.assertEqual(set(report["adaptations"]), {"syzkaller", "restler", "daikon", "lithium", "jepsen"})
        self.assertTrue(dependent_chains())
        self.assertGreater(report["heat"], 0)


if __name__ == "__main__":
    unittest.main()
