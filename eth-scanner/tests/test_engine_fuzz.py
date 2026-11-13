"""Defensive lead-gated fuzz stage — Medusa/Foundry, anvil fork, no attacks."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.engines.fuzz_harness import properties_for_class, write_live_fuzz_project
from eth_scanner.engines.fuzz_runner import (
    FuzzFailure,
    FuzzReport,
    fuzz_failures_as_confirmed,
    fuzz_failures_as_invariants,
    run_lead_fuzz,
)
from eth_scanner.engines.pipeline import run_advanced_engines
from eth_scanner.heat import evidence_heat
from eth_scanner.known_safe import is_known_safe


# Curated cold tokens (LINK, SAND, HEX, WETH, USDT, USDC, DAI).
_COLD = (
    "0x514910771af9ca656af840dff83e8264ecf986ca",  # LINK
    "0x3845badAde8e6dFF049820680d1F14bD3903a5d0",  # SAND
    "0x2b591e99afE9f32eAA6214f7B7629768c40Eeb39",  # HEX
    "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",  # WETH
    "0xdAC17F958D2ee523a2206206994597C13D831ec7",  # USDT
    "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",  # USDC
    "0x6B175474E89094C44Da98b954EedeAC495271d0F",  # DAI
)


class HarnessGeneration(unittest.TestCase):
    def test_vault_properties_cover_required_set(self):
        props = properties_for_class("vault")
        self.assertIn("solvency_assets_cover_shares", props)
        self.assertIn("share_price_round_trip", props)
        self.assertIn("access_control_non_owner", props)
        self.assertIn("no_third_party_balance_drop", props)

    def test_materialize_is_defensive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, props = write_live_fuzz_project(
                Path(tmp) / "fuzz",
                address="0x" + "11" * 20,
                contract_class="vault",
                contract_name="DemoVault",
            )
            self.assertTrue((root / "foundry.toml").is_file())
            self.assertTrue((root / "medusa.json").is_file())
            sol = (root / "test" / "LiveProperties.t.sol").read_text(encoding="utf-8")
            low = sol.lower()
            self.assertNotIn("function attack", low)
            self.assertNotIn("vm.prank", low)
            self.assertNotIn("broadcast", low)
            self.assertIn("proof of bug", low)
            self.assertIn('address(bytes20(hex"', sol)
            self.assertNotIn("function invariant_", sol)
            toml = (root / "foundry.toml").read_text(encoding="utf-8")
            self.assertIn("isolate = false", toml)
            self.assertGreaterEqual(len(props), 2)

    def test_forge_cli_omits_removed_invariant_runs_flag(self):
        import ast
        import inspect
        from eth_scanner.engines import fuzz_runner as fr

        src = inspect.getsource(fr._run_forge)
        self.assertIn("--fuzz-runs", src)
        self.assertIn("--fork-url", src)
        # Ensure the argv literal list never passes the removed Foundry 1.9 flag.
        tree = ast.parse(src)
        argv_lists = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.List)
        ]
        rendered = [" ".join(
            (elt.value if isinstance(elt, ast.Constant) and isinstance(elt.value, str) else "")
            for elt in lst.elts
        ) for lst in argv_lists]
        self.assertTrue(any("--fuzz-runs" in r for r in rendered))
        self.assertFalse(any("--invariant-runs" in r for r in rendered))


class FuzzEvidenceHeat(unittest.TestCase):
    def test_medusa_compile_failure_is_not_a_property_failure(self):
        from eth_scanner.engines.fuzz_runner import FuzzReport, _ingest_medusa_output

        report = FuzzReport(
            ran=True,
            property_ids=["solvency_assets_cover_shares"],
            properties_checked=1,
        )
        _ingest_medusa_output("Failed to compile target\x1b[31m", report)
        self.assertEqual(report.failure_count, 0)
        self.assertTrue(any("compile" in n.lower() for n in report.notes))

    def test_property_failure_feeds_failed_invariant_heat(self):
        report = FuzzReport(
            ran=True,
            skipped=False,
            tool="forge",
            status="failed",
            properties_checked=4,
            property_ids=["solvency_assets_cover_shares"],
            failures=[FuzzFailure(
                property_id="solvency_assets_cover_shares",
                tool="forge",
                reproduction="call sequence: convertToAssets(totalSupply)",
                evidence="property failed: test_solvency_assets_cover_shares",
            )],
            fork_block=123,
        )
        inv = fuzz_failures_as_invariants(report)
        conf = fuzz_failures_as_confirmed(report)
        self.assertEqual(len(inv), 1)
        self.assertEqual(inv[0]["status"], "failed")
        self.assertTrue(conf[0]["confirmed"])
        self.assertEqual(conf[0]["method"], "fuzz")
        heat, bd = evidence_heat(
            funds_usd=50_000,
            invariant_results=inv,
            corroborated=conf,
        )
        self.assertGreater(heat, 0)
        self.assertGreater(bd["invariants_failed"], 0)

    def test_no_failure_keeps_heat_zero_from_fuzz(self):
        report = FuzzReport(ran=True, skipped=False, tool="forge", status="ok", properties_checked=4)
        heat, _ = evidence_heat(
            funds_usd=50_000,
            invariant_results=fuzz_failures_as_invariants(report),
            corroborated=fuzz_failures_as_confirmed(report),
        )
        self.assertEqual(heat, 0)


class PipelineFuzzGating(unittest.TestCase):
    def test_fuzz_skipped_without_slither_or_invariant_lead(self):
        from eth_scanner.deep.runners import EngineRunResult

        fake_sl = EngineRunResult("slither", "ok", findings=[], note="ok", duration_ms=5)
        with mock.patch("eth_scanner.engines.pipeline.run_slither", return_value=fake_sl), \
             mock.patch("eth_scanner.engines.pipeline.run_mythril", return_value=EngineRunResult("mythril", "skipped")), \
             mock.patch("eth_scanner.engines.pipeline.run_lead_fuzz") as fuzz:
            report = run_advanced_engines(
                address="0x" + "ab" * 20,
                source="pragma solidity ^0.8.0; contract V { function deposit() external payable {} }",
                bytecode_hash="fuzz-skip-no-lead-hash",
                contract_class="vault",
                funds_usd=25_000,
                verified=True,
                rpc_url="https://example.invalid",
                invariant_results=[{"id": "x", "status": "held"}],
            )
        fuzz.assert_not_called()
        self.assertTrue(report.fuzz.get("skipped") or report.fuzz.get("status") == "skipped")

    def test_fuzz_runs_on_slither_lead(self):
        from eth_scanner.deep.findings import EngineFinding
        from eth_scanner.deep.runners import EngineRunResult

        finding = EngineFinding(
            id="slither-1",
            engine="slither",
            rule="reentrancy-eth",
            title="reentrancy",
            severity="high",
            confidence="high",
            evidence="x",
            generic=False,
            funds_class="reentrancy",
        )
        fake_sl = EngineRunResult("slither", "ok", findings=[finding], note="ok", duration_ms=5)
        fake_fuzz = FuzzReport(
            ran=True, skipped=False, tool="forge", status="ok",
            properties_checked=4, property_ids=["solvency_assets_cover_shares"],
            duration_ms=12,
            artifact={"kind": "fuzz", "failures": []},
        )
        with mock.patch("eth_scanner.engines.pipeline.run_slither", return_value=fake_sl), \
             mock.patch("eth_scanner.engines.pipeline.run_mythril", return_value=EngineRunResult("mythril", "skipped")), \
             mock.patch("eth_scanner.engines.pipeline.corroborate_lead") as corr, \
             mock.patch("eth_scanner.engines.pipeline.run_lead_fuzz", return_value=fake_fuzz) as fuzz:
            corr.return_value = mock.Mock(to_dict=lambda: {
                "lead_id": "slither-1", "confirmed": False, "method": "eth_call", "evidence": "reverted",
            })
            report = run_advanced_engines(
                address="0x" + "cd" * 20,
                source="pragma solidity ^0.8.0; contract V { function deposit() external payable {} }",
                bytecode_hash="cafebabe",
                contract_class="vault",
                funds_usd=25_000,
                verified=True,
                rpc_url="https://example.invalid",
            )
        fuzz.assert_called_once()
        self.assertTrue(report.timing.get("ran_fuzz"))
        self.assertEqual(report.timing.get("fuzz_properties"), 4)

    def test_run_lead_fuzz_skips_without_rpc(self):
        report = run_lead_fuzz(
            address="0x" + "11" * 20,
            contract_class="vault",
            rpc_url="",
            timeout_s=5,
        )
        self.assertTrue(report.skipped)
        self.assertEqual(report.status, "skipped")

    def test_fork_rpc_death_detection(self):
        from eth_scanner.engines.fuzz_runner import _looks_like_fork_rpc_death

        self.assertTrue(_looks_like_fork_rpc_death([
            "forge test exit=1 — ieve chain ID from fork endpoint tcp connect",
        ]))
        self.assertFalse(_looks_like_fork_rpc_death([
            "forge test exit=0 passed=4 failed=0",
        ]))


class KnownSafeStayCold(unittest.TestCase):
    def test_curated_tokens_known_safe(self):
        for addr in _COLD:
            ok, _reasons = is_known_safe(address=addr)
            self.assertTrue(ok, msg=addr)

    def test_known_safe_slither_lead_does_not_heat_without_confirm(self):
        # Even with a synthetic corroborated=False lead list, heat stays 0.
        heat, _ = evidence_heat(
            funds_usd=1_000_000,
            invariant_results=[],
            corroborated=[{"lead_id": "L2-slither-x", "confirmed": False, "method": "none"}],
        )
        self.assertEqual(heat, 0)


if __name__ == "__main__":
    unittest.main()
