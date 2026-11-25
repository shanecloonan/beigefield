"""Score pages that were already fetched. This module does not open sockets."""

from __future__ import annotations

import re
from typing import Any

from site_scanner.heat import score_facts
from site_scanner.redact import redact

_OLD_LIBS = (
    ("jquery-1.", "jquery 1.x"),
    ("jquery/1.", "jquery 1.x"),
    ("angular.js/1.2", "angularjs 1.2"),
    ("lodash@4.17.15", "lodash 4.17.15"),
)
_DANGLING = (
    "there isn't a github pages site here",
    "no such app",
    "the specified bucket does not exist",
    "project not found",
)
_SUPABASE = re.compile(r"https://([a-z0-9]{8,})\.supabase\.co", re.I)
_FIREBASE = re.compile(r"https://([a-z0-9-]{4,})\.firebaseio\.com", re.I)


def _header(headers: dict[str, str], name: str) -> str:
    for key, value in (headers or {}).items():
        if key.lower() == name.lower():
            return value or ""
    return ""


def facts_for_page(page: dict[str, Any]) -> list[str]:
    """One page: url, status, headers, body. Body must already be redacted by the caller if stored."""
    facts: list[str] = []
    if page.get("challenged"):
        return ["challenged"]
    if page.get("skipped") == "robots":
        return []
    status = int(page.get("status") or 0)
    headers = page.get("headers") if isinstance(page.get("headers"), dict) else {}
    body = str(page.get("body") or "")
    path = str(page.get("path") or "/")
    lowered = body.lower()

    if path in {"/", ""} and status:
        if not _header(headers, "content-security-policy"):
            facts.append("missing-csp")
        if str(page.get("scheme") or "https") == "https" and not _header(headers, "strict-transport-security"):
            facts.append("missing-hsts")
        origin = _header(headers, "access-control-allow-origin").strip()
        creds = _header(headers, "access-control-allow-credentials").strip().lower()
        if origin == "*" and creds == "true":
            facts.append("cors-credentials-star")

    if page.get("tls_expired"):
        facts.append("tls-expired")
    elif page.get("tls_soon"):
        facts.append("tls-soon")

    if path == "/.env" and status == 200 and re.search(r"(?i)(secret|password|api[_-]?key)\s*=", body):
        facts.append("exposed-env")
    if path == "/.git/HEAD" and status == 200 and lowered.startswith("ref: refs/"):
        facts.append("exposed-git")
    if status == 200 and ("<title>index of" in lowered or "directory listing for" in lowered):
        facts.append("open-directory")
    if path.startswith("/admin") and status == 200 and any(tok in lowered for tok in ("dashboard", "admin panel", "wp-admin")):
        facts.append("open-admin")

    _redacted, kinds = redact(str(page.get("raw_body") or body))
    if kinds:
        facts.append("secret-in-page")

    if any(token in lowered for token in (old for old, _name in _OLD_LIBS)):
        facts.append("old-library")
    if any(phrase in lowered for phrase in _DANGLING):
        facts.append("dangling-host")
    if page.get("supabase_schema_open"):
        facts.append("supabase-schema-open")
    if page.get("firebase_root_open"):
        facts.append("firebase-root-open")
    return facts


def cloud_hints(body: str) -> dict[str, str]:
    """Project refs named by the page. Callers may check metadata. They must not read rows."""
    supa = _SUPABASE.search(body or "")
    fire = _FIREBASE.search(body or "")
    return {
        "supabase_ref": supa.group(1) if supa else "",
        "firebase_ref": fire.group(1) if fire else "",
    }


def report_for(host: str, pages: list[dict[str, Any]], *, active_ran: bool) -> dict[str, Any]:
    fact_ids: list[str] = []
    evidence: list[dict[str, str]] = []
    for page in pages:
        raw = str(page.get("body") or "")
        redacted, kinds = redact(raw)
        safe = dict(page)
        safe["raw_body"] = raw
        safe["body"] = redacted[:400]
        for fact in facts_for_page(safe):
            fact_ids.append(fact)
        if kinds:
            evidence.append({
                "path": str(page.get("path") or "/"),
                "note": "secret kinds: %s" % ", ".join(kinds),
            })
    scored = score_facts([fact for fact in fact_ids if fact != "challenged"], active_ran=active_ran)
    if "challenged" in fact_ids:
        scored["facts"] = sorted(set(scored["facts"]) | {"challenged"})
        scored["findings"].append({
            "id": "challenged",
            "fact": "challenged",
            "stage": "fetch",
            "title": "The host returned a bot check",
            "heat": 0,
            "remediation": "Nothing else was requested from that host.",
            "evidence": "The response was a challenge or a WAF block. It was not retried.",
        })
    for finding in scored["findings"]:
        if finding["id"] == "challenged":
            continue
        match = next((item for item in evidence if finding["id"] == "secret-in-page"), None)
        if match and finding["id"] == "secret-in-page":
            finding["evidence"] = match["note"]
        else:
            finding["evidence"] = finding["title"]
    return {
        "host": host,
        "heat": scored["heat"],
        "score_state": scored["score_state"],
        "pending_stages": scored["pending_stages"],
        "findings": scored["findings"],
        "facts": scored["facts"],
        "mode": "active-baseline" if active_ran else "passive",
    }
