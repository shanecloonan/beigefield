"""Phase-G defensive stages: halmos/oracle/admin/storage/clones — known-safe cold."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.engines.admin_checks import AdminFinding, AdminReport, admin_as_confirmed
from eth_scanner.engines.clones import extract_selectors, match_known_bad, skeleton_hash
from eth_scanner.engines.fuzz_harness import write_live_fuzz_project
from eth_scanner.engines.halmos_runner import (
    HalmosReport,
    SymbolicFailure,
    symbolic_failures_as_confirmed,
    symbolic_failures_as_invariants,
)
from eth_scanner.engines.oracle_checks import OracleFinding, OracleReport, oracle_as_confirmed, run_oracle_checks
from eth_scanner.engines.pipeline import run_advanced_engines
from eth_scanner.engines.storage_diff import StorageFinding, StorageReport, storage_as_confirmed
from eth_scanner.heat import evidence_heat
from eth_scanner.known_safe import is_known_safe

_COLD = (
    "0x514910771af9ca656af840dff83e8264ecf986ca",  # LINK
    "0x3845badAde8e6dFF049820680d1F14bD3903a5d0",  # SAND
    "0x2b591e99afE9f32eAA6214f7B7629768c40Eeb39",  # HEX
    "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",  # WETH
    "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",  # USDC
    "0x6B175474E89094C44Da98b954EedeAC495271d0F",  # DAI
)


class KnownSafeStayCold(unittest.TestCase):
    def test_curated_tokens_known_safe(self):
        for addr in _COLD:
            ok, _ = is_known_safe(address=addr)
            self.assertTrue(ok, msg=addr)

    def test_oracle_leads_alone_add_zero_heat(self):
        heat, bd = evidence_heat(
            funds_usd=1_000_000,
            invariant_results=[],
            corroborated=[{
                "lead_id": "oracle-chainlink-usage",
                "confirmed": False,
                "method": "source",
                "evidence": "lead only",
            }],
        )
        self.assertEqual(heat, 0)
        self.assertEqual(bd["corroborated_leads"], 0)

    def test_clone_dataset_lead_alone_zero_heat(self):
        heat, _ = evidence_heat(
            funds_usd=500_000,
            invariant_results=[],
            corroborated=[{
                "lead_id": "clone-dataset-defihacklabs-erc4626-inflation",
                "confirmed": False,
                "method": "none",
                "evidence": "score=0.7",
            }],
        )
        self.assertEqual(heat, 0)


class HalmosSymbolic(unittest.TestCase):
    def test_harness_emits_check_entrypoints(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root, props = write_live_fuzz_project(
                Path(tmp) / "h",
                address="0x" + "11" * 20,
                contract_class="vault",
                runtime_bytecode="0x6080604052" + ("ab" * 40),
                compiler="v0.8.19+commit.7dd6d404",
            )
            sol = (root / "test" / "LiveProperties.t.sol").read_text(encoding="utf-8")
            self.assertIn("function check_solvency_assets_cover_shares", sol)
            self.assertIn("function check_access_control_non_owner", sol)
            self.assertIn("vm.etch", sol)
            self.assertNotIn("new MockBound", sol)
            toml = (root / "foundry.toml").read_text(encoding="utf-8")
            self.assertIn('solc = "0.8.19"', toml)
            self.assertTrue((root / "lib" / "forge-std" / "src" / "Vm.sol").is_file())
            self.assertGreaterEqual(len(props), 2)
            # Halmos fallback: mock etch hex without deployCode/`new`.
            root2, _ = write_live_fuzz_project(
                Path(tmp) / "h2",
                address="0x" + "22" * 20,
                contract_class="vault",
                allow_mock_etch=True,
            )
            sol2 = (root2 / "test" / "LiveProperties.t.sol").read_text(encoding="utf-8")
            self.assertIn("vm.etch", sol2)
            self.assertNotIn("new MockBound", sol2)

    def test_solc_detect_from_pragma_and_compiler(self):
        from eth_scanner.engines.fuzz_harness import detect_solc_version
        self.assertEqual(detect_solc_version(compiler="v0.8.17+commit.8df45f5f"), "0.8.17")
        self.assertEqual(
            detect_solc_version(source="pragma solidity ^0.8.12;"),
            "0.8.12",
        )

    def test_error_paths_are_property_skips_not_compile_skip(self):
        from eth_scanner.engines.halmos_runner import _ingest
        report = HalmosReport(
            ran=True, skipped=False, status="ok",
            properties_checked=3,
            property_ids=["access_control_non_owner", "no_third_party_balance_drop"],
        )
        blob = (
            "[PASS] check_access_control_non_owner ()\n"
            "[ERROR] check_no_third_party_balance_drop (paths: all reverted)\n"
            "Symbolic test result: 1 passed, 0 failed, 1 error\n"
        )
        _ingest(blob, report)
        self.assertTrue(report.executed)
        self.assertEqual(report.properties_executed, 2)
        self.assertEqual(report.properties_skipped, 1)
        self.assertEqual(report.failure_count, 0)
        from eth_scanner.engines.halmos_runner import _looks_like_true_compile_failure
        self.assertFalse(_looks_like_true_compile_failure(blob))

    def test_true_compile_failure_marker(self):
        from eth_scanner.engines.halmos_runner import _looks_like_true_compile_failure
        self.assertTrue(_looks_like_true_compile_failure("Error: Compiler run failed\nbuild failed"))
        self.assertFalse(_looks_like_true_compile_failure("[PASS] check_foo\n[ERROR] check_bar"))

    def test_counterexample_feeds_failed_invariant_heat(self):
        report = HalmosReport(
            ran=True, skipped=False, status="failed",
            properties_checked=4,
            property_ids=["solvency_assets_cover_shares"],
            failures=[SymbolicFailure(
                property_id="solvency_assets_cover_shares",
                reproduction="[FAIL] check_solvency_assets_cover_shares Counterexample: 0x1",
                evidence="halmos counterexample",
            )],
        )
        inv = symbolic_failures_as_invariants(report)
        conf = symbolic_failures_as_confirmed(report)
        self.assertEqual(inv[0]["status"], "failed")
        self.assertTrue(conf[0]["confirmed"])
        self.assertEqual(conf[0]["method"], "symbolic")
        heat, bd = evidence_heat(
            funds_usd=50_000,
            invariant_results=inv,
            corroborated=conf,
        )
        self.assertGreater(heat, 0)
        self.assertGreater(bd["invariants_failed"], 0)

    def test_halmos_missing_is_skip(self):
        from eth_scanner.engines.halmos_runner import run_lead_halmos
        with mock.patch("eth_scanner.engines.halmos_runner.halmos_bin", return_value=None):
            report = run_lead_halmos(
                address="0x" + "22" * 20,
                contract_class="vault",
                rpc_url="https://example.invalid",
                timeout_s=60,
            )
        self.assertTrue(report.skipped)
        self.assertEqual(report.status, "skipped")


class OracleChecks(unittest.TestCase):
    def test_detects_chainlink_as_lead_without_rpc(self):
        src = """
        interface AggregatorV3Interface { function latestRoundData() external view returns (uint80,int256,uint256,uint256,uint80); }
        contract V { AggregatorV3Interface public priceFeed = AggregatorV3Interface(0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419); }
        """
        report = run_oracle_checks(address="0x" + "33" * 20, source=src, rpc_url="")
        self.assertTrue(any("chainlink" in f.id for f in report.leads))
        self.assertEqual(len(report.confirmed), 0)

    def test_confirmed_oracle_adds_heat(self):
        conf = oracle_as_confirmed(OracleReport(confirmed=[OracleFinding(
            id="oracle-live-stale",
            kind="confirmed",
            title="stale",
            evidence="feed=0xabc age_s=999999",
            confirmed=True,
            method="eth_call",
        )]))
        heat, _ = evidence_heat(funds_usd=80_000, invariant_results=[], corroborated=conf)
        self.assertGreater(heat, 0)


class AdminChecks(unittest.TestCase):
    def test_eoa_admin_confirmed_feeds_heat_at_100k(self):
        report = AdminReport(
            ran=True, eoa_admin=True,
            confirmed=[AdminFinding(
                id="admin-eoa-confirmed",
                title="EOA admin",
                evidence="controller=0xbeef funds_usd=150000",
                confirmed=True,
            )],
        )
        conf = admin_as_confirmed(report)
        heat, bd = evidence_heat(
            funds_usd=150_000,
            invariant_results=[],
            eoa_admin=True,
            corroborated=conf,
        )
        self.assertGreater(heat, 0)
        self.assertGreater(bd["eoa_admin"], 0)

    def test_privileged_callable_feeds_heat(self):
        heat, bd = evidence_heat(
            funds_usd=25_000,
            invariant_results=[],
            privileged_callable=True,
        )
        self.assertGreater(bd["privileged_callable"], 0)


class StorageDiff(unittest.TestCase):
    def test_collision_confirmed_heats(self):
        conf = storage_as_confirmed(StorageReport(confirmed=[StorageFinding(
            id="storage-collision-live",
            title="collision",
            evidence="impl in slot 0",
            confirmed=True,
        )]))
        heat, _ = evidence_heat(funds_usd=40_000, invariant_results=[], corroborated=conf)
        self.assertGreater(heat, 0)


class CloneDataset(unittest.TestCase):
    def test_selector_skeleton(self):
        src = """
        contract V {
            function deposit(uint256 assets, address receiver) external returns (uint256) {}
            function mint(uint256 shares, address receiver) external returns (uint256) {}
        }
        """
        sels = extract_selectors(src)
        self.assertTrue(sels)
        self.assertEqual(len(skeleton_hash(sels)), 64)

    def test_dataset_match_unprotected_init(self):
        src = """
        pragma solidity ^0.8.0;
        contract Bad {
            address public owner;
            function initialize(address admin) public { owner = admin; }
            function changeAdmin(address a) public { owner = a; }
            function upgradeTo(address i) public {}
        }
        """
        leads = match_known_bad(source=src, contract_name="Bad")
        self.assertTrue(leads)
        # Still a lead — heat only after corroboration.
        heat, _ = evidence_heat(
            funds_usd=200_000,
            invariant_results=[],
            corroborated=[{"lead_id": leads[0].id, "confirmed": False}],
        )
        self.assertEqual(heat, 0)


class PipelineIntegration(unittest.TestCase):
    def test_stages_run_without_blocking_on_tool_absence(self):
        from eth_scanner.deep.findings import EngineFinding
        from eth_scanner.deep.runners import EngineRunResult

        finding = EngineFinding(
            id="slither-1",
            engine="slither",
            rule="reentrancy-eth",
            title="Slither reentrancy-eth",
            severity="high",
            confidence="medium",
            funds_class="reentrancy",
            evidence="reentrancy lead",
            generic=False,
        )
        fake_sl = EngineRunResult("slither", "ok", findings=[finding], note="ok", duration_ms=1)
        with mock.patch("eth_scanner.engines.pipeline.run_slither", return_value=fake_sl), \
             mock.patch("eth_scanner.engines.pipeline.run_mythril", return_value=EngineRunResult("mythril", "skipped")), \
             mock.patch("eth_scanner.engines.pipeline.corroborate_lead") as corr, \
             mock.patch("eth_scanner.engines.pipeline.run_lead_fuzz") as fuzz, \
             mock.patch("eth_scanner.engines.pipeline.run_lead_halmos") as halmos, \
             mock.patch("eth_scanner.engines.pipeline.run_oracle_checks") as oracle, \
             mock.patch("eth_scanner.engines.pipeline.run_admin_checks") as admin, \
             mock.patch("eth_scanner.engines.pipeline.run_storage_diff") as storage:
            from eth_scanner.engines.corroborate import Corroboration
            corr.return_value = Corroboration("slither-1", False, "eth_call", "reverted")
            from eth_scanner.engines.oracle_checks import OracleReport
            from eth_scanner.engines.admin_checks import AdminReport
            from eth_scanner.engines.storage_diff import StorageReport
            oracle.return_value = OracleReport(ran=True, status="ok")
            admin.return_value = AdminReport(ran=True, status="ok")
            storage.return_value = StorageReport(ran=False, status="ok")
            fuzz.return_value = mock.Mock(
                to_dict=lambda: {"status": "skipped", "ran": False},
                notes=[], status="skipped", tool="none", properties_checked=0,
                failure_count=0, duration_ms=0, ran=False, failures=[], artifact={},
            )
            # Simulated prior false-positive: ran=True but executed=False (compile-skip).
            halmos.return_value = HalmosReport(
                ran=False, skipped=True, status="compile-skip", executed=False,
                properties_checked=16, properties_executed=0, properties_skipped=16,
            )
            report = run_advanced_engines(
                address="0x" + "ab" * 20,
                source="pragma solidity ^0.8.0; contract V { function deposit() external payable {} }",
                bytecode_hash="phaseg-pipeline-integration-hash",
                contract_class="vault",
                funds_usd=25_000,
                verified=True,
                rpc_url="https://example.invalid",
                run_fuzz=True,
                run_halmos=True,
                compiler="v0.8.20+commit.a1b79de6",
                runtime_bytecode="0x6080604052",
            )
        self.assertTrue(report.timing.get("ran_oracle") or report.timing.get("oracle_executed"))
        self.assertIn("oracle_ms", report.timing)
        self.assertIn("halmos_status", report.timing)
        self.assertFalse(report.timing.get("halmos_executed"))
        self.assertTrue(report.timing.get("halmos_skipped"))
        self.assertTrue(report.timing.get("slither_executed"))
        self.assertIn("fuzz_executed", report.timing)
        self.assertIn("clone_executed", report.timing)
        # solc / bytecode wiring reaches runners
        fuzz.assert_called()
        kwargs = fuzz.call_args.kwargs
        self.assertEqual(kwargs.get("compiler"), "v0.8.20+commit.a1b79de6")
        self.assertTrue(kwargs.get("runtime_bytecode"))


if __name__ == "__main__":
    unittest.main()
