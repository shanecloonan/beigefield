"""Evidence scoring, redaction, and the active-check gate."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from site_scanner.allow import active_allowed
import asyncio

import httpx

from site_scanner.fetch import USER_AGENT, _robots_disallows, _same_origin, fetch_host
from site_scanner.fingerprint import match_page
from site_scanner.analyze import report_for
from site_scanner.discover import (
    hosts_from_certstream,
    hosts_from_san,
    mix_hosts,
    names_from_crt_rows,
    parse_bounty,
    parse_crt,
    parse_tranco,
    sample_tranco_lines,
    source_counts,
    take_batch,
    usable_host,
)
from site_scanner.migrate import missing_ddl_secrets, pg_env
from site_scanner.store import _error_code
from site_scanner.redact import redact


LEAK = """
<html><title>Settings</title>
<script src="https://cdn.example/jquery-1.12.4.min.js"></script>
<script>
const key = "AKIAIOSFODNN7EXAMPLE";
const api = "https://abcd1234wxyz.supabase.co";
</script>
</html>
"""


class ScanTests(unittest.TestCase):
    def test_redact_removes_the_token(self) -> None:
        text, kinds = redact("key AKIAIOSFODNN7EXAMPLE end")
        self.assertIn("aws-access-key", kinds)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", text)
        self.assertIn("«redacted:aws-access-key»", text)

    def test_leaky_page_scores_evidence_and_hides_the_secret(self) -> None:
        report = report_for("app.example", [{
            "path": "/",
            "scheme": "https",
            "status": 200,
            "headers": {},
            "body": LEAK,
        }], active_ran=False)
        self.assertIn("missing-csp", report["facts"])
        self.assertIn("missing-hsts", report["facts"])
        self.assertIn("secret-in-page", report["facts"])
        self.assertIn("old-library", report["facts"])
        self.assertLessEqual(report["heat"], 12)
        self.assertEqual(report["score_state"], "provisional")
        self.assertEqual(report["pending_stages"], ["active-baseline"])
        blob = str(report)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", blob)
        secret = next(item for item in report["findings"] if item["id"] == "secret-in-page")
        self.assertIn("aws-access-key", secret["evidence"])
        self.assertNotIn("AKIA", secret["evidence"])

    def test_env_and_git_are_separate_facts(self) -> None:
        report = report_for("app.example", [
            {"path": "/.env", "status": 200, "headers": {}, "body": "API_KEY=supersecretvalue"},
            {"path": "/.git/HEAD", "status": 200, "headers": {}, "body": "ref: refs/heads/main\n"},
        ], active_ran=True)
        self.assertIn("exposed-env", report["facts"])
        self.assertIn("exposed-git", report["facts"])
        self.assertEqual(report["score_state"], "final")
        self.assertNotIn("supersecretvalue", str(report["findings"]))

    def test_active_checks_stay_on_the_allowlist(self) -> None:
        self.assertTrue(active_allowed("beigefield.vercel.app"))
        self.assertTrue(active_allowed("https://dap-ashy.vercel.app/path"))
        self.assertFalse(active_allowed("example.com"))
        self.assertTrue(active_allowed("shop.example", {"shop.example"}))

    def test_lists_parse_without_a_network_call(self) -> None:
        self.assertEqual(parse_crt([{"common_name": "*.Login.Example.com"}], limit=5), ["login.example.com"])
        self.assertEqual(parse_tranco("1,google.com\n2,example.com\n", limit=1), ["google.com"])

    def test_bounty_scope_drops_exclusions(self) -> None:
        hosts = parse_bounty([{
            "targets": {
                "in_scope": [
                    {"asset_identifier": "https://app.example", "asset_type": "URL", "eligible_for_submission": True},
                    {"asset_identifier": "https://admin.example", "asset_type": "URL"},
                    {"asset_identifier": "api.example", "asset_type": "WILDCARD"},
                ],
                "out_of_scope": [
                    {"asset_identifier": "https://admin.example", "asset_type": "URL"},
                ],
            },
        }])
        self.assertEqual(hosts, ["app.example"])

    def test_pending_stage_does_not_change_heat(self) -> None:
        page = {"path": "/", "scheme": "https", "status": 200, "headers": {"content-security-policy": "default-src 'self'", "strict-transport-security": "max-age=10"}, "body": "<html>ok</html>"}
        quiet = report_for("owned.example", [page], active_ran=False)
        done = report_for("owned.example", [page], active_ran=True)
        self.assertEqual(quiet["heat"], 0)
        self.assertEqual(done["heat"], quiet["heat"])
        self.assertEqual(quiet["score_state"], "provisional")
        self.assertEqual(done["score_state"], "final")

    def test_robots_and_script_urls_stay_on_the_host(self) -> None:
        robots = "User-agent: *\nDisallow: /.env\n"
        self.assertTrue(_robots_disallows(robots, "/.env"))
        self.assertFalse(_robots_disallows(robots, "/"))
        self.assertEqual(_same_origin("app.example", "/_next/static/app.js"), "https://app.example/_next/static/app.js")
        self.assertEqual(_same_origin("app.example", "https://cdn.example/app.js"), "")

    def test_discovery_keeps_random_hosts_passive(self) -> None:
        hosts = mix_hosts(
            owned=["beigefield.vercel.app"],
            bounty=["app.example"],
            crt=["*.new.example"],
            tranco=["shop.example", "app.example"],
            limit=4,
        )
        self.assertEqual(hosts, ["beigefield.vercel.app", "app.example", "new.example", "shop.example"])
        bounty = {"app.example"}
        self.assertTrue(active_allowed("app.example", bounty))
        self.assertFalse(active_allowed("shop.example", bounty))
        self.assertFalse(active_allowed("new.example", bounty))
        self.assertEqual(usable_host("*.Login.Example"), "login.example")
        message = {"data": {"leaf_cert": {"all_domains": ["*.issued.example", "localhost"]}}}
        self.assertEqual(hosts_from_certstream(message), ["issued.example"])
        lines = "\n".join("%s,site-%s.example" % (rank, rank) for rank in range(1, 600))
        picked = sample_tranco_lines(lines, limit=2, start_rank=500, rng=__import__("random").Random(1))
        self.assertEqual(len(picked), 2)
        self.assertTrue(all(host.startswith("site-5") for host in picked))
        counts = source_counts(hosts, owned=["beigefield.vercel.app"], bounty=["app.example"], crt=["new.example"], tranco=["shop.example"])
        self.assertEqual(counts, {"owned": 1, "bounty": 1, "certificate": 1, "tranco": 1})

    def test_a_host_excluded_by_any_program_is_dropped(self) -> None:
        hosts = parse_bounty([
            {"targets": {"in_scope": [{"asset_identifier": "https://app.example", "asset_type": "URL"}], "out_of_scope": [{"asset_identifier": "https://admin.example"}]}},
            {"targets": {"in_scope": [{"asset_identifier": "https://admin.example", "asset_type": "URL"}]}},
        ])
        self.assertEqual(hosts, ["app.example"])

    def test_migration_report_names_missing_secrets_only(self) -> None:
        self.assertEqual(
            missing_ddl_secrets({}),
            ["DATABASE_URL or SUPABASE_DB_PASSWORD", "SUPABASE_ACCESS_TOKEN"],
        )
        env = {"DATABASE_URL": "postgresql://postgres:s3cret@db.example:5432/postgres"}
        self.assertNotIn("s3cret", str(missing_ddl_secrets(env)))
        child = pg_env(env)
        assert child is not None
        self.assertEqual(child["PGHOST"], "db.example")
        self.assertEqual(child["PGPASSWORD"], "s3cret")
        self.assertEqual(_error_code('{"code":"PGRST205","message":"AKIAIOSFODNN7EXAMPLE"}'), "PGRST205")
        self.assertEqual(_error_code('{"message":"AKIAIOSFODNN7EXAMPLE"}'), "")

    def test_header_hygiene_stays_visible_and_low(self) -> None:
        bare = report_for("app.example", [{
            "path": "/",
            "scheme": "https",
            "status": 200,
            "headers": {},
            "body": "<html></html>",
        }], active_ran=True)
        self.assertEqual(bare["heat"], 1)
        self.assertIn("missing-csp", bare["facts"])
        self.assertIn("missing-hsts", bare["facts"])
        self.assertEqual(len([item for item in bare["findings"] if item["id"] in {"missing-csp", "missing-hsts"}]), 2)
        leaked = report_for("app.example", [{
            "path": "/",
            "scheme": "https",
            "status": 200,
            "headers": {"content-security-policy": "default-src 'none'", "strict-transport-security": "max-age=10"},
            "body": "key AKIAIOSFODNN7EXAMPLE",
        }], active_ran=True)
        self.assertGreaterEqual(leaked["heat"], 8)
        self.assertGreater(leaked["heat"], bare["heat"])

    def test_crt_rows_prefer_the_last_hour(self) -> None:
        now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
        names = names_from_crt_rows([
            {"common_name": "old.example", "entry_timestamp": "2026-11-21T00:00:00"},
            {"common_name": "*.fresh.example", "entry_timestamp": "2026-11-22T11:30:00"},
        ], now=now, hours=1, limit=5)
        self.assertEqual(names, ["fresh.example"])
        fallback = names_from_crt_rows([
            {"common_name": "old.example", "entry_timestamp": "2026-11-21T00:00:00"},
        ], now=now, hours=1, limit=5)
        self.assertEqual(fallback, ["old.example"])
        self.assertEqual(hosts_from_san("DNS:alpha.example, DNS:*.beta.example"), ["alpha.example", "beta.example"])

    def test_the_cursor_walks_forward_and_then_wraps(self) -> None:
        pool = ["owned.example", "a.example", "b.example", "c.example", "d.example"]
        first, seen, wrapped = take_batch(pool, [], 2)
        self.assertEqual(first, ["owned.example", "a.example"])
        self.assertFalse(wrapped)
        second, seen, wrapped = take_batch(pool, seen, 2)
        self.assertEqual(second, ["b.example", "c.example"])
        self.assertFalse(wrapped)
        third, seen, wrapped = take_batch(pool, seen, 2)
        self.assertEqual(third, ["d.example", "owned.example"])
        self.assertTrue(wrapped)
        self.assertEqual(seen, ["d.example", "owned.example"])
        self.assertEqual(take_batch([], ["a.example"], 2), ([], ["a.example"], False))

    def test_the_schedule_is_hourly_with_a_small_batch(self) -> None:
        from pathlib import Path
        text = Path(__file__).resolve().parents[2].joinpath(".github/workflows/site-scanner.yml").read_text()
        self.assertIn('cron: "47 * * * *"', text)
        self.assertIn("cancel-in-progress: false", text)
        self.assertIn("--limit 6", text)
        self.assertIn("workflow_dispatch", text)
        self.assertNotIn("*/10 * * * *", text)

    def test_a_challenge_is_not_retried_and_adds_no_heat(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            self.assertEqual(request.headers["user-agent"], USER_AGENT)
            self.assertIn("beigefield.com", request.headers["user-agent"])
            return httpx.Response(403, text="Just a moment... cf-browser-verification", headers={"server": "cloudflare"})

        async def no_sleep(_seconds: float) -> None:
            return None

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport, headers={"User-Agent": USER_AGENT})
        try:
            pages = fetch_host(
                "blocked.example",
                active=False,
                pause_s=0,
                client=client,
                tls_check=lambda _host: {"tls_expired": False, "tls_soon": False},
                sleep=no_sleep,
            )
        finally:
            asyncio.run(client.aclose())
        self.assertEqual(calls["n"], 1)
        self.assertTrue(pages[0]["challenged"])
        self.assertEqual(pages[0]["body"], "")
        report = report_for("blocked.example", pages, active_ran=False)
        self.assertEqual(report["heat"], 0)
        self.assertIn("challenged", report["facts"])
        self.assertEqual(report["findings"][0]["heat"], 0)

    def test_a_transient_status_is_retried_once(self) -> None:
        calls = {"n": 0}

        def handler(_request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(503, text="unavailable")
            return httpx.Response(200, text="User-agent: *\nDisallow: /private\n")

        async def no_sleep(_seconds: float) -> None:
            return None

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        try:
            pages = fetch_host(
                "retry.example",
                active=False,
                pause_s=0,
                client=client,
                tls_check=lambda _host: {"tls_expired": False, "tls_soon": False},
                sleep=no_sleep,
            )
        finally:
            asyncio.run(client.aclose())
        self.assertGreaterEqual(calls["n"], 2)
        self.assertEqual(pages[0]["status"], 200)
        self.assertEqual(pages[0]["path"], "/robots.txt")

    def test_a_version_is_evidence_and_only_known_eol_adds_heat(self) -> None:
        catalog = {
            "jQuery": {"scriptSrc": "jquery[.-](\\d+\\.\\d+\\.\\d+)\\;version:\\1"},
            "Nginx": {"headers": {"server": "nginx(?:/(\\d+\\.\\d+\\.\\d+))?\\;version:\\1"}},
            "DemoLib": {"js": {"DemoLib.version": "(\\d+\\.\\d+)\\;version:\\1"}},
        }
        page = {
            "path": "/",
            "status": 200,
            "headers": {"server": "nginx/1.24.0"},
            "body": "<script src=\"/jquery-1.12.4.min.js\"></script>",
            "js_globals": {"DemoLib.version": "2.1"},
        }
        hits = match_page(page, catalog=catalog)
        by_name = {item["name"]: item for item in hits}
        self.assertEqual(by_name["jQuery"]["version"], "1.12.4")
        self.assertTrue(by_name["jQuery"]["eol"])
        self.assertEqual(by_name["Nginx"]["version"], "1.24.0")
        self.assertFalse(by_name["Nginx"]["eol"])
        self.assertEqual(by_name["DemoLib"]["version"], "2.1")
        self.assertEqual(by_name["DemoLib"]["source"], "js")
        self.assertEqual(by_name["jQuery"]["heat_contribution"], 0)
        report = report_for("app.example", [page], active_ran=True)
        self.assertIn("known-eol", report["facts"])
        eol = next(item for item in report["findings"] if item["id"] == "known-eol")
        self.assertIn("jQuery 1.12.4", eol["evidence"])
        self.assertNotIn("Nginx", eol["evidence"])
        self.assertGreater(eol["heat"], 0)


if __name__ == "__main__":
    unittest.main()
