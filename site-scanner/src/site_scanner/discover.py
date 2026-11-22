"""Pick hosts from public lists. The caller still rate-limits the scan."""

from __future__ import annotations

import json
import urllib.request

from site_scanner.allow import host_of

# A short public sample used when the live lists do not answer.
FALLBACK_HOSTS = (
    "beigefield.vercel.app",
    "example.com",
)


def parse_crt(rows: object, *, limit: int = 10) -> list[str]:
    found: list[str] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("common_name") or row.get("name_value") or "").split("\n", 1)[0].strip().lower()
        if name.startswith("*."):
            name = name[2:]
        if name and name not in found and "." in name:
            found.append(name)
        if len(found) >= limit:
            break
    return found


def parse_tranco(raw: str, *, limit: int = 10) -> list[str]:
    hosts: list[str] = []
    for line in (raw or "").splitlines():
        parts = line.split(",")
        if len(parts) < 2:
            continue
        host = parts[1].strip().lower()
        if host and host not in hosts:
            hosts.append(host)
        if len(hosts) >= limit:
            break
    return hosts


def crt_hosts(query: str, *, limit: int = 10) -> list[str]:
    """Names from crt.sh JSON. Empty when the service does not answer."""
    url = "https://crt.sh/?q=%s&output=json" % urllib.request.quote(query)
    try:
        with urllib.request.urlopen(url, timeout=12) as response:
            raw = response.read(500_000).decode("utf-8", errors="replace")
        rows = json.loads(raw)
    except Exception:
        return []
    return parse_crt(rows, limit=limit)


def parse_bounty(programs: object, *, limit: int = 20) -> list[str]:
    """In-scope website hosts from a bounty-targets-data style document.

    Out-of-scope identifiers are dropped. The default job does not scan these.
    """
    hosts: list[str] = []
    rows = programs if isinstance(programs, list) else []
    for program in rows:
        if not isinstance(program, dict):
            continue
        targets = program.get("targets") if isinstance(program.get("targets"), dict) else {}
        blocked = set()
        for row in targets.get("out_of_scope") or []:
            if isinstance(row, dict):
                blocked.add(host_of(str(row.get("asset_identifier") or "")))
        for row in targets.get("in_scope") or []:
            if not isinstance(row, dict):
                continue
            if row.get("eligible_for_submission") is False:
                continue
            kind = str(row.get("asset_type") or "").lower()
            if kind and "url" not in kind and "domain" not in kind and "website" not in kind:
                continue
            host = host_of(str(row.get("asset_identifier") or ""))
            if not host or host in blocked or host in hosts:
                continue
            hosts.append(host)
            if len(hosts) >= limit:
                return hosts
    return hosts


def tranco_hosts(*, limit: int = 10) -> list[str]:
    """The top of the Tranco list. Empty when the download does not answer."""
    url = "https://tranco-list.eu/download/daily/top-1m.csv"
    try:
        with urllib.request.urlopen(url, timeout=12) as response:
            raw = response.read(80_000).decode("utf-8", errors="replace")
    except Exception:
        return []
    return parse_tranco(raw, limit=limit)
