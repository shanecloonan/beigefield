"""Phase E optional LLM triage — skip path without keys."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.triage_ai.explain import explain_finding, llm_configured


class TriageAi(unittest.TestCase):
    def test_skips_without_key(self):
        for k in ("OPENAI_API_KEY", "ETH_SCANNER_LLM_API_KEY"):
            os.environ.pop(k, None)
        self.assertFalse(llm_configured())
        out = explain_finding({"engine": "slither", "rule": "reentrancy-eth", "title": "reentrancy"})
        self.assertEqual(out["status"], "skipped")
        self.assertFalse(out["adds_heat"])


if __name__ == "__main__":
    unittest.main()
