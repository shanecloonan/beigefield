"""L4 template generation + L2 custom detectors. No forge required."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.research.detectors import (
    detect_hash_preimage_payout,
    detect_oracle_freshness,
    detect_pre08_arithmetic,
    detect_share_asset_shape,
    detect_unbounded_storage_loop,
    detect_unchecked_low_level,
    detect_weak_auth_value_moves,
    detect_weak_entropy,
)
from eth_scanner.research.fork_checks import TotalAssetsCheck, run_fork_checks
from eth_scanner.research.invariants import (
    generate_invariant_stubs,
    is_foundry_project,
    load_template,
    run_forge_test,
)
from eth_scanner.research.slither_runner import parse_slither_json

FIXTURES = ROOT / "tests" / "fixtures"
ADDR = "0x" + "d2" * 20


class TemplateGeneration(unittest.TestCase):
    def test_vault_staking_lending_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            for role, needle in (
                ("vault", "test_template_share_solvency"),
                ("staking", "test_template_account_lte_total"),
                ("lending", "test_template_cash_plus_borrows"),
            ):
                paths = generate_invariant_stubs(role, dest, address=ADDR)
                self.assertEqual(len(paths), 1)
                text = paths[0].read_text(encoding="utf-8")
                self.assertIn(needle, text)
                self.assertNotIn("function attack", text.lower())
                self.assertNotIn("vm.prank", text.lower())
                self.assertIn("Defensive", text)

    def test_unknown_role_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(generate_invariant_stubs("router", Path(tmp)), [])

    def test_load_template_matches_files(self):
        text = load_template("vault")
        self.assertIn("IVaultLike", text)

    def test_foundry_fixture_detected_but_forge_skips(self):
        project = FIXTURES / "research_foundry"
        self.assertTrue(is_foundry_project(project))
        with patch("eth_scanner.research.invariants.forge_available", return_value=False):
            rc, note = run_forge_test(project)
        self.assertIsNone(rc)
        self.assertIn("forge not on PATH", note)


class CustomDetectors(unittest.TestCase):
    def test_open_vault_flags_missing_auth(self):
        src = (FIXTURES / "open_vault.sol").read_text(encoding="utf-8")
        rows = detect_weak_auth_value_moves(address=ADDR, source=src)
        self.assertTrue(rows)
        self.assertTrue(all(r.defensive_only for r in rows))
        self.assertTrue(any(r.severity in {"high", "med"} for r in rows))

    def test_gated_vault_no_missing_auth_from_source(self):
        src = (FIXTURES / "gated_vault.sol").read_text(encoding="utf-8")
        rows = detect_weak_auth_value_moves(address=ADDR, source=src)
        self.assertEqual(rows, [])

    def test_4626_share_shape_info(self):
        src = (FIXTURES / "erc4626_vault_like.sol").read_text(encoding="utf-8")
        rows = detect_share_asset_shape(address=ADDR, source=src, role="vault")
        self.assertTrue(any("Share/asset accounting terms present" in r.title for r in rows))

    def test_oracle_without_freshness(self):
        src = (FIXTURES / "oracle_vault_like.sol").read_text(encoding="utf-8")
        rows = detect_oracle_freshness(address=ADDR, source=src)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].severity, "med")
        self.assertIn("freshness", rows[0].title.lower())

    def test_oracle_with_updated_at_is_info(self):
        src = """
        interface AggregatorV3Interface { function latestRoundData() external view returns (uint80,int256,uint256,uint256,uint80); }
        contract C { function p(AggregatorV3Interface f) public view returns (int256) {
            (, int256 a,, uint256 updatedAt,) = f.latestRoundData(); require(updatedAt + 1 hours > block.timestamp); return a;
        }}
        """
        rows = detect_oracle_freshness(address=ADDR, source=src)
        self.assertEqual(rows[0].severity, "info")


class GapDetectors(unittest.TestCase):
    """Shapes Slither 0.11.6 misses. Leads only: low severity, defensive_only."""

    def test_pre08_overflow_flags_and_guarded_or_modern_does_not(self):
        raw = """
        pragma solidity ^0.4.19;
        contract C {
            uint public count = 1;
            function run(uint256 input) public { count += input; }
        }
        """
        rows = detect_pre08_arithmetic(address=ADDR, source=raw)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].detector, "custom:pre08-arithmetic")
        self.assertEqual(rows[0].severity, "low")
        self.assertTrue(rows[0].defensive_only)
        guarded = """
        pragma solidity ^0.4.19;
        contract C {
            function add(uint a, uint b) public returns (uint) {
                uint c = a + b;
                require(c >= a);
                return c;
            }
        }
        """
        self.assertEqual(detect_pre08_arithmetic(address=ADDR, source=guarded), [])
        modern = """
        pragma solidity ^0.8.20;
        contract C { function run(uint input) public returns (uint) { return input + 1; } }
        """
        self.assertEqual(detect_pre08_arithmetic(address=ADDR, source=modern), [])
        internal = """
        pragma solidity ^0.4.16;
        library SafeMath {
            function add(uint a, uint b) internal returns (uint) {
                uint c = a + b;
                return c;
            }
        }
        """
        self.assertEqual(detect_pre08_arithmetic(address=ADDR, source=internal), [])

    def test_weak_entropy_sees_blockhash_and_ignores_a_deadline(self):
        lottery = """
        pragma solidity ^0.4.21;
        contract L {
            function makeBet() public {
                bool won = (block.number % 2) == 0;
            }
        }
        """
        rows = detect_weak_entropy(address=ADDR, source=lottery)
        self.assertEqual(rows[0].detector, "custom:weak-entropy")
        deal = """
        contract D {
            function deal(address player) public returns (uint8) {
                return uint8(uint256(keccak256(block.blockhash(block.number), player)) % 52);
            }
        }
        """
        self.assertTrue(detect_weak_entropy(address=ADDR, source=deal))
        deadline = """
        contract T {
            function withdraw() public {
                require(block.timestamp > 10);
            }
        }
        """
        self.assertEqual(detect_weak_entropy(address=ADDR, source=deadline), [])

    def test_unchecked_call_and_checked_call(self):
        bare = """
        pragma solidity ^0.4.10;
        contract Caller {
            function callAddress(address a) public { a.call(); }
        }
        """
        rows = detect_unchecked_low_level(address=ADDR, source=bare)
        self.assertEqual(rows[0].detector, "custom:unchecked-low-level")
        checked = """
        contract C {
            function pay(address a) public {
                (bool ok,) = a.call("");
                require(ok);
            }
        }
        """
        self.assertEqual(detect_unchecked_low_level(address=ADDR, source=checked), [])
        required = """
        contract C {
            function bid(address a) public {
                require(a.send(1));
            }
        }
        """
        self.assertEqual(detect_unchecked_low_level(address=ADDR, source=required), [])
        delegated = """
        contract C {
            function run(address a) public { a.delegatecall(""); }
        }
        """
        delegated_rows = detect_unchecked_low_level(address=ADDR, source=delegated)
        self.assertEqual(delegated_rows[0].detector, "custom:unchecked-delegatecall")
        internal = """
        contract C {
            function donateToWhale(uint256 amount) internal {
                whale.call.value(amount)(bytes4(keccak256("donate()")));
            }
        }
        """
        self.assertTrue(detect_unchecked_low_level(address=ADDR, source=internal))

    def test_hash_preimage_payout_and_unbounded_loop(self):
        puzzle = """
        pragma solidity ^0.4.22;
        contract FindThisHash {
            bytes32 public hash;
            function solve(string solution) public {
                require(hash == sha3(solution));
                msg.sender.transfer(1 ether);
            }
        }
        """
        rows = detect_hash_preimage_payout(address=ADDR, source=puzzle)
        self.assertEqual(rows[0].detector, "custom:hash-preimage-payout")
        encoded = """
        contract M {
            function claim(bytes32 leaf) public {
                require(keccak256(abi.encodePacked(leaf)) == leaf);
                msg.sender.transfer(1);
            }
        }
        """
        self.assertEqual(detect_hash_preimage_payout(address=ADDR, source=encoded), [])
        loop = """
        contract D {
            uint[] array;
            function insertNnumbers(uint value, uint numbers) public {
                for (uint i = 0; i < numbers; i++) { array.push(value); }
            }
        }
        """
        loop_rows = detect_unbounded_storage_loop(address=ADDR, source=loop)
        self.assertEqual(loop_rows[0].detector, "custom:unbounded-storage-loop")
        fixed = """
        contract D {
            address[] list;
            function fill() public {
                for (uint i = 0; i < 350; i++) { list.push(msg.sender); }
            }
        }
        """
        self.assertEqual(detect_unbounded_storage_loop(address=ADDR, source=fixed), [])


class SlitherParse(unittest.TestCase):
    def test_allowlist_and_noise_drop(self):
        payload = {
            "results": {
                "detectors": [
                    {"check": "reentrancy-eth", "impact": "High", "description": "reenter"},
                    {"check": "naming-convention", "impact": "Informational", "description": "style"},
                    {"check": "tx-origin", "impact": "Medium", "description": "tx.origin"},
                    {"check": "weak-prng", "impact": "High", "description": "blockhash % n"},
                    {"check": "timestamp", "impact": "Low", "description": "block.timestamp"},
                    {"check": "calls-loop", "impact": "Low", "description": "call in loop"},
                    {"check": "costly-loop", "impact": "Informational", "description": "sstore in loop"},
                    {"check": "multiple-constructors", "impact": "High", "description": "old and new ctor"},
                    {"check": "incorrect-shift", "impact": "High", "description": "shl args reversed"},
                ]
            }
        }
        rows = parse_slither_json(payload, address=ADDR)
        checks = {r.detector for r in rows}
        self.assertIn("slither:reentrancy-eth", checks)
        self.assertIn("slither:tx-origin", checks)
        self.assertIn("slither:weak-prng", checks)
        self.assertIn("slither:timestamp", checks)
        self.assertIn("slither:calls-loop", checks)
        self.assertIn("slither:costly-loop", checks)
        self.assertIn("slither:multiple-constructors", checks)
        self.assertIn("slither:incorrect-shift", checks)
        self.assertFalse(any("naming" in c for c in checks))
        self.assertEqual(rows[0].severity, "high")
        self.assertEqual(rows[0].layer, "L2")
        by = {r.detector: r for r in rows}
        # Noisy detectors stay in the report but are capped at informational.
        self.assertEqual(by["slither:timestamp"].severity, "info")
        self.assertEqual(by["slither:costly-loop"].severity, "info")
        self.assertEqual(by["slither:weak-prng"].severity, "high")


class ForkScaffold(unittest.TestCase):
    def test_no_rpc_skips(self):
        finding, skip, _ = TotalAssetsCheck().run(ADDR)
        self.assertIsNotNone(finding)
        self.assertEqual(finding.detector, "fork:skipped")
        self.assertIsNotNone(skip)

    def test_mock_property_ok_and_fail(self):
        ok, skip, _ = TotalAssetsCheck().run(
            ADDR, mock={"totalAssets": 100, "convertToAssets_totalSupply": 99},
        )
        self.assertIsNone(skip)
        self.assertEqual(ok.severity, "info")
        bad, skip2, _ = TotalAssetsCheck().run(
            ADDR, mock={"totalAssets": 10, "convertToAssets_totalSupply": 50},
        )
        self.assertIsNone(skip2)
        self.assertEqual(bad.severity, "high")
        self.assertIn("exceeds", bad.title)

    def test_run_fork_checks_mock(self):
        findings, skips, notes = run_fork_checks(
            address=ADDR, role="vault",
            mock={"totalAssets": 5, "convertToAssets_totalSupply": 5},
        )
        self.assertTrue(findings)
        self.assertEqual(skips, [])
        self.assertTrue(any("mock" in n.lower() for n in notes))


if __name__ == "__main__":
    unittest.main()
