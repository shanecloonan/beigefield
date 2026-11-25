"""Bytecode clone matching. Metadata differences still match. No exploit code."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.heat import evidence_heat
from eth_scanner.logic.clones import (
    forta_alerts,
    load_index,
    match_runtime,
    normalize_runtime,
    runtime_hash,
)


def _with_meta(body: str, meta: str) -> str:
    return body + meta + f"{len(meta) // 2:04x}"


class Clones(unittest.TestCase):
    def setUp(self):
        self.body = "60" * 200
        self.meta_a = "a2646970667358221220" + "11" * 16
        self.meta_b = "a2646970667358221220" + "22" * 16
        self.code = _with_meta(self.body, self.meta_a)
        self.same = _with_meta(self.body, self.meta_b)
        self.near = _with_meta(self.body + "60016002", self.meta_a)
        self.other = _with_meta("61" * 200, self.meta_a)

    def test_metadata_does_not_change_the_hash(self):
        self.assertEqual(normalize_runtime(self.code), self.body)
        self.assertEqual(runtime_hash(self.code), runtime_hash(self.same))
        self.assertNotIn(self.meta_a, normalize_runtime(self.code))

    def test_exact_and_near(self):
        index = [{"id": "known-vault", "runtime": self.code}]
        exact = match_runtime(self.same, index)
        self.assertEqual(exact["kind"], "exact")
        self.assertEqual(exact["weight"], 3)
        near = match_runtime(self.near, index)
        self.assertEqual(near["kind"], "near")
        self.assertEqual(near["weight"], 1)
        self.assertGreaterEqual(near["similarity"], 0.92)
        none = match_runtime(self.other, index)
        self.assertEqual(none["kind"], "none")
        self.assertEqual(none["weight"], 0)

    def test_hash_only_index_matches_exact(self):
        index = [{"id": "hash-only", "runtime_hash": runtime_hash(self.code)}]
        found = match_runtime(self.same, index)
        self.assertEqual(found["kind"], "exact")
        self.assertEqual(found["id"], "hash-only")

    def test_heat_uses_the_match_weight(self):
        found = match_runtime(self.same, [{"id": "known-vault", "runtime": self.code}])
        heat, bd = evidence_heat(funds_usd=None, invariant_results=[], clone_match=found)
        self.assertEqual(bd["clone_evidence"], 3)
        self.assertEqual(heat, 3)
        self.assertEqual(bd["clone_match"]["id"], "known-vault")

    def test_shipped_index_has_no_bytecode(self):
        rows = load_index()
        self.assertEqual(rows, [])

    def test_forta_names_add_no_heat(self):
        quiet = forta_alerts()
        self.assertFalse(quiet["enabled"])
        self.assertEqual(quiet["heat_contribution"], 0)
        named = forta_alerts([{"name": "Suspicious contract creation", "tx": "0xabc"}])
        self.assertEqual(named["alerts"], ["Suspicious contract creation"])
        self.assertEqual(named["heat_contribution"], 0)
        self.assertNotIn("0x", " ".join(named["alerts"]))

    def test_load_index_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.json"
            path.write_text(json.dumps({"entries": [{"id": "a", "runtime_hash": "ab"}]}), encoding="utf-8")
            self.assertEqual(load_index(path)[0]["id"], "a")


if __name__ == "__main__":
    unittest.main()
