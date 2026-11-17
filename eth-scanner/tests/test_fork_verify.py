"""Post-heat fork-verify stage: gating, result merge, planted true-positive."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.drain import score_drain
from eth_scanner.engines.fork_verify import (
    ATTACKER_ADDRESS,
    DEFAULT_EXPLOIT_POC_HEAT,
    DEFAULT_MIN_HEAT,
    ForkVerifyFailure,
    ForkVerifyReport,
    PLANT_ADDRESS,
    apply_fork_verify,
    apply_fork_verify_to_row,
    fork_verify_enabled,
    fuzz_min_heat,
    list_high_heat_rows,
    run_fork_verify,
    selector4,
    selectors_from_source,
    should_run_fork_verify,
    write_fork_verify_project,
)
from eth_scanner.research.keccak import selector4 as keccak_selector4
from eth_scanner.types import FunnelResult


def _result(**kwargs) -> FunnelResult:
    base = dict(
        bucket="lane-a-cool",
        dropped=False,
        drop_reason=None,
        heat=8,
        src_confidence="high",
        ir_confidence="high",
        funds_usd=235_000,
        contract_class="vault",
        heat_breakdown={"total": 8, "funds_in_heat": 0},
    )
    base.update(kwargs)
    return FunnelResult(**base)


class GateAndConfig(unittest.TestCase):
    def test_default_min_heat_is_eight(self):
        self.assertEqual(DEFAULT_MIN_HEAT, 8)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ETH_SCANNER_FUZZ_MIN_HEAT", None)
            self.assertEqual(fuzz_min_heat(), 8)

    def test_env_min_heat_override(self):
        with mock.patch.dict(os.environ, {"ETH_SCANNER_FUZZ_MIN_HEAT": "10"}):
            self.assertEqual(fuzz_min_heat(), 10)

    def test_disabled_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ETH_SCANNER_FORK_VERIFY", None)
            self.assertFalse(fork_verify_enabled())
            ok, reason = should_run_fork_verify(heat=12, rpc_url="http://127.0.0.1:8545")
            self.assertFalse(ok)
            self.assertIn("disabled", reason)

    def test_enabled_but_heat_too_low(self):
        ok, reason = should_run_fork_verify(
            heat=7, rpc_url="http://example", enabled=True, min_heat=8,
        )
        self.assertFalse(ok)
        self.assertIn("below", reason)

    def test_enabled_but_no_rpc(self):
        ok, reason = should_run_fork_verify(heat=12, rpc_url="", enabled=True)
        self.assertFalse(ok)
        self.assertIn("ETH_RPC_URL", reason)

    def test_enabled_high_heat_with_rpc(self):
        ok, reason = should_run_fork_verify(
            heat=8, rpc_url="https://example.invalid", enabled=True,
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")

    def test_fixture_bypasses_gates(self):
        ok, reason = should_run_fork_verify(heat=0, rpc_url="", fixture="leaky", enabled=False)
        self.assertTrue(ok)
        self.assertEqual(reason, "fixture")
        ok, reason = should_run_fork_verify(fixture="nope")
        self.assertFalse(ok)


class SelectorsAndHarness(unittest.TestCase):
    def test_poke_selector(self):
        self.assertEqual(keccak_selector4("poke()"), "0x18178358")
        self.assertIn("0x18178358", selectors_from_source("function poke() external {}"))

    def test_parses_source_functions(self):
        src = "function withdraw(uint256 amount) external {}\nfunction harvest() public {}"
        sels = selectors_from_source(src)
        self.assertIn(selector4("withdraw(uint256)"), sels)
        self.assertIn(selector4("harvest()"), sels)

    def test_harness_is_conservation_not_an_attack_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, props = write_fork_verify_project(
                Path(tmp) / "fv",
                address=PLANT_ADDRESS,
                source="function poke() external {}",
            )
            sol = (root / "test" / "ForkVerifyProperties.t.sol").read_text(encoding="utf-8")
            low = sol.lower()
            self.assertNotIn("function attack", low)
            self.assertNotIn("vm.broadcast", low)
            self.assertNotIn("startbroadcast", low)
            self.assertIn("never broadcast", low)
            self.assertIn("profit-attacker-balance", sol)
            self.assertIn("testFuzz_unprivileged_sequence_cannot_extract", sol)
            self.assertIn("vm.prank", sol)
            self.assertIn("never broadcast", low)
            self.assertIn('address(bytes20(hex"', sol)
            self.assertTrue((root / "foundry.toml").is_file())
            self.assertIn("unprivileged_known_selectors_cannot_extract", props)


class ApplyAndHeat(unittest.TestCase):
    def test_skip_without_rpc_on_live_target(self):
        report = run_fork_verify(address="0x" + "11" * 20, rpc_url="", heat=12, force=True)
        self.assertTrue(report.skipped)
        self.assertFalse(report.drainable)
        self.assertIn("ETH_RPC_URL", report.skip_reason or "".join(report.notes))

    def test_drainable_bumps_heat_and_promotes_bucket(self):
        result = _result(heat=8, bucket="lane-b-queue")
        report = ForkVerifyReport(
            ran=True,
            skipped=False,
            status="broken",
            drainable=True,
            tool="forge",
            heat_in=8,
            sequence="ForkVerifyProperties.handler_selector(0) poke()",
            failures=[ForkVerifyFailure(
                property_id="unprivileged_known_selectors_cannot_extract",
                tool="forge",
                reproduction="handler_selector(0)",
                evidence="property failed: test_unprivileged_known_selectors_cannot_extract",
            )],
        )
        apply_fork_verify(result, report)
        self.assertEqual(result.bucket, "manual-review")
        self.assertEqual(result.heat, min(12, 8 + DEFAULT_EXPLOIT_POC_HEAT))
        hb = result.heat_breakdown
        self.assertTrue(hb["drainable"])
        self.assertTrue(hb["exploit_poc"]["drainable"])
        self.assertEqual(hb["exploit_poc"]["bucket_hint"], "proven-drainable")
        self.assertIn("handler_selector", hb["exploit_poc"]["sequence"])
        self.assertTrue(hb["profit_invariant_broke"])
        self.assertGreaterEqual(hb["drain_probability"], 88)
        row = result.invariant_results[-1]
        self.assertEqual(row["id"], "profit-attacker-balance")
        self.assertEqual(row["source"], "fork-verify")
        self.assertEqual(row["status"], "failed")
        drain = score_drain(funds_usd=result.funds_usd, invariant_results=result.invariant_results)
        self.assertTrue(drain["profit_invariant_broke"])
        self.assertEqual(drain["band"], "profit")

    def test_held_does_not_promote_or_bump(self):
        result = _result(heat=10, bucket="lane-b-queue")
        report = ForkVerifyReport(ran=True, skipped=False, status="ok", drainable=False, tool="forge")
        apply_fork_verify(result, report)
        self.assertEqual(result.bucket, "lane-b-queue")
        self.assertEqual(result.heat, 10)
        self.assertFalse(result.heat_breakdown["drainable"])

    def test_apply_to_row_and_list_helper(self):
        row = {
            "address": "0xabc",
            "heat": 10,
            "bucket": "lane-a-cool",
            "heat_breakdown": {"total": 10},
            "funds_usd": 24000,
        }
        report = ForkVerifyReport(ran=True, skipped=False, status="broken", drainable=True, tool="forge", sequence="poke()")
        patched = apply_fork_verify_to_row(row, report)
        self.assertEqual(patched["bucket"], "manual-review")
        self.assertGreater(patched["heat"], 10)
        self.assertTrue(patched["heat_breakdown"]["drainable"])

        class _Store:
            def list_results(self, limit=200):
                return [
                    {"address": "0x1", "heat": 12, "created_at": "2"},
                    {"address": "0x1", "heat": 12, "created_at": "1"},
                    {"address": "0x2", "heat": 3, "created_at": "3"},
                    {"address": "0x3", "heat": 10, "created_at": "4"},
                ]

        rows = list_high_heat_rows(_Store(), min_heat=8, limit=2)
        self.assertEqual([r["address"] for r in rows], ["0x1", "0x3"])


@unittest.skipUnless(
    __import__("shutil").which("forge") and __import__("shutil").which("anvil"),
    "forge + anvil required for planted true-positive",
)
class PlantedTruePositive(unittest.TestCase):
    def test_leaky_fixture_is_drainable(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = run_fork_verify(
                fixture="leaky",
                work_dir=Path(tmp),
                timeout_s=90,
            )
        self.assertFalse(report.skipped, report.notes)
        self.assertTrue(report.drainable, report.to_dict())
        self.assertEqual(report.status, "broken")
        self.assertEqual(report.tool, "forge")
        self.assertEqual(report.address.lower(), PLANT_ADDRESS)
        blob = (report.sequence + " " + " ".join(f.evidence for f in report.failures)).lower()
        self.assertTrue(
            "unprivileged_known_selectors" in blob
            or "attacker_cannot_extract" in blob
            or "profit-attacker-balance" in blob
            or report.failures,
            report.to_dict(),
        )

    def test_safe_fixture_is_not_drainable(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = run_fork_verify(
                fixture="safe",
                work_dir=Path(tmp),
                timeout_s=90,
            )
        self.assertFalse(report.skipped, report.notes)
        self.assertFalse(report.drainable, report.to_dict())
        self.assertEqual(report.status, "ok")


if __name__ == "__main__":
    unittest.main()
