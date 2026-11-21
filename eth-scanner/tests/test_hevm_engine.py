"""hevm sits beside Halmos. A missing binary adds no heat."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.deep.runners import run_hevm_engine


class HevmEngine(unittest.TestCase):
    def test_a_missing_binary_is_skipped(self):
        with patch("eth_scanner.deep.runners.hevm_bin", return_value=None):
            result = run_hevm_engine("/tmp/does-not-matter")
        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.findings, [])
        self.assertIn("not on PATH", result.note)

    def test_missing_bytecode_is_skipped(self,):
        with patch("eth_scanner.deep.runners.hevm_bin", return_value="/usr/bin/hevm"):
            result = run_hevm_engine("/tmp/no-such-project-hevm")
        self.assertEqual(result.status, "skipped")
        self.assertIn("bytecode", result.note)

    def test_a_local_failure_is_generic_and_not_profit(self):
        root = Path("/tmp/hevm-fixture-project")
        out = root / "out" / "C.sol"
        out.mkdir(parents=True, exist_ok=True)
        (out / "C.json").write_text(json.dumps({
            "deployedBytecode": {"object": "0x6080604052"},
        }), encoding="utf-8")

        def fake_run(argv, **_kwargs):
            self.assertEqual(argv[1], "symbolic")
            self.assertLessEqual(_kwargs["timeout"], 20)
            return subprocess.CompletedProcess(argv, 1, stdout="Assertion violation\n", stderr="")

        with patch("eth_scanner.deep.runners.hevm_bin", return_value="/usr/bin/hevm"), \
                patch("eth_scanner.deep.runners.subprocess.run", side_effect=fake_run):
            result = run_hevm_engine(str(root), timeout_s=20)
        self.assertEqual(result.status, "ok")
        self.assertEqual(len(result.findings), 1)
        self.assertTrue(result.findings[0].generic)
        self.assertNotIn("caller_profit_delta=", result.findings[0].evidence)


if __name__ == "__main__":
    unittest.main()
