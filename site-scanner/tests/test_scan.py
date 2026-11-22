"""Evidence scoring, redaction, and the active-check gate."""

from __future__ import annotations

import unittest

from site_scanner.allow import active_allowed
from site_scanner.fetch import _robots_disallows, _same_origin
from site_scanner.analyze import report_for
from site_scanner.discover import parse_bounty, parse_crt, parse_tranco
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


if __name__ == "__main__":
    unittest.main()
