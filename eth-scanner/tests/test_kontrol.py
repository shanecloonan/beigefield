"""Kontrol fails soft. A missing binary adds no heat."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.advanced.kontrol import run_kontrol


class KontrolFailSoft(unittest.TestCase):
    def test_a_missing_binary_is_skipped(self):
        with patch("eth_scanner.advanced.kontrol.kontrol_bin", return_value=None):
            result = run_kontrol("/tmp/no-kontrol")
        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.findings, [])
        self.assertEqual(result.duration_ms, 0)

    def test_without_a_foundry_project_it_does_not_start(self):
        with patch("eth_scanner.advanced.kontrol.kontrol_bin", return_value="/usr/bin/kontrol"):
            result = run_kontrol("/tmp/no-such-kontrol-project")
        self.assertEqual(result.status, "skipped")
        self.assertIn("foundry.toml", result.note)

    def test_a_timeout_is_an_error_and_adds_no_finding(self):
        root = Path("/tmp/kontrol-fixture")
        root.mkdir(parents=True, exist_ok=True)
        (root / "foundry.toml").write_text("[profile.default]\n", encoding="utf-8")

        def explode(*_args, **_kwargs):
            raise subprocess.TimeoutExpired(cmd="kontrol", timeout=30)

        with patch("eth_scanner.advanced.kontrol.kontrol_bin", return_value="/usr/bin/kontrol"), \
                patch("eth_scanner.advanced.kontrol.subprocess.run", side_effect=explode):
            result = run_kontrol(str(root), timeout_s=30)
        self.assertEqual(result.status, "error")
        self.assertEqual(result.findings, [])
        self.assertIn("timed out", result.note)


if __name__ == "__main__":
    unittest.main()
