"""Echidna is evidence unless a fork check shows the caller gained value."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.deep.echidna_runner import findings_from_echidna, parse_echidna_output
from eth_scanner.deep.medusa_runner import fork_profit_results
from eth_scanner.deep.strong import heat_if_live_confirmed
from eth_scanner.drain import simulate_local_vault


class EchidnaParse(unittest.TestCase):
    def test_setup_crash_adds_nothing(self):
        self.assertEqual(parse_echidna_output("setUp() failed to compile"), [])

    def test_solvency_failure_is_evidence_only(self):
        text = "echidna_share_solvency: failed! Call sequence: deposit(1)"
        rows = parse_echidna_output(text)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["caller_profit"])
        self.assertEqual(fork_profit_results(findings_from_echidna(text)), [])
        heat, changed, _ = heat_if_live_confirmed(1, 40_000, [])
        self.assertEqual(heat, 1)
        self.assertFalse(changed)

    def test_leaky_vault_caller_profit_raises_heat(self):
        leaked = simulate_local_vault("leaky")
        delta = int(leaked["invariant"]["attacker_delta"])
        text = "echidna_no_caller_profit: failed!\ncaller_profit_delta=%s\n" % delta
        proofs = fork_profit_results(findings_from_echidna(text))
        self.assertEqual(proofs[0]["attacker_delta"], delta)
        heat, changed, bd = heat_if_live_confirmed(0, 20_000, proofs)
        self.assertTrue(changed)
        self.assertTrue(bd["profit_invariant_broke"])

    def test_safe_vault_does_not_fire(self):
        safe = simulate_local_vault("safe")
        self.assertFalse(safe["profit_invariant_broke"])
        text = "echidna_no_caller_profit: passing\ncaller_profit_delta=0\n"
        self.assertEqual(fork_profit_results(findings_from_echidna(text)), [])
        heat, changed, _ = heat_if_live_confirmed(0, 20_000, [])
        self.assertEqual(heat, 0)
        self.assertFalse(changed)


if __name__ == "__main__":
    unittest.main()
