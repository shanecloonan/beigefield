"""External AGPL suites stay outside the package."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eth_scanner.logic.external_suites import (
    PINS,
    harness_source,
    looks_like_erc4626,
    parse_property_failures,
    prepare_external_suites,
)


class ExternalSuiteTests(unittest.TestCase):
    def test_pins_are_agpl_and_not_linked(self):
        self.assertEqual(PINS["erc4626-tests"]["license"], "AGPL-3.0")
        self.assertEqual(PINS["crytic-properties"]["license"], "AGPL-3.0")
        self.assertEqual(PINS["erc4626-tests"]["commit"], "ac485460e014f22807c1ff687e0b4dc3af96ee40")
        source = Path(__file__).resolve().parents[1] / "src" / "eth_scanner" / "logic" / "external_suites.py"
        text = source.read_text(encoding="utf-8")
        self.assertNotIn("function prop_RT_", text)
        self.assertNotIn("CryticERC4626FunctionalAccounting", text)

    def test_missing_checkout_skips(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = prepare_external_suites(
                vault="0x1111111111111111111111111111111111111111",
                asset="0x2222222222222222222222222222222222222222",
                dest=Path(tmp) / "out",
                roots={"erc4626-tests": None, "crytic-properties": None},
            )
        self.assertEqual(report["status"], "skipped")
        self.assertEqual(report["heat"], 0)
        self.assertFalse(report["erc4626"])

    def test_non_vault_is_not_run(self):
        self.assertFalse(looks_like_erc4626("lending", "function borrow()"))
        self.assertTrue(looks_like_erc4626("erc4626-vault", ""))
        report = prepare_external_suites(
            vault="0x1111111111111111111111111111111111111111",
            asset="0x2222222222222222222222222222222222222222",
            dest=Path("unused"),
            contract_class="lending",
            roots={"erc4626-tests": None, "crytic-properties": None},
        )
        self.assertEqual(report["status"], "skipped")
        self.assertIn("Not an ERC-4626", report["note"])

    def test_harness_is_thin_and_configs_point_outside(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            erc = root / "a16z"
            (erc).mkdir()
            (erc / "ERC4626.test.sol").write_text("// external marker\n", encoding="utf-8")
            crytic = root / "crytic" / "contracts" / "ERC4626" / "properties"
            crytic.mkdir(parents=True)
            (crytic.parent / "ERC4626PropertyTests.sol").write_text("// external marker\n", encoding="utf-8")
            (crytic / "RoundingProps.sol").write_text("// external marker\n", encoding="utf-8")
            dest = root / "work"
            report = prepare_external_suites(
                vault="0x1111111111111111111111111111111111111111",
                asset="0x2222222222222222222222222222222222222222",
                dest=dest,
                roots={"erc4626-tests": erc, "crytic-properties": crytic.parents[2]},
            )
            harness = Path(report["harness"]).read_text(encoding="utf-8")
            self.assertIn("SPDX-License-Identifier: MIT", harness)
            self.assertIn('import "erc4626-tests/ERC4626.test.sol";', harness)
            self.assertNotIn("function prop_", harness)
            self.assertNotIn("AGPL", harness)
            foundry = (dest / "erc4626" / "foundry.toml").read_text(encoding="utf-8")
            self.assertIn("ffi = false", foundry)
            self.assertIn(erc.resolve().as_posix(), foundry)
            medusa = json.loads((dest / "crytic" / "medusa.json").read_text(encoding="utf-8"))
            self.assertEqual(
                medusa["compilation"]["platformConfig"]["target"],
                str((crytic.parents[2]).resolve()),
            )
            self.assertEqual(medusa["fuzzing"]["workers"], 1)
            self.assertEqual(medusa["fuzzing"]["timeout"], 20)
            self.assertTrue(medusa["fuzzing"]["testing"]["assertionTesting"]["enabled"])
            self.assertIn("verify_", medusa["fuzzing"]["testing"]["propertyTesting"]["testPrefixes"])
            echidna = (dest / "crytic" / "echidna.yaml").read_text(encoding="utf-8")
            self.assertIn("testMode: assertion", echidna)
            self.assertIn("RoundingProps", (dest / "crytic" / "properties.txt").read_text(encoding="utf-8"))
            self.assertEqual(report["heat"], 0)
            self.assertTrue(report["heat_breakdown"]["erc4626_suite"])
            self.assertTrue(report["heat_breakdown"]["crytic_properties"])

    def test_public_rpc_is_refused_before_any_run(self):
        called = []

        def runner(argv, cwd, timeout):
            called.append(argv)
            return 0, ""

        report = prepare_external_suites(
            vault="0x1111111111111111111111111111111111111111",
            asset="0x2222222222222222222222222222222222222222",
            dest=Path("unused"),
            fork_url="https://eth-mainnet.example/v2/secret",
            run=True,
            runner=runner,
            roots={"erc4626-tests": None, "crytic-properties": None},
        )
        self.assertEqual(report["status"], "refused")
        self.assertEqual(called, [])
        self.assertNotIn("secret", json.dumps(report))

    def test_local_property_failure_adds_invariant_heat_without_calldata(self):
        with tempfile.TemporaryDirectory() as tmp:
            erc = Path(tmp) / "a16z"
            erc.mkdir()
            (erc / "ERC4626.test.sol").write_text("// external marker\n", encoding="utf-8")

            def runner(argv, cwd, timeout):
                self.assertIn("--fork-url", argv)
                self.assertIn("127.0.0.1", " ".join(argv))
                return 1, (
                    "[FAIL: 0xdeadbeefcafebabe] prop_RT_deposit_redeem(address,uint256)\n"
                    "[FAIL] test_setup()\n"
                )

            report = prepare_external_suites(
                vault="0x1111111111111111111111111111111111111111",
                asset="0x2222222222222222222222222222222222222222",
                dest=Path(tmp) / "work",
                fork_url="http://127.0.0.1:8545",
                run=True,
                runner=runner,
                roots={"erc4626-tests": erc, "crytic-properties": None},
            )
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["results"][0]["id"], "prop_RT_deposit_redeem")
        self.assertEqual(report["results"][0]["source"], "fork-simulation")
        self.assertNotIn("0x", report["results"][0]["evidence"])
        self.assertGreater(report["heat"], 0)
        self.assertEqual(len(report["results"]), 1)

    def test_parser_drops_hex(self):
        rows = parse_property_failures(
            "[FAIL] property_rounding() calldata 0x1234567890abcdef",
            source="fuzz",
        )
        self.assertEqual(rows[0]["source"], "fuzz")
        self.assertNotIn("0x", json.dumps(rows))

    def test_harness_rejects_a_short_address(self):
        with self.assertRaises(ValueError):
            harness_source("0x1234", "0x2222222222222222222222222222222222222222")


if __name__ == "__main__":
    unittest.main()
