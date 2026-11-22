"""Scan a few hosts and print a redacted report."""

from __future__ import annotations

import argparse
import json
import time

from site_scanner.allow import active_allowed, host_of
from site_scanner.analyze import report_for
from site_scanner.cloud import annotate_cloud
from site_scanner.discover import FALLBACK_HOSTS, crt_hosts, live_discovery, tranco_hosts
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


def scan_host(host: str, *, bounty: set[str], pause_s: float = 0.5) -> dict:
    allowed = active_allowed(host, bounty)
    pages = fetch_host(host, active=allowed, pause_s=pause_s)
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
    parser.add_argument("--discover", action="store_true", help="Add passive hosts from CT logs, Tranco, and bounty scope.")
    parser.add_argument("--limit", type=int, default=4)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    sources = {"owned": 0, "bounty": 0, "certificate": 0, "tranco": 0}
    if args.discover:
        hosts, bounty, sources = live_discovery(limit=max(1, args.limit))
    else:
        bounty = {host_of(item) for item in args.bounty_hosts.split(",") if item.strip()}
        hosts = _hosts(args)
    reports = []
    for index, host in enumerate(hosts):
        if index:
            time.sleep(0.5)
        reports.append(scan_host(host, bounty=bounty))
    payload = {"status": "ok", "scanned": len(reports), "sources": sources, "reports": reports}
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        for report in reports:
            print("%s heat=%s mode=%s facts=%s" % (report["host"], report["heat"], report["mode"], ",".join(report["facts"])))


if __name__ == "__main__":
    main()
