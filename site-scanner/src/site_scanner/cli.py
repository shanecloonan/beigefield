"""Scan a few hosts and print a redacted report."""

from __future__ import annotations

import argparse
import json

from site_scanner.allow import active_allowed, host_of
from site_scanner.analyze import report_for
from site_scanner.cloud import annotate_cloud
from site_scanner.discover import FALLBACK_HOSTS, crt_hosts, tranco_hosts
from site_scanner.fetch import fetch_host
from site_scanner.store import save_hit


def _hosts(args: argparse.Namespace) -> list[str]:
    named = [host_of(item) for item in (args.hosts or "").split(",") if item.strip()]
    if named:
        return named[: args.limit]
    found = crt_hosts(args.crt, limit=args.limit) if args.crt else []
    if not found and args.tranco:
        found = tranco_hosts(limit=args.limit)
    if not found:
        found = list(FALLBACK_HOSTS)
    return found[: args.limit]


def scan_host(host: str, *, bounty: set[str]) -> dict:
    allowed = active_allowed(host, bounty)
    pages = fetch_host(host, active=allowed, pause_s=0.3)
    annotate_cloud(pages)
    report = report_for(host, pages, active_ran=allowed)
    report["persist"] = save_hit(report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(prog="site-scanner")
    parser.add_argument("cmd", choices=["scan"])
    parser.add_argument("--hosts", default="")
    parser.add_argument("--crt", default="")
    parser.add_argument("--tranco", action="store_true")
    parser.add_argument("--bounty-hosts", default="", help="Comma-separated in-scope hosts. Active checks stay off otherwise.")
    parser.add_argument("--limit", type=int, default=4)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    bounty = {host_of(item) for item in args.bounty_hosts.split(",") if item.strip()}
    reports = [scan_host(host, bounty=bounty) for host in _hosts(args)]
    payload = {"status": "ok", "scanned": len(reports), "reports": reports}
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        for report in reports:
            print("%s heat=%s mode=%s facts=%s" % (report["host"], report["heat"], report["mode"], ",".join(report["facts"])))


if __name__ == "__main__":
    main()
