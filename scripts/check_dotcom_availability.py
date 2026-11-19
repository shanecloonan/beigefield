#!/usr/bin/env python3
"""Check .com registration status for every first-word × second-word combo.

Availability is determined by RDAP (the domain registry's registration
database), not by DNS. A registered domain can have no DNS records, so a
failed lookup is never treated as "available".

    HTTP 404 from RDAP  →  AVAILABLE  (not in the .com registry)
    HTTP 200 with a record  →  TAKEN
    Network errors / rate-limit exhaustion / unexpected status  →  UNKNOWN

DNS is a sanity note only, queried over DNS-over-HTTPS (Cloudflare, then
Google) so a local stub or fake-ip resolver cannot spoof a "resolves"
result. Public DNS records never flip a domain from TAKEN to AVAILABLE.
A real discrepancy (RDAP 404 but public DNS has records) is marked
UNKNOWN so it is not silently treated as free.

Usage (from the repo root or this directory):

    python3 scripts/check_dotcom_availability.py

Optional flags:

    --delay 0.75          Seconds to wait between RDAP requests (default 0.75)
    --out scripts/dotcom-availability-results
                          Write <path>.json and <path>.csv
    --resume              Skip domains already present in the JSON output
    --recheck-unknown     With --resume, re-query rows previously marked UNKNOWN
    --limit N             Check only the first N combos (for a smoke test)

Edit FIRST_WORDS and SECOND_WORDS below to change the lists. Words are
lowercased and concatenated, then given a .com TLD, e.g. Blue + Whale
→ bluewhale.com.
"""

from __future__ import annotations

import argparse
import csv
import json
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Word lists — edit these to change the search space.
# ---------------------------------------------------------------------------

FIRST_WORDS = [
    "Blue",
    "Red",
    "Orange",
    "Purple",
    "Green",
    "Yellow",
    "Big",
    "Small",
    "Gold",
    "Silver",
    "Royal",
    "Smart",
]

SECOND_WORDS = [
    "Whale",
    "Monkey",
    "Bird",
    "Rabbit",
    "Coyote",
    "Fox",
    "Deer",
    "Buck",
    "Ape",
    "Parrot",
    "Frog",
    "Lion",
    "Tiger",
    "Elephant",
    "Dolphin",
    "Octopus",
    "Book",
    "Note",
    "Site",
    "Lottery",
    "Money",
    "Cash",
    "Bill",
    "Cloud",
    "Science",
    "Bio",
    "Biology",
    "Com",
    "Company",
    "Coin",
    "Chain",
    "Block",
]

# ---------------------------------------------------------------------------

USER_AGENT = (
    "beigefield-dotcom-check/1.0 "
    "(https://github.com/shanecloonan/beigefield; polite RDAP client)"
)
ACCEPT = "application/rdap+json, application/json"
VERISIGN_RDAP = "https://rdap.verisign.com/com/v1/domain/{domain}"
BOOTSTRAP_RDAP = "https://rdap.org/domain/{domain}"
DOH_ENDPOINTS = (
    "https://cloudflare-dns.com/dns-query?name={name}&type=A",
    "https://dns.google/resolve?name={name}&type=A",
)
REQUEST_TIMEOUT_S = 20
MAX_RETRIES = 5
STATUSES = ("AVAILABLE", "TAKEN", "UNKNOWN")


def combinations(first: list[str], second: list[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for a in first:
        for b in second:
            label = f"{a}{b}".lower()
            rows.append(
                {
                    "first": a,
                    "second": b,
                    "label": label,
                    "domain": f"{label}.com",
                }
            )
    return rows


def _http_get(url: str, accept: str = ACCEPT) -> tuple[int, bytes]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": accept},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
            return int(resp.status), resp.read()
    except urllib.error.HTTPError as exc:
        body = b""
        try:
            body = exc.read()
        except Exception:
            pass
        return int(exc.code), body


def _is_retryable(status: int | None, exc: BaseException | None) -> bool:
    if status in {429, 500, 502, 503, 504}:
        return True
    if exc is None:
        return False
    return isinstance(
        exc,
        (
            TimeoutError,
            socket.timeout,
            socket.gaierror,
            urllib.error.URLError,
            ConnectionError,
            OSError,
        ),
    )


def _backoff_sleep(attempt: int) -> None:
    # 1s, 2s, 4s, 8s, 16s — capped
    time.sleep(min(16.0, 2 ** (attempt - 1)))


def _parse_rdap_taken(body: bytes) -> dict[str, str]:
    info = {"registrar": "", "expires": "", "rdap_name": ""}
    try:
        data = json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return info
    if not isinstance(data, dict):
        return info
    info["rdap_name"] = str(data.get("ldhName") or data.get("unicodeName") or "")
    for event in data.get("events") or []:
        if not isinstance(event, dict):
            continue
        action = (event.get("eventAction") or "").lower()
        if action in {"expiration", "expiry"}:
            info["expires"] = str(event.get("eventDate") or "")
            break
    for entity in data.get("entities") or []:
        if not isinstance(entity, dict):
            continue
        roles = [str(r).lower() for r in (entity.get("roles") or [])]
        if "registrar" not in roles:
            continue
        # vcardArray is ["vcard", [[name, params, type, value], ...]]
        vcard = entity.get("vcardArray")
        if isinstance(vcard, list) and len(vcard) >= 2 and isinstance(vcard[1], list):
            for item in vcard[1]:
                if isinstance(item, list) and len(item) >= 4 and item[0] == "fn":
                    info["registrar"] = str(item[3] or "")
                    break
        if not info["registrar"]:
            info["registrar"] = str(entity.get("handle") or "")
        break
    return info


def rdap_lookup(domain: str) -> dict[str, Any]:
    """Query RDAP. Returns a result dict with status AVAILABLE/TAKEN/UNKNOWN."""
    urls = [VERISIGN_RDAP.format(domain=domain), BOOTSTRAP_RDAP.format(domain=domain)]
    last_error = ""
    for url in urls:
        for attempt in range(1, MAX_RETRIES + 1):
            status: int | None = None
            exc: BaseException | None = None
            body = b""
            try:
                status, body = _http_get(url)
            except Exception as err:  # noqa: BLE001 — must classify, not crash
                exc = err
                last_error = f"{type(err).__name__}: {err}"
                if attempt < MAX_RETRIES and _is_retryable(None, exc):
                    _backoff_sleep(attempt)
                    continue
                break

            if status == 404:
                return {
                    "status": "AVAILABLE",
                    "source": url,
                    "http_status": status,
                    "detail": "RDAP 404 — not in the .com registry",
                    "registrar": "",
                    "expires": "",
                }
            if status == 200:
                if not body.strip():
                    last_error = f"HTTP 200 with empty body from {url}"
                    break
                parsed = _parse_rdap_taken(body)
                return {
                    "status": "TAKEN",
                    "source": url,
                    "http_status": status,
                    "detail": "RDAP 200 — registered",
                    "registrar": parsed["registrar"],
                    "expires": parsed["expires"],
                }
            last_error = f"HTTP {status} from {url}"
            if attempt < MAX_RETRIES and _is_retryable(status, None):
                _backoff_sleep(attempt)
                continue
            # Non-retryable unexpected status: try the next endpoint.
            break
    return {
        "status": "UNKNOWN",
        "source": "",
        "http_status": None,
        "detail": last_error or "RDAP lookup failed",
        "registrar": "",
        "expires": "",
    }


def dns_resolves(domain: str) -> bool | None:
    """Public A-record check via DNS-over-HTTPS. Informational; not used as truth.

    Local getaddrinfo() is intentionally avoided: some environments (including
    this one) use a fake-ip stub that makes every name appear to resolve.
    """
    last_error = None
    for template in DOH_ENDPOINTS:
        url = template.format(name=urllib.parse.quote(domain, safe=""))
        try:
            status, body = _http_get(url, accept="application/dns-json, application/json")
        except Exception as err:  # noqa: BLE001
            last_error = err
            continue
        if status != 200 or not body.strip():
            continue
        try:
            data = json.loads(body.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        rcode = data.get("Status")
        answers = data.get("Answer") or []
        # 3 = NXDOMAIN. 0 = NOERROR (may still have no A records).
        if rcode == 3:
            return False
        if rcode == 0:
            has_a = any(
                isinstance(item, dict) and item.get("type") == 1 and item.get("data")
                for item in answers
            )
            return bool(has_a)
        # Other rcodes (SERVFAIL, REFUSED, …): try the next resolver.
        last_error = f"DoH Status={rcode}"
    if last_error is not None:
        return None
    return None


def load_existing(json_path: Path) -> dict[str, dict[str, Any]]:
    if not json_path.is_file():
        return {}
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        return {}
    by_domain: dict[str, dict[str, Any]] = {}
    for row in results:
        if isinstance(row, dict) and row.get("domain") and row.get("status") in STATUSES:
            by_domain[str(row["domain"])] = row
    return by_domain


def write_outputs(out_base: Path, payload: dict[str, Any]) -> None:
    out_base.parent.mkdir(parents=True, exist_ok=True)
    json_path = out_base.with_suffix(".json")
    csv_path = out_base.with_suffix(".csv")
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    fields = [
        "domain",
        "first",
        "second",
        "status",
        "http_status",
        "registrar",
        "expires",
        "dns_resolves",
        "detail",
        "source",
        "checked_at",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in payload["results"]:
            writer.writerow(row)


def _payload(
    started: datetime,
    delay: float,
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "checked_at": started.isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "delay_seconds": delay,
        "source_of_truth": "RDAP",
        "first_words": FIRST_WORDS,
        "second_words": SECOND_WORDS,
        "counts": {
            status: sum(1 for r in results if r["status"] == status)
            for status in STATUSES
        },
        "results": results,
    }


def print_report(results: list[dict[str, Any]], out_base: Path) -> None:
    buckets = {key: [] for key in STATUSES}
    for row in results:
        buckets.setdefault(row["status"], []).append(row["domain"])
    available = buckets.get("AVAILABLE", [])
    taken = buckets.get("TAKEN", [])
    unknown = buckets.get("UNKNOWN", [])
    total = len(results)

    def heading(title: str) -> None:
        print()
        print(title)
        print("-" * len(title))

    heading("AVAILABLE (not registered)")
    if available:
        for name in available:
            print(f"  {name}")
    else:
        print("  (none)")

    heading("UNKNOWN (could not determine — do not treat as available)")
    if unknown:
        for name in unknown:
            detail = next(
                (r.get("detail") or "" for r in results if r["domain"] == name),
                "",
            )
            suffix = f"  — {detail}" if detail else ""
            print(f"  {name}{suffix}")
    else:
        print("  (none)")

    heading("TAKEN (registered)")
    if taken:
        for name in taken:
            row = next(r for r in results if r["domain"] == name)
            extra_bits = []
            if row.get("registrar"):
                extra_bits.append(str(row["registrar"]))
            if row.get("expires"):
                extra_bits.append(f"expires {row['expires']}")
            extra = f"  ({'; '.join(extra_bits)})" if extra_bits else ""
            print(f"  {name}{extra}")
    else:
        print("  (none)")

    heading("Summary")
    print(f"  Total checked: {total}")
    print(f"  Available:     {len(available)}")
    print(f"  Taken:         {len(taken)}")
    print(f"  Unknown:       {len(unknown)}")
    print(f"  Results:       {out_base.with_suffix('.json')}")
    print(f"                 {out_base.with_suffix('.csv')}")
    print()
    print(
        "RDAP is the source of truth. DNS is recorded only as a sanity note "
        "and is never used to mark a domain available."
    )


def parse_args() -> argparse.Namespace:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description="Check .com availability for first-word × second-word combos via RDAP."
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.75,
        help="Seconds to wait between RDAP requests (default: 0.75)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=here / "dotcom-availability-results",
        help="Output path prefix (writes .json and .csv)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip domains already present in the existing JSON output",
    )
    parser.add_argument(
        "--recheck-unknown",
        action="store_true",
        help="With --resume, re-query domains previously marked UNKNOWN",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Check only the first N combos (0 = all)",
    )
    parser.add_argument(
        "--no-dns",
        action="store_true",
        help="Skip the informational DNS-over-HTTPS sanity lookup",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.delay < 0:
        print("--delay must be >= 0", file=sys.stderr)
        return 2

    combos = combinations(FIRST_WORDS, SECOND_WORDS)
    if args.limit and args.limit > 0:
        combos = combos[: args.limit]

    out_base = args.out
    if out_base.suffix in {".json", ".csv"}:
        out_base = out_base.with_suffix("")

    existing = load_existing(out_base.with_suffix(".json")) if args.resume else {}
    # Keep already-known rows so a mid-run interrupt cannot shrink the file.
    known: dict[str, dict[str, Any]] = dict(existing)
    started = datetime.now(timezone.utc)

    def should_skip(domain: str) -> bool:
        if domain not in existing:
            return False
        if args.recheck_unknown and existing[domain].get("status") == "UNKNOWN":
            return False
        return True

    skip_count = sum(1 for c in combos if should_skip(c["domain"]))
    print(
        f"Checking {len(combos)} .com domains "
        f"({len(FIRST_WORDS)} × {len(SECOND_WORDS)}) via RDAP. "
        f"Delay={args.delay}s. Resume skipped={skip_count}."
    )
    sys.stdout.flush()

    def ordered_results() -> list[dict[str, Any]]:
        return [known[c["domain"]] for c in combos if c["domain"] in known]

    for index, combo in enumerate(combos, start=1):
        domain = combo["domain"]
        if should_skip(domain):
            print(f"[{index}/{len(combos)}] {domain}: {known[domain]['status']} (cached)")
            sys.stdout.flush()
            continue

        rdap = rdap_lookup(domain)
        if args.no_dns:
            dns: bool | None | str = ""
        else:
            dns = dns_resolves(domain)

        note = rdap["detail"]
        # Public-DNS discrepancy only. Never flip TAKEN→AVAILABLE on DNS, and
        # never trust a local stub that makes every name appear to resolve.
        if rdap["status"] == "AVAILABLE" and dns is True:
            rdap["status"] = "UNKNOWN"
            note = (
                "RDAP 404 (not in registry) but public DNS has an A record "
                "— marked UNKNOWN, not available"
            )
        elif rdap["status"] == "TAKEN" and dns is False:
            note = "RDAP 200 (registered) but public DNS has no A record — still TAKEN"
        elif rdap["status"] == "AVAILABLE" and dns is False:
            note = "RDAP 404 — not in the .com registry; public DNS is NXDOMAIN / no A"

        row = {
            "domain": domain,
            "first": combo["first"],
            "second": combo["second"],
            "status": rdap["status"],
            "http_status": rdap["http_status"],
            "registrar": rdap["registrar"],
            "expires": rdap["expires"],
            "dns_resolves": dns if dns != "" else "",
            "detail": note,
            "source": rdap["source"],
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        known[domain] = row
        print(f"[{index}/{len(combos)}] {domain}: {row['status']}")
        sys.stdout.flush()

        write_outputs(out_base, _payload(started, args.delay, ordered_results()))
        if index < len(combos):
            time.sleep(args.delay)

    results = ordered_results()
    write_outputs(out_base, _payload(started, args.delay, results))
    print_report(results, out_base)
    counts = {status: sum(1 for r in results if r["status"] == status) for status in STATUSES}
    return 0 if counts["UNKNOWN"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
