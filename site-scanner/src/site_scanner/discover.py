"""Pick hosts from public lists. The caller still rate-limits the scan."""

from __future__ import annotations

import json
import random
import time
import urllib.request
from typing import Iterable

from site_scanner.allow import host_of

# Hosts the scheduled job always includes. Active checks stay on the allowlist.
SCHEDULED_OWNED = (
    "beigefield.vercel.app",
    "dap-ashy.vercel.app",
)
_SKIP_SUFFIX = (".local", ".internal", ".localhost", ".invalid")

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


def usable_host(value: str) -> str:
    """A public website hostname. Wildcards, paths, and local names are dropped."""
    text = (value or "").strip()
    if text.lower().startswith("*."):
        text = text[2:]
    host = host_of(text)
    if not host or "." not in host or len(host) > 253:
        return ""
    if any(ch in host for ch in " *?/\\"):
        return ""
    if host.endswith(_SKIP_SUFFIX):
        return ""
    labels = host.split(".")
    if any(not label or len(label) > 63 for label in labels):
        return ""
    return host


def parse_bounty(programs: object, *, limit: int = 20) -> list[str]:
    """In-scope website hosts from a bounty-targets-data style document.

    A host listed out of scope by any program is dropped.
    """
    blocked: set[str] = set()
    candidates: list[str] = []
    rows = programs if isinstance(programs, list) else []
    for program in rows:
        if not isinstance(program, dict):
            continue
        targets = program.get("targets") if isinstance(program.get("targets"), dict) else {}
        for row in targets.get("out_of_scope") or []:
            if isinstance(row, dict):
                name = usable_host(str(row.get("asset_identifier") or ""))
                if name:
                    blocked.add(name)
        for row in targets.get("in_scope") or []:
            if not isinstance(row, dict):
                continue
            if row.get("eligible_for_submission") is False:
                continue
            kind = str(row.get("asset_type") or "").lower()
            if kind and "url" not in kind and "domain" not in kind and "website" not in kind:
                continue
            name = usable_host(str(row.get("asset_identifier") or ""))
            if name:
                candidates.append(name)
    hosts: list[str] = []
    for host in candidates:
        if host in blocked or host in hosts:
            continue
        hosts.append(host)
        if len(hosts) >= limit:
            break
    return hosts


def hosts_from_certstream(message: object) -> list[str]:
    """Domain names from one certstream certificate_update message."""
    if not isinstance(message, dict):
        return []
    data = message.get("data") if isinstance(message.get("data"), dict) else {}
    leaf = data.get("leaf_cert") if isinstance(data.get("leaf_cert"), dict) else {}
    names = leaf.get("all_domains") if isinstance(leaf.get("all_domains"), list) else []
    found: list[str] = []
    for name in names:
        host = usable_host(str(name))
        if host and host not in found:
            found.append(host)
    return found


def sample_tranco_lines(raw: str, *, limit: int, start_rank: int = 500, rng: random.Random | None = None) -> list[str]:
    """A random slice of a Tranco CSV, starting after the very top ranks."""
    hosts: list[str] = []
    seen: set[str] = set()
    for line in (raw or "").splitlines():
        parts = line.split(",")
        if len(parts) < 2:
            continue
        try:
            rank = int(parts[0].strip())
        except ValueError:
            continue
        if rank < start_rank:
            continue
        host = usable_host(parts[1])
        if not host or host in seen:
            continue
        seen.add(host)
        hosts.append(host)
    picker = rng or random.Random()
    if len(hosts) <= limit:
        return hosts
    return picker.sample(hosts, limit)


def mix_hosts(
    *,
    owned: Iterable[str],
    bounty: Iterable[str],
    crt: Iterable[str],
    tranco: Iterable[str],
    limit: int,
) -> list[str]:
    """Owned hosts first, then bounty, certificate-log, and Tranco names. Deduped."""
    ordered: list[str] = []
    for group in (owned, bounty, crt, tranco):
        for item in group:
            host = usable_host(item)
            if not host or host in ordered:
                continue
            ordered.append(host)
            if len(ordered) >= limit:
                return ordered
    return ordered


def _read(url: str, *, limit: int, timeout: float) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "beigefield-site-scanner/0.1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(limit)


def certstream_hosts(*, limit: int = 4, seconds: float = 6) -> list[str]:
    """A few names from the public certstream feed. Empty when it does not answer."""
    try:
        from websocket import create_connection
    except ImportError:
        return []
    found: list[str] = []
    ws = None
    try:
        ws = create_connection("wss://certstream.calidog.io/", timeout=8)
        ws.settimeout(2)
        deadline = time.time() + seconds
        while time.time() < deadline and len(found) < limit:
            try:
                raw = ws.recv()
            except Exception:
                break
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue
            for host in hosts_from_certstream(message):
                if host not in found:
                    found.append(host)
                if len(found) >= limit:
                    break
    except Exception:
        return found
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
    return found


def fetch_bounty_hosts(*, limit: int = 40) -> list[str]:
    """In-scope hosts from the public bounty-targets-data file. Empty on failure."""
    url = "https://raw.githubusercontent.com/arkadiyt/bounty-targets-data/master/data/hackerone_data.json"
    try:
        raw = _read(url, limit=20_000_000, timeout=30)
        programs = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:
        return []
    return parse_bounty(programs, limit=limit)


def fetch_tranco_sample(*, limit: int = 4, rng: random.Random | None = None) -> list[str]:
    """Random hosts from the latest Tranco list. Empty when the list does not answer."""
    try:
        meta = json.loads(_read("https://tranco-list.eu/api/lists/date/latest", limit=20_000, timeout=15).decode("utf-8", errors="replace"))
        download = str(meta.get("download") or "")
        if not download.startswith("https://tranco-list.eu/"):
            return []
        raw = _read(download, limit=400_000, timeout=20).decode("utf-8", errors="replace")
    except Exception:
        return []
    return sample_tranco_lines(raw, limit=limit, rng=rng)


def tranco_hosts(*, limit: int = 10) -> list[str]:
    """The top of the latest Tranco list. Empty when the list does not answer."""
    try:
        meta = json.loads(_read("https://tranco-list.eu/api/lists/date/latest", limit=20_000, timeout=15).decode("utf-8", errors="replace"))
        download = str(meta.get("download") or "")
        if not download.startswith("https://tranco-list.eu/"):
            return []
        raw = _read(download, limit=80_000, timeout=20).decode("utf-8", errors="replace")
    except Exception:
        return []
    return parse_tranco(raw, limit=limit)


def source_counts(
    hosts: Iterable[str],
    *,
    owned: Iterable[str],
    bounty: Iterable[str],
    crt: Iterable[str],
    tranco: Iterable[str],
) -> dict[str, int]:
    """Count each chosen host once, in source priority order."""
    counts = {"owned": 0, "bounty": 0, "certificate": 0, "tranco": 0}
    owned_set = {usable_host(item) for item in owned}
    bounty_set = {usable_host(item) for item in bounty}
    crt_set = {usable_host(item) for item in crt}
    tranco_set = {usable_host(item) for item in tranco}
    for host in hosts:
        if host in owned_set:
            counts["owned"] += 1
        elif host in bounty_set:
            counts["bounty"] += 1
        elif host in crt_set:
            counts["certificate"] += 1
        elif host in tranco_set:
            counts["tranco"] += 1
    return counts


def live_discovery(*, limit: int = 8, rng: random.Random | None = None) -> tuple[list[str], set[str], dict[str, int]]:
    """Owned hosts plus a small passive sample. Bounty hosts are returned for the active gate."""
    picker = rng or random.Random()
    bounty_all = fetch_bounty_hosts(limit=80)
    if len(bounty_all) <= 2:
        bounty_pick = list(bounty_all)
    else:
        bounty_pick = picker.sample(bounty_all, 2)
    stream = certstream_hosts(limit=3, seconds=6)
    logged = list(stream)
    if len(logged) < 2:
        for host in crt_hosts("com", limit=3):
            if host not in logged:
                logged.append(host)
    sampled = fetch_tranco_sample(limit=3, rng=picker)
    hosts = mix_hosts(
        owned=SCHEDULED_OWNED,
        bounty=bounty_pick,
        crt=logged[:3],
        tranco=sampled,
        limit=limit,
    )
    if len(hosts) < limit:
        sampled = sampled + fetch_tranco_sample(limit=limit, rng=picker)
        hosts = mix_hosts(
            owned=SCHEDULED_OWNED,
            bounty=bounty_pick,
            crt=logged[:3],
            tranco=sampled,
            limit=limit,
        )
    counts = source_counts(hosts, owned=SCHEDULED_OWNED, bounty=bounty_pick, crt=logged, tranco=sampled)
    return hosts, set(bounty_all), counts
