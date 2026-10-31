"""ETHERSCAN_API_KEYS / SUPABASE_URL come from env only (nothing baked in)."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.config import load_settings


def _settings(**env):
    base = {k: v for k, v in os.environ.items() if k not in {"ETHERSCAN_API_KEYS", "SUPABASE_URL", "ETH_SCANNER_SUPABASE_URL"}}
    base.update(env)
    with mock.patch.dict(os.environ, base, clear=True):
        with mock.patch("eth_scanner.config._load_dotenv"):
            return load_settings()


class EnvOnlyConfig(unittest.TestCase):
    def test_unset_has_no_keys(self):
        self.assertEqual(_settings().etherscan_api_keys, [])

    def test_blank_has_no_keys(self):
        self.assertEqual(_settings(ETHERSCAN_API_KEYS="  ").etherscan_api_keys, [])

    def test_env_keys_split(self):
        self.assertEqual(
            _settings(ETHERSCAN_API_KEYS="override-key, other-key").etherscan_api_keys,
            ["override-key", "other-key"],
        )

    def test_no_baked_supabase_url(self):
        s = _settings(SUPABASE_SERVICE_ROLE_KEY="role", NEXT_PUBLIC_SUPABASE_URL="https://public-site.supabase.co")
        self.assertEqual(s.supabase_url, "")
        self.assertFalse(s.persist_remote)


if __name__ == "__main__":
    unittest.main()
