"""Phase B fork property catalog + evidence sanitization."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.fork_props.catalog import properties_for_class
from eth_scanner.fork_props.runner import sanitize_fork_evidence, run_fork_properties
from eth_scanner.invariants.live import LiveInvariantResult


class Catalog(unittest.TestCase):
    def test_vault_and_custody_catalogs(self):
        v = properties_for_class("vault")
        self.assertTrue(any(p["id"] == "erc4626-solvency" for p in v))
        c = properties_for_class("custody")
        self.assertTrue(any(p["id"] == "privileged-callable" for p in c))


class Sanitize(unittest.TestCase):
    def test_elides_calldata_and_traces(self):
        raw = "ok Traces: call 0x" + ("ab" * 80) + " drain()"
        out = sanitize_fork_evidence(raw)
        self.assertIn("elided", out.lower())
        self.assertNotIn("ababab", out)


class RunnerMapping(unittest.TestCase):
    def test_maps_live_failed_to_violated(self):
        live = [
            LiveInvariantResult(
                "erc4626-solvency",
                "convertToAssets(totalSupply) <= totalAssets",
                "failed",
                "convertToAssets=10 totalAssets=1 tol=1",
                contract_class="vault",
                extras={"converted": 10, "totalAssets": 1},
            )
        ]
        with mock.patch(
            "eth_scanner.fork_props.runner.run_live_invariants",
            return_value=live,
        ):
            rows = run_fork_properties(
                "0x1111111111111111111111111111111111111111",
                contract_class="vault",
                run_forge=False,
            )
        solv = [r for r in rows if r.id == "erc4626-solvency"][0]
        self.assertEqual(solv.status, "violated")
        self.assertIn("convertToAssets", solv.evidence)


if __name__ == "__main__":
    unittest.main()
