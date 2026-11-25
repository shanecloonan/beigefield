"""Pick hosts from public lists. The caller still rate-limits the scan."""

from __future__ import annotations

import base64
import json
import random
import re
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Iterable

from site_scanner.allow import host_of
from site_scanner.fetch import USER_AGENT

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
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(limit)


def _stamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def names_from_crt_rows(rows: object, *, now: datetime, hours: int = 1, limit: int = 10) -> list[str]:
    """Names from a crt.sh JSON page. Prefer the last hour, otherwise the rows that answered."""
    fresh: list[str] = []
    older: list[str] = []
    cutoff = now - timedelta(hours=hours)
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        host = usable_host(str(row.get("common_name") or row.get("name_value") or ""))
        if not host:
            continue
        stamp = _stamp(row.get("entry_timestamp") or row.get("not_before"))
        bucket = fresh if stamp is not None and stamp >= cutoff else older
        if host not in bucket and host not in fresh:
            bucket.append(host)
    pool = fresh or older
    return pool[:limit]


_INFRA_PREFIX = ("crl.", "ocsp.", "ocsp-", "crt.")
_INFRA_SUFFIX = (".amazontrust.com", ".pki.goog", ".crl", ".cer")
_HOST_IN_CERT = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,62}\.)+)(?:[a-z]{2,})", re.I)


def hosts_from_san(text: str) -> list[str]:
    found: list[str] = []
    for part in (text or "").replace(",", "\n").splitlines():
        piece = part.strip()
        if piece.upper().startswith("DNS:"):
            piece = piece[4:]
        host = _public_site(piece)
        if host and host not in found:
            found.append(host)
    return found


def _public_site(value: str) -> str:
    host = usable_host(value)
    if not host or host.startswith(_INFRA_PREFIX) or host.endswith(_INFRA_SUFFIX):
        return ""
    labels = host.split(".")
    if labels[-1] in {"crt", "crl", "cer"}:
        return ""
    if labels[0].startswith(("crl", "ocsp")) or labels[0] in {"cacerts", "crt"}:
        return ""
    if any(token in host for token in ("acm-acme", "dns-fw", ".ops.prod.")):
        return ""
    return host


def hosts_from_leaf(leaf: bytes) -> list[str]:
    """DNS names embedded in a CT leaf. Works for certificates and precertificates."""
    text = leaf.decode("latin-1", errors="ignore")
    found: list[str] = []
    for match in _HOST_IN_CERT.finditer(text):
        host = _public_site(match.group(0))
        if host and host not in found:
            found.append(host)
    return found


def _crt_json(query: str) -> list[object]:
    url = "https://crt.sh/?q=%s&exclude=expired&output=json" % urllib.request.quote(query, safe="")
    try:
        raw = _read(url, limit=400_000, timeout=8)
        rows = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:
        return []
    return rows if isinstance(rows, list) else []


def _log_entries(base: str, start: int, end: int) -> list[dict]:
    raw = _read("%sget-entries?start=%s&end=%s" % (base, start, end), limit=3_000_000, timeout=20)
    data = json.loads(raw.decode("utf-8", errors="replace"))
    rows = data.get("entries") if isinstance(data, dict) else []
    return [row for row in rows or [] if isinstance(row, dict)]


def ct_log_hosts(*, limit: int = 10) -> list[str]:
    """Recent names from the tail of a public CT log. Empty when the log does not answer."""
    base = "https://ct.googleapis.com/logs/us1/argon2026h2/ct/v1/"
    try:
        sth = json.loads(_read(base + "get-sth", limit=8_000, timeout=12).decode("utf-8", errors="replace"))
        end = int(sth.get("tree_size") or 0) - 1
    except Exception:
        return []
    found: list[str] = []
    for _page in range(8):
        if end < 0 or len(found) >= limit:
            break
        start = max(0, end - 31)
        try:
            entries = _log_entries(base, start, end)
        except Exception:
            break
        for entry in entries:
            try:
                leaf = base64.b64decode(str(entry.get("leaf_input") or ""))
            except Exception:
                continue
            for host in hosts_from_leaf(leaf):
                if host not in found:
                    found.append(host)
                if len(found) >= limit:
                    return found
        if start == 0:
            break
        end = start - 1
    return found


def recent_certificate_hosts(*, limit: int = 10) -> list[str]:
    """crt.sh JSON for a wildcard, then the public CT log when crt.sh does not answer."""
    found: list[str] = []
    now = datetime.now(timezone.utc)
    for query in ("%.app", "%.dev"):
        for host in names_from_crt_rows(_crt_json(query), now=now, hours=1, limit=limit):
            if host not in found:
                found.append(host)
        if len(found) >= limit:
            return found[:limit]
    for host in ct_log_hosts(limit=limit):
        if host not in found:
            found.append(host)
        if len(found) >= limit:
            break
    if len(found) < 4:
        for host in certstream_hosts(limit=limit, seconds=4):
            if host not in found:
                found.append(host)
            if len(found) >= limit:
                break
    return found[:limit]


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


def take_batch(pool: list[str], seen: list[str], limit: int) -> tuple[list[str], list[str], bool]:
    """The next hosts in a pool, skipping ones this cycle already scanned.

    When the unseen remainder is shorter than the batch, the cycle wraps.
    The returned seen list is only the new batch, so the following run
    continues through the rest of the pool instead of repeating this one.
    """
    size = max(0, int(limit))
    ordered = [host for host in pool if host]
    if size == 0 or not ordered:
        return [], list(seen), False
    seen_set = set(seen)
    fresh = [host for host in ordered if host not in seen_set]
    if len(fresh) >= size:
        chosen = fresh[:size]
        return chosen, list(seen) + chosen, False
    chosen = list(fresh)
    for host in ordered:
        if host in chosen:
            continue
        chosen.append(host)
        if len(chosen) >= size:
            break
    return chosen[:size], chosen[:size], True


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


def live_discovery(*, limit: int = 24, rng: random.Random | None = None) -> tuple[list[str], set[str], dict[str, int]]:
    """Owned hosts plus a small passive sample. Bounty hosts are returned for the active gate."""
    picker = rng or random.Random()
    bounty_all = fetch_bounty_hosts(limit=80)
    bounty_n = min(6, max(2, limit // 4))
    if len(bounty_all) <= bounty_n:
        bounty_pick = list(bounty_all)
    else:
        bounty_pick = picker.sample(bounty_all, bounty_n)
    logged = recent_certificate_hosts(limit=min(10, max(4, limit // 2)))
    sampled = fetch_tranco_sample(limit=min(10, max(4, limit // 3)), rng=picker)
    hosts = mix_hosts(
        owned=SCHEDULED_OWNED,
        bounty=bounty_pick,
        crt=logged,
        tranco=sampled,
        limit=limit,
    )
    if len(hosts) < limit:
        sampled = sampled + fetch_tranco_sample(limit=limit, rng=picker)
        hosts = mix_hosts(
            owned=SCHEDULED_OWNED,
            bounty=bounty_pick,
            crt=logged,
            tranco=sampled,
            limit=limit,
        )
    counts = source_counts(hosts, owned=SCHEDULED_OWNED, bounty=bounty_pick, crt=logged, tranco=sampled)
    return hosts, set(bounty_all), counts
