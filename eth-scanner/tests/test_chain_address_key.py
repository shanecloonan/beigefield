"""The remote target key is (chain, address). Ethereum rows stay addressable."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.store.supabase import SupabaseStore
from eth_scanner.types import Target

ADDR = "0x" + "ab" * 20
CONFLICT = (
    'supabase POST eth_scan_targets failed: HTTP 400 '
    '{"code":"42P10","message":"there is no unique or exclusion constraint '
    'matching the ON CONFLICT specification"}'
)


class RecordingStore(SupabaseStore):
    def __init__(self, *, fail_composite: bool = False, rows: list | None = None):
        self.url = "http://example.test"
        self.key = "service"
        self.timeout_s = 1.0
        self.calls: list[dict] = []
        self.fail_composite = fail_composite
        self.rows = list(rows or [])

    def _req(self, method, table, body=None, query=None, prefer="return=representation"):
        self.calls.append({
            "method": method,
            "table": table,
            "body": body,
            "query": dict(query or {}),
            "prefer": prefer,
        })
        if self.fail_composite and (query or {}).get("on_conflict") == "chain,address":
            raise RuntimeError(CONFLICT)
        if method == "GET":
            return list(self.rows)
        return []


class ChainAddressKey(unittest.TestCase):
    def test_the_same_address_is_stored_on_two_chains(self):
        store = RecordingStore()
        store.upsert_target(Target(address=ADDR, status="pending", funds_usd=10))
        store.upsert_target(Target(address=ADDR, chain="bsc", status="pending", funds_usd=5000))
        posts = [call for call in store.calls if call["method"] == "POST"]
        self.assertEqual(len(posts), 2)
        self.assertEqual(posts[0]["query"]["on_conflict"], "chain,address")
        self.assertEqual(posts[0]["body"]["chain"], "ethereum")
        self.assertEqual(posts[1]["body"]["chain"], "bsc")
        self.assertEqual(posts[0]["body"]["address"], posts[1]["body"]["address"])
        self.assertEqual(posts[0]["body"]["funds_usd"], 10)
        self.assertEqual(posts[1]["body"]["funds_usd"], 5000)

    def test_a_second_chain_does_not_fall_back_onto_the_address_key(self):
        store = RecordingStore(fail_composite=True)
        with self.assertRaises(RuntimeError):
            store.upsert_target(Target(address=ADDR, chain="arbitrum", status="pending"))
        self.assertEqual(len(store.calls), 1)
        self.assertEqual(store.calls[0]["query"]["on_conflict"], "chain,address")

    def test_ethereum_still_writes_when_the_composite_key_is_absent(self):
        store = RecordingStore(fail_composite=True)
        store.upsert_target(Target(address=ADDR, funds_usd=10))
        self.assertEqual(len(store.calls), 2)
        self.assertNotIn("on_conflict", store.calls[1]["query"])
        self.assertEqual(store.calls[1]["body"]["chain"], "ethereum")
        self.assertEqual(store.calls[1]["body"]["address"], ADDR)

    def test_reads_and_patches_filter_by_chain(self):
        store = RecordingStore(rows=[{"address": ADDR, "chain": "base", "status": "pending"}])
        self.assertEqual(store.get_target(ADDR, chain="base")["chain"], "base")
        self.assertEqual(store.calls[-1]["query"]["chain"], "eq.base")
        self.assertEqual(store.calls[-1]["query"]["address"], "eq.%s" % ADDR)
        store.get_target(ADDR)
        self.assertEqual(store.calls[-1]["query"]["chain"], "eq.ethereum")
        store.requeue_target(ADDR, chain="base")
        patch = store.calls[-1]
        self.assertEqual(patch["method"], "PATCH")
        self.assertEqual(patch["query"]["chain"], "eq.base")
        self.assertEqual(patch["query"]["address"], "eq.%s" % ADDR)
        self.assertEqual(patch["body"]["status"], "pending")


if __name__ == "__main__":
    unittest.main()
