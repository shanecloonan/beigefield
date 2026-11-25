"""Bytecode surface: union, heat, harness files, and the invariant filter."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.heat import evidence_heat
from eth_scanner.logic.bytecode_surface import (
    actions_for_surface,
    harness_calls,
    prefix_report,
    recover_surface,
    write_surface_inputs,
)
from eth_scanner.logic.sequences import run_sequence_invariants

IMPL = "0x2222222222222222222222222222222222222222"
_EVMOLE = {
    "functions": [
        {"selector": "b460af94", "arguments": "uint256,address,address", "state_mutability": "nonpayable"},
        {"selector": "01e1d114", "arguments": "", "state_mutability": "view"},
    ],
    "storage": [{"slot": "0", "offset": 0, "type": "uint256"}],
    "proxies": [{"kind": "eip7702", "implementation": IMPL}],
}
_WHATSABI = {
    "functions": [
        {"selector": "0xb460af94", "stateMutability": "payable"},
        {"selector": "0x6e553f65", "stateMutability": "nonpayable"},
    ],
    "proxies": [{"name": "EIP7702", "implementation": IMPL}],
}


class Union(unittest.TestCase):
    def test_evmole_mutability_wins_and_selectors_merge(self):
        surface = recover_surface(
            "0x",
            evmole_report=_EVMOLE,
            whatsabi_report=_WHATSABI,
            use_evmole=False,
            use_whatsabi=False,
        )
        by_sel = {row["selector"]: row for row in surface["functions"]}
        self.assertEqual(by_sel["b460af94"]["mutability"], "nonpayable")
        self.assertEqual(sorted(by_sel["b460af94"]["sources"]), ["evmole", "whatsabi"])
        self.assertIn("6e553f65", by_sel)
        self.assertEqual(surface["proxy_kind"], "eip7702")
        self.assertEqual(surface["implementation"], IMPL)
        self.assertEqual(surface["storage"][0]["slot"], "0")
        self.assertTrue(surface["tools"]["evmole"])
        self.assertTrue(surface["tools"]["whatsabi"])

    def test_prefix_reads_a_delegation_and_a_clone(self):
        delegated = "0xef0100" + IMPL[2:]
        found = prefix_report(delegated)
        self.assertEqual(found["proxy_kind"], "eip7702")
        self.assertEqual(found["implementation"], IMPL)
        clone = "0x363d3d373d3d3d363d73" + IMPL[2:] + "5af43d82803e903d91602b57fd5bf3"
        cloned = prefix_report(clone)
        self.assertEqual(cloned["proxy_kind"], "eip1167")
        self.assertEqual(cloned["implementation"], IMPL)

    def test_missing_tools_do_not_raise(self):
        surface = recover_surface("", use_evmole=False, use_whatsabi=False)
        self.assertEqual(surface["functions"], [])
        self.assertEqual(surface["surface_evidence"], 0)
        self.assertIn("evmole", surface["pins"])


class Heat(unittest.TestCase):
    def test_delegation_adds_two_and_shows(self):
        surface = recover_surface("0x", evmole_report=_EVMOLE, use_evmole=False, use_whatsabi=False)
        heat, bd = evidence_heat(funds_usd=None, invariant_results=[], bytecode_surface=surface)
        self.assertEqual(bd["surface_evidence"], 2)
        self.assertTrue(bd["bytecode_surface"])
        self.assertEqual(heat, 2)

    def test_eip1967_is_shown_and_does_not_add_points(self):
        surface = recover_surface(
            "0x",
            whatsabi_report={
                "functions": [{"selector": "01e1d114", "stateMutability": "view"}],
                "proxies": [{"name": "EIP1967Proxy", "implementation": IMPL}],
            },
            use_evmole=False,
            use_whatsabi=False,
        )
        heat, bd = evidence_heat(funds_usd=None, invariant_results=[], bytecode_surface=surface)
        self.assertEqual(bd["surface_evidence"], 0)
        self.assertEqual(bd["surface_overlap"], "proxy")
        self.assertTrue(bd["bytecode_surface"])
        self.assertEqual(heat, 0)

    def test_clone_with_a_value_selector_adds_two(self):
        surface = recover_surface(
            "0x",
            evmole_report={
                "functions": [{"selector": "a9059cbb", "arguments": "address,uint256", "state_mutability": "nonpayable"}],
                "proxies": [{"kind": "eip1167", "implementation": IMPL}],
            },
            use_evmole=False,
            use_whatsabi=False,
        )
        self.assertEqual(surface["surface_evidence"], 2)
        self.assertTrue(harness_calls(surface))

    def test_admin_plus_delegation_is_not_capped_as_admin_only(self):
        surface = recover_surface("0x", evmole_report=_EVMOLE, use_evmole=False, use_whatsabi=False)
        heat, bd = evidence_heat(
            funds_usd=200_000,
            invariant_results=[],
            eoa_admin=True,
            bytecode_surface=surface,
            source="function deposit(uint256 assets) external { uint256 bal = token.balanceOf(address(this)); }",
        )
        self.assertEqual(bd["surface_evidence"], 2)
        self.assertFalse(bd["admin_capped"])
        self.assertGreaterEqual(heat, 5)


class Harness(unittest.TestCase):
    def test_files_and_sequence_filter(self):
        surface = recover_surface("0x", evmole_report=_EVMOLE, whatsabi_report=_WHATSABI, use_evmole=False, use_whatsabi=False)
        allowed = actions_for_surface(surface)
        self.assertIsNotNone(allowed)
        self.assertIn("withdraw", allowed)
        self.assertIn("deposit", allowed)
        self.assertNotIn("redeem", allowed)
        report = run_sequence_invariants("fair", allowed_actions=allowed)
        self.assertGreater(report["skipped_sequences"], 0)
        self.assertLess(report["sequences"], 5)
        with self.subTest("files"):
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                written = write_surface_inputs(Path(tmp), surface)
                self.assertEqual(len(written), 3)
                text = (Path(tmp) / "corpus" / "ityfuzz" / "selectors.txt").read_text(encoding="utf-8")
                self.assertIn("b460af94", text)
                payload = json.loads((Path(tmp) / "corpus" / "surface.json").read_text(encoding="utf-8"))
                self.assertEqual(payload["proxy_kind"], "eip7702")
                sol = (Path(tmp) / "src" / "RecoveredSelectors.sol").read_text(encoding="utf-8")
                self.assertIn("function withdraw(uint256,address,address) external nonpayable;", sol)
                self.assertNotIn("calldata", sol.lower())


if __name__ == "__main__":
    unittest.main()
