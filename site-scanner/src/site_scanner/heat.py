"""Evidence heat for a website. Each fact counts once. Cap 12.

Scoring goes through the stage fusion from the contract scanner: a pending
stage stays provisional and an empty finished stage does not dilute heat.
"""

from __future__ import annotations

from typing import Any

from eth_scanner.stages.fusion import fuse

MAX_HEAT = 12
# Missing CSP and HSTS stay visible, but together they cannot outrank a real exposure.
HEADER_FACTS = frozenset({"missing-csp", "missing-hsts"})
HEADER_CAP = 1

# fact -> (points, stage, title, remediation)
FACTS: dict[str, tuple[int, str, str, str]] = {
    "missing-csp": (1, "headers", "No Content-Security-Policy", "Send a Content-Security-Policy that limits script and frame sources."),
    "missing-hsts": (1, "headers", "No Strict-Transport-Security", "Send Strict-Transport-Security on HTTPS responses."),
    "cors-credentials-star": (6, "headers", "CORS allows any origin with credentials", "Do not combine Access-Control-Allow-Origin * with Allow-Credentials: true."),
    "tls-expired": (6, "tls", "TLS certificate is expired", "Renew the certificate and keep the chain current."),
    "tls-soon": (1, "tls", "TLS certificate expires within 14 days", "Renew the certificate before it expires."),
    "exposed-env": (8, "exposure", "Environment file is publicly readable", "Remove the file from the web root and rotate any credential that was in it."),
    "exposed-git": (8, "exposure", "Git metadata is publicly readable", "Block .git on the web server and rotate anything the repo contained."),
    "open-directory": (5, "exposure", "Directory listing is enabled", "Turn off autoindex and serve an explicit index or a 403."),
    "open-admin": (4, "exposure", "An admin path responds without a gate", "Require authentication before the admin page is rendered."),
    "secret-in-page": (8, "secrets", "A secret-shaped token is in a public response", "Remove the token from client code and rotate it."),
    "old-library": (6, "fingerprint", "A public page loads a library with a known old line", "Upgrade the library to a supported release."),
    "known-eol": (4, "fingerprint", "A detected library is a known end-of-life release", "Upgrade that library to a release the project still supports."),
    "supabase-schema-open": (8, "cloud", "Supabase OpenAPI schema is readable", "Require a key for /rest/v1/ and enable RLS. Row data was not read."),
    "firebase-root-open": (8, "cloud", "Firebase root JSON is readable", "Tighten the Realtime Database rules. The body was not stored."),
    "dangling-host": (7, "takeover", "The response is a provider's missing-site page", "Remove the dangling DNS record or reclaim the name at the provider."),
}


def score_facts(fact_ids: list[str], *, active_ran: bool) -> dict[str, Any]:
    seen: set[str] = set()
    by_stage: dict[str, list[dict[str, Any]]] = {}
    meta: dict[str, tuple[str, str]] = {}
    for fact in fact_ids:
        if fact in seen or fact not in FACTS:
            continue
        seen.add(fact)
        points, stage, title, fix = FACTS[fact]
        by_stage.setdefault(stage, []).append({
            "fact": fact,
            "heat": points,
            "direction": "support",
            "confidence": 1.0,
        })
        meta[fact] = (title, fix)
    stages = [
        {"id": stage, "status": "done", "confidence": 1.0, "facts": facts}
        for stage, facts in by_stage.items()
    ]
    stages.append({
        "id": "active-baseline",
        "status": "done" if active_ran else "pending",
        "confidence": 1.0 if active_ran else 0.0,
        "facts": [],
    })
    fused = fuse(stages)
    findings = []
    for fact in sorted(seen):
        applied = int((fused.get("facts") or {}).get(fact) or 0)
        if applied <= 0:
            continue
        title, fix = meta[fact]
        _points, stage, _title, _fix = FACTS[fact]
        findings.append({
            "id": fact,
            "fact": fact,
            "stage": stage,
            "title": title,
            "heat": applied,
            "remediation": fix,
        })
    header_room = HEADER_CAP
    rest = 0
    for finding in findings:
        if finding["id"] in HEADER_FACTS:
            applied = min(int(finding["heat"]), header_room)
            finding["heat"] = applied
            header_room -= applied
        else:
            rest += int(finding["heat"])
    heat = min(MAX_HEAT, rest + (HEADER_CAP - header_room))
    findings = [row for row in findings if int(row["heat"]) > 0 or row["id"] in HEADER_FACTS]
    return {
        "heat": heat,
        "findings": findings,
        "stages": {str(row["id"]): str(row["status"]) for row in stages},
        "facts": sorted(seen),
        "score_state": fused.get("score_state") or "provisional",
        "pending_stages": list(fused.get("pending_stages") or []),
    }
