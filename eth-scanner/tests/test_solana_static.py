"""Solana configuration notes. No network and no heat."""

from __future__ import annotations

import base64
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.chains.registry import _b58decode
from eth_scanner.chains.solana_discover import RpcLimited
from eth_scanner.chains.solana_static import (
    MULTISIG_OWNERS,
    UPGRADEABLE,
    inspect_program,
    scan_source,
)

PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
AUTHORITY = "So11111111111111111111111111111111111111112"
SQUADS = next(iter(MULTISIG_OWNERS))


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _program_data(programdata: bytes) -> str:
    return _b64(struct.pack("<I", 2) + programdata)


def _programdata(authority: bytes | None) -> str:
    slot = struct.pack("<Q", 9)
    if authority is None:
        body = struct.pack("<I", 3) + slot + bytes([0]) + bytes(32)
    else:
        body = struct.pack("<I", 3) + slot + bytes([1]) + authority
    return _b64(body)


class SolanaStatic(unittest.TestCase):
    def test_immutable_when_the_authority_option_is_empty(self):
        programdata = _b58decode(AUTHORITY)

        def rpc(method, params):
            self.assertNotEqual(method, "sendTransaction")
            address = params[0]
            if address == PROGRAM:
                return {"value": {"executable": True, "owner": UPGRADEABLE, "data": [_program_data(programdata), "base64"]}}
            if address == AUTHORITY:
                return {"value": {"executable": False, "owner": UPGRADEABLE, "data": [_programdata(None), "base64"]}}
            raise AssertionError(address)

        report = inspect_program(PROGRAM, rpc=rpc, fetch=lambda _url: {"is_verified": False})
        self.assertEqual(report["heat_contribution"], 0)
        self.assertEqual(report["authority_kind"], "immutable")
        self.assertTrue(report["immutable"])
        self.assertFalse(report["verified"])

    def test_single_key_and_multisig_are_labels_not_heat(self):
        programdata = _b58decode(AUTHORITY)
        authority = _b58decode(UPGRADEABLE)

        def rpc_single(method, params):
            address = params[0]
            if address == PROGRAM:
                return {"value": {"executable": True, "owner": UPGRADEABLE, "data": [_program_data(programdata), "base64"]}}
            if address == AUTHORITY:
                return {"value": {"executable": False, "owner": UPGRADEABLE, "data": [_programdata(authority), "base64"]}}
            return {"value": {"executable": False, "owner": "11111111111111111111111111111111", "data": ["", "base64"]}}

        single = inspect_program(PROGRAM, rpc=rpc_single, fetch=lambda _url: {})
        self.assertEqual(single["authority_kind"], "single-key")
        self.assertEqual(single["heat_contribution"], 0)

        def rpc_multi(method, params):
            address = params[0]
            if address == PROGRAM:
                return {"value": {"executable": True, "owner": UPGRADEABLE, "data": [_program_data(programdata), "base64"]}}
            if address == AUTHORITY:
                return {"value": {"executable": False, "owner": UPGRADEABLE, "data": [_programdata(authority), "base64"]}}
            return {"value": {"executable": False, "owner": SQUADS, "data": ["", "base64"]}}

        multi = inspect_program(PROGRAM, rpc=rpc_multi, fetch=lambda _url: {"is_verified": True, "repo_url": "https://example.invalid/src"})
        self.assertEqual(multi["authority_kind"], "squads-v4")
        self.assertEqual(multi["source_url"], "https://example.invalid/src")
        self.assertEqual(multi["heat_contribution"], 0)

    def test_rate_limit_leaves_the_kind_unknown(self):
        def rpc(method, params):
            raise RpcLimited("429")

        report = inspect_program(PROGRAM, rpc=rpc, fetch=lambda _url: {})
        self.assertTrue(report["degraded"])
        self.assertEqual(report["authority_kind"], "unknown")
        self.assertEqual(report["heat_contribution"], 0)

    def test_source_notes_add_no_heat(self):
        text = "\n".join([
            "fn pull(accounts: &[AccountInfo]) {",
            "    invoke(&instruction, accounts);",
            "    let x = a.unchecked_add(b);",
            "    let (_pda, _bump_missing) = Pubkey::find_program_address(seeds, program);",
            "}",
        ])
        # The bump word is absent on purpose: the helper name above does not include it.
        text = text.replace("_bump_missing", "slot")
        findings = scan_source(text)
        rules = {row["rule"] for row in findings}
        self.assertIn("missing-signer-check", rules)
        self.assertIn("unchecked-math", rules)
        self.assertIn("pda-bump", rules)
        self.assertTrue(all(row["heat_contribution"] == 0 for row in findings))
        self.assertNotIn("exploit", text.lower())


if __name__ == "__main__":
    unittest.main()
