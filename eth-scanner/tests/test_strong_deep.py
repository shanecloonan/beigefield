"""Strong-candidate selection and the live-only heat gate.

Engine findings are evidence. They must not move heat.
"""

from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.config import Settings
from eth_scanner.deep.runners import forge_fuzz_argv, mythril_argv, semgrep_argv
from eth_scanner.deep.source_tree import compiler_settings, write_verified_project
from eth_scanner.deep.strong import (
    DRAIN_PROBABILITY_STRONG_MIN,
    TIER1_MIN_FUNDS_USD,
    TIER2_MIN_FUNDS_USD,
    heat_if_live_confirmed,
    is_strong_candidate,
    run_strong_deep,
    select_strong,
)
from eth_scanner.feed.master_list import MasterCandidate
from eth_scanner.store.supabase import MemoryStore
from eth_scanner.types import SourceArtifact


def _cand(addr: str, tier: int, usd: float, rank: int, drain: float = 0.0) -> MasterCandidate:
    return MasterCandidate(
        address=addr, protocol="P", slug="p", category="Lending",
        est_usd_held=usd, candidate_reason="no-audit", tier=tier, rank=rank,
        drain_probability=drain, contract_class="Lending",
    )


class StrongSelection(unittest.TestCase):
    def test_thresholds_and_lane_b(self):
        self.assertEqual(TIER1_MIN_FUNDS_USD, 10_000.0)
        self.assertEqual(TIER2_MIN_FUNDS_USD, 100_000.0)
        self.assertFalse(is_strong_candidate(tier=1, funds_usd=9_999))
        self.assertTrue(is_strong_candidate(tier=1, funds_usd=10_000))
        self.assertFalse(is_strong_candidate(tier=2, funds_usd=50_000))
        self.assertTrue(is_strong_candidate(tier=2, funds_usd=100_000))
        self.assertFalse(is_strong_candidate(tier=3, funds_usd=5_000_000))
        self.assertTrue(is_strong_candidate(tier=3, funds_usd=100, heat=1))
        self.assertTrue(is_strong_candidate(tier=3, funds_usd=100, bucket="lane-b-queue"))
        self.assertEqual(DRAIN_PROBABILITY_STRONG_MIN, 0.60)
        self.assertTrue(is_strong_candidate(tier=3, funds_usd=100, drain_probability=0.60))
        self.assertFalse(is_strong_candidate(tier=3, funds_usd=100, drain_probability=0.59))

    def test_order_is_tier_then_usd(self):
        a = "0x" + "11" * 20
        b = "0x" + "22" * 20
        c = "0x" + "33" * 20
        rows = select_strong(
            [_cand(a, 2, 200_000, 3), _cand(b, 1, 12_000, 2), _cand(c, 1, 80_000, 1)],
            {},
        )
        self.assertEqual([item[0].address for item in rows], [c, b, a])

    def test_order_is_drain_probability_first(self):
        hot = "0x" + "aa" * 20
        rich = "0x" + "bb" * 20
        rows = select_strong(
            [_cand(rich, 1, 9_000_000, 1, drain=0.10), _cand(hot, 3, 3_000, 9, drain=0.91)],
            {},
        )
        self.assertEqual([item[0].address for item in rows], [hot, rich])

    def test_live_funds_override_estimate(self):
        addr = "0x" + "ab" * 20
        rows = select_strong(
            [_cand(addr, 1, 50_000, 1)],
            {addr: {"funds_usd": 100, "heat": 0, "bucket": "lane-a-cool"}},
        )
        self.assertEqual(rows, [])


class HeatGate(unittest.TestCase):
    def test_engine_findings_do_not_change_heat(self):
        heat, changed, bd = heat_if_live_confirmed(4, 50_000, [
            {"id": "share-solvency", "status": "held"},
        ])
        self.assertEqual(heat, 4)
        self.assertFalse(changed)
        self.assertEqual(bd["engine_heat"], 0)

    def test_live_failure_can_raise_heat(self):
        heat, changed, bd = heat_if_live_confirmed(0, 50_000, [
            {"id": "share-solvency", "status": "failed"},
        ])
        self.assertTrue(changed)
        self.assertGreater(heat, 0)
        self.assertEqual(bd["engine_heat"], 0)
        self.assertEqual(bd["corroborated_leads"], 0)


class EngineCommands(unittest.TestCase):
    def test_mythril_is_bounded_and_semgrep_is_rules_only(self):
        cmd = mythril_argv("myth", "A.sol", execution_timeout=300, max_depth=22)
        self.assertIn("--execution-timeout", cmd)
        self.assertIn("300", cmd)
        self.assertIn("--max-depth", cmd)
        self.assertIn("22", cmd)
        self.assertNotIn("--rpc", cmd)
        sem = semgrep_argv("semgrep", "/proj", rules_dir="/rules")
        self.assertIn("p/solidity", sem)
        self.assertIn("/rules", sem)
        self.assertIn("--metrics=off", sem)
        fuzz = forge_fuzz_argv("forge", fork_url="https://rpc.example")
        self.assertIn("--fork-url", fuzz)
        self.assertNotIn("--broadcast", fuzz)
        self.assertNotIn("--unlocked", fuzz)

    def test_verified_tree_keeps_remappings(self):
        payload = {
            "sources": {"contracts/Vault.sol": {"content": "pragma solidity ^0.8.20; contract Vault {}"}},
            "settings": {"remappings": ["oz/=lib/oz/"], "optimizer": {"enabled": True, "runs": 200}},
        }
        art = SourceArtifact(
            kind="source", language="solidity", content=json.dumps(payload),
            src_confidence="high", compiler="v0.8.20+commit.a1b79de6", contract_name="Vault",
        )
        dest = Path("/tmp/strong-tree")
        if dest.exists():
            import shutil
            shutil.rmtree(dest)
        meta = write_verified_project(art, dest)
        self.assertEqual(meta["solc"], "0.8.20")
        self.assertIn("oz/=lib/oz/", meta["remappings"])
        self.assertTrue((dest / "contracts" / "Vault.sol").is_file())
        toml = (dest / "foundry.toml").read_text(encoding="utf-8")
        self.assertIn('solc = "0.8.20"', toml)
        self.assertEqual(compiler_settings(art.content)["optimizer"], True)


class StrongCursor(unittest.TestCase):
    def test_resume_and_persist_evidence_without_heat(self):
        addr = "0x" + "44" * 20
        path = Path("/tmp/strong-list.json")
        path.write_text(json.dumps([{
            "address": addr, "protocol": "P", "slug": "p", "category": "Lending",
            "est_usd_held": 20_000, "candidate_reason": "no-audit", "tier": 1, "rank": 1,
        }]), encoding="utf-8")
        store = MemoryStore()
        store.save_test_scan_run({
            "dedupe_key": "master-list:%s" % addr,
            "kind": "lane-a",
            "address": addr,
            "discovery_source": "master_list",
            "heat": 2,
            "bucket": "lane-a-cool",
            "funds_usd": 20_000,
            "tier": 1,
            "candidate_reason": "no-audit",
            "status": "done",
        })
        settings = Settings(dry_run=True, etherscan_api_keys=[], eth_rpc_url="")

        def scan(cand, light, funds):
            from eth_scanner.deep.findings import EngineFinding
            return {
                "status": "done",
                "heat_before": light.get("heat"),
                "findings": [EngineFinding(
                    id="slither:naming:1", engine="slither", rule="naming-convention",
                    title="naming", severity="info", confidence="low", funds_class="other",
                    evidence="contract Foo {}",
                )],
                "engine_runs": [{"engine": "slither", "status": "ok", "duration_ms": 12, "finding_count": 1}],
                "live_results": [{"id": "share-solvency", "status": "held"}],
            }

        progress = run_strong_deep(
            settings=settings, store=store, path=str(path), workers=1,
            deadline_monotonic=time.monotonic() + 5, scan_one=scan,
        )
        self.assertEqual(progress.strong, 1)
        self.assertEqual(progress.scanned, 1)
        self.assertEqual(progress.heat_changed, 0)
        self.assertEqual(progress.findings_stored, 1)
        deep = [r for r in store.test_runs if str(r.get("dedupe_key", "")).startswith("strong-deep:")]
        self.assertEqual(len(deep), 1)
        self.assertEqual(deep[0]["heat"], 0)
        self.assertIsInstance(deep[0]["heat_breakdown"], dict)
        self.assertFalse(deep[0]["heat_breakdown"].get("live_confirmed"))
        self.assertEqual(store.test_findings[0]["engine"], "slither")
        self.assertEqual(store.test_findings[0]["raw"]["heat_contribution"], 0)


if __name__ == "__main__":
    unittest.main()
