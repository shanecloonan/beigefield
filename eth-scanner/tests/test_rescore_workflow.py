"""The rescore workflow uses the existing Actions secrets and does not add a public RPC."""

from __future__ import annotations

import unittest
from pathlib import Path


class RescoreWorkflowTests(unittest.TestCase):
    def test_dispatch_uses_existing_secrets(self) -> None:
        root = Path(__file__).resolve().parents[2]
        text = (root / ".github/workflows/eth-scanner-rescore.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch", text)
        self.assertIn("rescore-evidence", text)
        self.assertIn("secrets.SUPABASE_URL", text)
        self.assertIn("secrets.SUPABASE_SECRET_KEY", text)
        self.assertIn("secrets.ETH_RPC_URL", text)
        lowered = text.lower()
        self.assertNotIn("publicnode", lowered)
        self.assertNotIn("llamarpc", lowered)
        self.assertNotIn("eth.merkle", lowered)


if __name__ == "__main__":
    unittest.main()
