"""Static-analysis evidence: weights, fetch cache, store, heat component."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.deep.runners import EngineRunResult
from eth_scanner.heat import evidence_heat
from eth_scanner.logic.source_fetch import fetch_verified_source, solidity_from_payload
from eth_scanner.logic.static_norm import clean_evidence, score_static
from eth_scanner.logic.static_run import local_semgrep_argv, run_static_command
from eth_scanner.store.supabase import MemoryStore, SupabaseStore


ADDR = "0x1111111111111111111111111111111111111111"


class Weights(unittest.TestCase):
    def test_high_detector_weighs_more_than_medium(self):
        scored = score_static([
            {"engine": "slither", "rule": "arbitrary-send-eth", "evidence": "sends eth"},
            {"engine": "slither", "rule": "tx-origin", "evidence": "origin check"},
            {"engine": "slither", "rule": "timestamp", "evidence": "block.timestamp"},
        ])
        self.assertEqual(scored["points"], 4)
        self.assertEqual(scored["high"], 1)
        self.assertEqual(scored["medium"], 1)

    def test_cap_and_duplicate_rule(self):
        rows = [
            {"engine": "slither", "rule": "suicidal", "function": "close"},
            {"engine": "aderyn", "rule": "public-selfdestruct", "function": "close"},
            {"engine": "slither", "rule": "unprotected-upgrade", "function": "upgrade"},
            {"engine": "slither", "rule": "reentrancy-eth", "function": "withdraw"},
        ]
        scored = score_static(rows)
        self.assertEqual(scored["points"], 6)
        counted = [row for row in scored["rows"] if row["counted"]]
        self.assertEqual(len(counted), 2)

    def test_admin_gated_hit_is_zero(self):
        scored = score_static([{
            "engine": "slither",
            "rule": "missing-zero-check",
            "title": "onlyOwner withdraw",
            "evidence": "AccessControl onlyRole(DEFAULT_ADMIN_ROLE) gates this call",
            "severity": "high",
            "confidence": "high",
        }])
        self.assertEqual(scored["points"], 0)
        self.assertFalse(scored["rows"][0]["counted"])

    def test_unprotected_initializer_still_counts(self):
        scored = score_static([{
            "engine": "semgrep",
            "rule": "beigefield.unprotected-initializer",
            "evidence": "public initialize assigns owner with no initializer guard",
            "generic": True,
        }])
        self.assertEqual(scored["points"], 3)
        self.assertEqual(scored["rows"][0]["rule"], "unprotected-initializer")

    def test_evidence_drops_calldata(self):
        text = clean_evidence("see 0x" + "ab" * 20 + " at https://example.invalid/poc")
        self.assertNotIn("abab", text)
        self.assertNotIn("http", text)

    def test_aderyn_alias(self):
        scored = score_static([{
            "engine": "aderyn",
            "rule": "reentrancy-state-change",
            "evidence": "state write after call",
        }])
        self.assertEqual(scored["rows"][0]["rule"], "reentrancy-eth")
        self.assertEqual(scored["points"], 3)


class Heat(unittest.TestCase):
    def test_absent_static_leaves_existing_heat(self):
        heat, bd = evidence_heat(funds_usd=1_000_000, invariant_results=[])
        self.assertEqual(heat, 0)
        self.assertEqual(bd["static_evidence"], 0)
        self.assertNotIn("static_findings", bd)

    def test_static_does_not_unlock_a_bare_shape_lead(self):
        source = "function deposit() external { uint256 bal = token.balanceOf(address(this)); _mint(msg.sender, bal); }"
        heat, bd = evidence_heat(
            funds_usd=50_000,
            invariant_results=[],
            source=source,
            static_findings=[{"engine": "slither", "rule": "arbitrary-send-eth", "evidence": "send"}],
        )
        self.assertEqual(bd["gated_leads"], 0)
        self.assertEqual(bd["static_evidence"], 3)
        self.assertEqual(heat, 3)

    def test_static_stacks_under_the_ceiling(self):
        heat, bd = evidence_heat(
            funds_usd=200_000,
            invariant_results=[{"id": "erc4626-asset-shortfall", "status": "failed", "evidence": "short"}],
            static_findings=[
                {"engine": "slither", "rule": "arbitrary-send-eth", "function": "a"},
                {"engine": "slither", "rule": "suicidal", "function": "b"},
                {"engine": "slither", "rule": "unprotected-upgrade", "function": "c"},
            ],
        )
        self.assertEqual(bd["invariants_failed"], 3)
        self.assertEqual(bd["static_evidence"], 6)
        self.assertLessEqual(heat, 12)


class Fetch(unittest.TestCase):
    def test_sourcify_and_etherscan_shapes(self):
        sourcify = {"stdJsonInput": {"sources": {"A.sol": {"content": "pragma solidity ^0.8.0;\ncontract A {}"}}}}
        etherscan = {"result": [{"SourceCode": "contract B { function f() external {} }"}]}
        self.assertIn("contract A", solidity_from_payload(sourcify))
        self.assertIn("contract B", solidity_from_payload(etherscan))

    def test_cache_skips_the_network(self):
        calls = {"n": 0}

        def fetch(_url: str):
            calls["n"] += 1
            return {"stdJsonInput": {"sources": {"A.sol": {"content": "contract A { function f() external {} }"}}}}

        with tempfile.TemporaryDirectory() as tmp:
            first = fetch_verified_source(ADDR, cache_dir=Path(tmp), fetch_json=fetch, etherscan_get=None)
            second = fetch_verified_source(ADDR, cache_dir=Path(tmp), fetch_json=fetch, etherscan_get=None)
        self.assertEqual(calls["n"], 1)
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(second["via"], "sourcify")
        self.assertNotIn("apikey", json.dumps(second))

    def test_failed_fetch_is_empty(self):
        def boom(_url: str):
            raise TimeoutError("slow")

        def boom_eth(_addr: str):
            raise RuntimeError("down")

        row = fetch_verified_source(ADDR, fetch_json=boom, etherscan_get=boom_eth)
        self.assertEqual(row["source"], "")
        self.assertFalse(row["verified"])
        self.assertEqual(row["heat_contribution"], 0)


class Command(unittest.TestCase):
    def test_local_semgrep_stays_offline(self):
        argv = local_semgrep_argv("semgrep", "/proj", "/rules/solidity.yml")
        self.assertNotIn("p/solidity", argv)
        self.assertNotIn("http", " ".join(argv))
        self.assertIn("/rules/solidity.yml", argv)

    def test_command_stores_and_scores_without_binaries(self):
        def engines(_source: str, _timeout: int):
            return [EngineRunResult(
                "slither",
                "ok",
                findings=[{
                    "engine": "slither",
                    "rule": "arbitrary-send-erc20",
                    "evidence": "transfer of caller token 0x" + "cd" * 16,
                }],
            )]

        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp))
            report = run_static_command(
                address=ADDR,
                source="contract T { function poke() external {} }",
                store=store,
                engines_fn=engines,
                etherscan_get=lambda _a: (_ for _ in ()).throw(AssertionError("no fetch")),
            )
            reloaded = MemoryStore(Path(tmp))
        self.assertEqual(report["static_evidence"], 3)
        self.assertEqual(report["heat"], 3)
        self.assertEqual(report["source_via"], "local")
        self.assertEqual(report["store"]["saved"], 1)
        self.assertNotIn("cdcd", report["findings"][0]["evidence"])
        self.assertEqual(len(reloaded.static_findings), 1)
        self.assertTrue(reloaded.static_findings[0]["defensive_only"])

    def test_remote_store_degrades_when_the_table_is_missing(self):
        remote = SupabaseStore("https://example.supabase.co", "service-role-test")
        captured = {}

        def fake_req(method, table, body=None, query=None, prefer="return=representation"):
            captured["table"] = table
            captured["key_in_body"] = "service-role-test" in json.dumps(body or {})
            raise RuntimeError("supabase POST eth_scan_static_findings failed: HTTP 404 PGRST205")

        remote._req = fake_req  # type: ignore[method-assign]
        result = remote.save_static_findings(ADDR, [{
            "finding_key": "slither:suicidal:close",
            "engine": "slither",
            "rule": "suicidal",
            "evidence": "public selfdestruct",
            "weight": 3,
            "counted": True,
        }])
        self.assertTrue(result["degraded"])
        self.assertFalse(result["persisted"])
        self.assertEqual(captured["table"], "eth_scan_static_findings")
        self.assertFalse(captured["key_in_body"])

    def test_skipped_engine_adds_no_heat(self):
        def engines(_source: str, _timeout: int):
            return [EngineRunResult("slither", "skipped", note="slither not on PATH")]

        report = run_static_command(
            address=ADDR,
            source="contract T {}",
            engines_fn=engines,
        )
        self.assertEqual(report["static_evidence"], 0)
        self.assertEqual(report["heat"], 0)
        self.assertEqual(report["engines"][0]["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
