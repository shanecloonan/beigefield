"""Scan a few hosts and print a redacted report."""

from __future__ import annotations

import argparse
import asyncio
import json

from site_scanner.allow import active_allowed, host_of
from site_scanner.analyze import report_for
from site_scanner.cloud import annotate_cloud
from site_scanner.discover import FALLBACK_HOSTS, crt_hosts, live_discovery, take_batch, tranco_hosts
from site_scanner.fetch import fetch_host_async
from site_scanner.store import load_cursor, save_cursor, save_hit


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


def scan_host(host: str, *, bounty: set[str], pause_s: float = 0.35) -> dict:
    return asyncio.run(scan_host_async(host, bounty=bounty, pause_s=pause_s))


async def scan_host_async(host: str, *, bounty: set[str], pause_s: float = 0.35) -> dict:
    allowed = active_allowed(host, bounty)
    pages = await fetch_host_async(host, active=allowed, pause_s=pause_s)
    annotate_cloud(pages)
    report = report_for(host, pages, active_ran=allowed)
    report["persist"] = save_hit(report)
    return report


async def scan_hosts(hosts: list[str], bounty: set[str], *, pause_s: float = 0.35, concurrency: int = 2) -> list[dict]:
    """At most `concurrency` hosts at once. Each host still waits between its own requests."""
    gate = asyncio.Semaphore(max(1, concurrency))

    async def one(host: str) -> dict:
        async with gate:
            return await scan_host_async(host, bounty=bounty, pause_s=pause_s)

    return list(await asyncio.gather(*(one(host) for host in hosts)))


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
    cursor_note: dict = {"status": "unused"}
    if args.discover:
        batch = max(1, args.limit)
        pool, bounty, sources = live_discovery(limit=max(batch * 8, 24))
        state = load_cursor()
        hosts, seen_next, wrapped = take_batch(pool, list(state.get("seen") or []), batch)
        cycle = int(state.get("cycle") or 0) + (1 if wrapped else 0)
        cursor_note = {
            "status": "pending",
            "cycle": cycle,
            "wrapped": wrapped,
            "batch": len(hosts),
            "pool": len(pool),
            "_seen": seen_next,
        }
    else:
        bounty = {host_of(item) for item in args.bounty_hosts.split(",") if item.strip()}
        hosts = _hosts(args)
    reports = asyncio.run(scan_hosts(hosts, bounty))
    if cursor_note.get("status") == "pending":
        saved = save_cursor(list(cursor_note.pop("_seen") or []), int(cursor_note.get("cycle") or 0))
        cursor_note["status"] = saved.get("status")
    payload = {
        "status": "ok",
        "scanned": len(reports),
        "sources": sources,
        "cursor": cursor_note,
        "reports": reports,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        for report in reports:
            print("%s heat=%s mode=%s facts=%s" % (report["host"], report["heat"], report["mode"], ",".join(report["facts"])))


if __name__ == "__main__":
    main()
