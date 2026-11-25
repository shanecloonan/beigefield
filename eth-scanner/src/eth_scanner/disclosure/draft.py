"""Write a disclosure draft and record public contact pages.

Triage is one of unreviewed, reviewing, fp, or credible. A security.txt
file is read with GET when a lookup is asked for. Immunefi, Cantina, and
SEAL 911 are public URLs. Nothing is mailed or messaged.
Heat stays 0.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Optional

STATUSES = ("unreviewed", "reviewing", "fp", "credible")
SEAL_911_URL = "https://www.securityalliance.org/seal-911"
_ADDR = re.compile(r"^0x[a-f0-9]{40}$")
_HOST = re.compile(
    r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$"
)
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_UNSAFE = re.compile(r"\b(exploit|attack|calldata|drain|steal)\b|0x[0-9a-fA-F]{8,}", re.I)
_REFUSED_HOSTS = {"localhost", "localhost.localdomain"}

Fetch = Callable[[str], tuple[int, str]]


def normalize_status(value: str) -> str:
    token = (value or "").strip().lower()
    if token == "false-positive":
        token = "fp"
    return token if token in STATUSES else ""


def _host(domain: str) -> str:
    host = (domain or "").strip().lower().rstrip(".")
    if "://" in host or "/" in host or "@" in host or ":" in host:
        return ""
    if not _HOST.match(host):
        return ""
    if host in _REFUSED_HOSTS or host.endswith(".local") or host.endswith(".internal"):
        return ""
    return host


def _slug(value: str) -> str:
    token = (value or "").strip().lower()
    return token if _SLUG.match(token) else ""


def https_get(url: str) -> tuple[int, str]:
    """Read one public https URL. The method is GET."""
    import urllib.request

    if not url.startswith("https://"):
        raise ValueError("lookup is an https GET")
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=8) as response:
        raw = response.read(65536)
        code = int(getattr(response, "status", None) or getattr(response, "code", None) or 0)
    return code, raw.decode("utf-8", errors="replace")


def security_txt_urls(domain: str) -> list[str]:
    host = _host(domain)
    if not host:
        return []
    return [
        "https://%s/.well-known/security.txt" % host,
        "https://%s/security.txt" % host,
    ]


def listing_urls(slug: str) -> dict[str, str]:
    """Public program pages. Recorded on the draft and not fetched."""
    token = _slug(slug)
    urls = {"seal_911": SEAL_911_URL}
    if token:
        urls["immunefi"] = "https://immunefi.com/bug-bounty/%s/" % token
        urls["cantina"] = "https://cantina.xyz/bounties/%s" % token
    return urls


def _contacts(body: str) -> list[str]:
    found: list[str] = []
    for line in (body or "").splitlines():
        if not line.lower().startswith("contact:"):
            continue
        value = line.split(":", 1)[1].strip()
        if value and len(value) <= 200 and "\n" not in value:
            found.append(value)
        if len(found) >= 8:
            break
    return found


def _read_security_txt(domain: str, fetch: Fetch) -> dict[str, Any]:
    contacts: list[str] = []
    reads: list[dict[str, Any]] = []
    for url in security_txt_urls(domain):
        if not url.startswith("https://"):
            continue
        try:
            status, body = fetch(url)
        except Exception:
            reads.append({"url": url, "status": 0})
            continue
        code = int(status or 0)
        reads.append({"url": url, "status": code})
        if code == 200:
            contacts.extend(_contacts(body))
    return {"reads": reads, "contacts": contacts[:8]}


def draft_disclosure(
    *,
    address: str = "",
    domain: str = "",
    slug: str = "",
    status: str = "unreviewed",
    note: str = "",
    lookup: bool = False,
    fetch: Optional[Fetch] = None,
    dest: Optional[Path] = None,
) -> dict[str, Any]:
    """Write a draft. ``lookup`` may GET security.txt and does nothing else."""
    triage = normalize_status(status)
    target = (address or "").strip().lower()
    report: dict[str, Any] = {
        "status": "skipped",
        "address": target,
        "triage": triage,
        "sent": False,
        "disclosure": False,
        "contacts": [],
        "urls": {},
        "reads": [],
        "heat_contribution": 0,
        "note": "",
    }
    if not triage:
        report["status"] = "refused"
        report["note"] = "Triage must be unreviewed, reviewing, fp, or credible. Nothing was sent."
        return report
    if target and not _ADDR.match(target):
        report["status"] = "refused"
        report["note"] = "The address is not a 20-byte hex address. Nothing was sent."
        return report
    text = (note or "").strip()
    if text and (_UNSAFE.search(text) or len(text) > 240):
        report["status"] = "refused"
        report["note"] = "The note was refused. Nothing was sent."
        return report
    host = _host(domain) if domain else ""
    if domain and not host:
        report["status"] = "refused"
        report["note"] = "The domain is not a public host. Nothing was sent."
        return report
    urls = listing_urls(slug)
    if host:
        urls["security_txt"] = security_txt_urls(host)[0]
    report["urls"] = urls
    if lookup and host:
        if fetch is None:
            report["status"] = "skipped"
            report["note"] = "Lookup needs a GET client. Nothing was contacted and nothing was sent."
            return report
        found = _read_security_txt(host, fetch)
        report["reads"] = found["reads"]
        report["contacts"] = found["contacts"]
    report["sent"] = False
    report["disclosure"] = True
    report["heat_contribution"] = 0
    if dest is not None:
        report["files"] = _write(dest, report, text)
    report["status"] = "ok"
    report["note"] = "Draft only. Not sent. Heat stays 0."
    return report


def _write(dest: Path, report: dict[str, Any], note: str) -> list[str]:
    dest.mkdir(parents=True, exist_ok=True)
    payload = {
        "address": report["address"],
        "triage": report["triage"],
        "sent": False,
        "contacts": report["contacts"],
        "urls": report["urls"],
        "reads": [{"url": row["url"], "status": row["status"]} for row in report["reads"]],
        "heat_contribution": 0,
        "note": "Draft only. Not sent.",
    }
    (dest / "disclosure.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Disclosure draft",
        "",
        "Status: %s" % report["triage"],
        "Address: %s" % (report["address"] or "unset"),
        "Sent: no",
        "",
        "This file is a draft. It was not emailed or submitted.",
        "Not sent.",
        "",
        "## Public contacts",
        "",
    ]
    for name, url in report["urls"].items():
        lines.append("- %s: %s" % (name, url))
    for contact in report["contacts"]:
        lines.append("- security.txt contact: %s" % contact)
    if note:
        lines.extend(["", "## Note", "", note])
    lines.extend(["", "Heat stays 0.", ""])
    (dest / "disclosure.md").write_text("\n".join(lines), encoding="utf-8")
    return ["disclosure.json", "disclosure.md"]


def public_report(report: dict[str, Any]) -> dict[str, Any]:
    """Fields safe to print. The draft was not sent."""
    triage = report.get("triage") if report.get("disclosure") else ""
    return {
        "status": report.get("status"),
        "address": report.get("address"),
        "triage": report.get("triage"),
        "sent": False,
        "contacts": list(report.get("contacts") or []),
        "urls": dict(report.get("urls") or {}),
        "disclosure": bool(report.get("disclosure")),
        "heat": 0,
        "heat_breakdown": {
            "disclosure": bool(report.get("disclosure")),
            "disclosure_status": triage or "",
        },
        "note": report.get("note"),
    }
