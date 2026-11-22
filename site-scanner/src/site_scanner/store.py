"""Upsert redacted hits. The service key stays in the environment, never in a row."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any


def _env() -> tuple[str, str]:
    url = (os.environ.get("SUPABASE_URL") or os.environ.get("ETH_SCANNER_SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
    return url, key


def _req(method: str, query: dict[str, str] | None = None, body: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    url, key = _env()
    if not url or not key:
        return []
    qs = ("?" + urllib.parse.urlencode(query)) if query else ""
    data = json.dumps(body).encode("utf-8") if body is not None and method != "GET" else None
    request = urllib.request.Request(
        "%s/rest/v1/site_scan_hits%s" % (url, qs),
        data=data,
        method=method,
        headers={
            "apikey": key,
            "Authorization": "Bearer %s" % key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Prefer": "resolution=merge-duplicates,return=representation",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError:
        return []
    if not raw:
        return []
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, list) else []


def save_hit(report: dict[str, Any]) -> dict[str, Any]:
    """Write one host. Peak heat only rises. Findings are already redacted."""
    host = str(report.get("host") or "").lower()
    if not host:
        return {"status": "skipped", "reason": "no host"}
    url, key = _env()
    if not url or not key:
        return {"status": "skipped", "reason": "no store"}
    previous = _req("GET", {"select": "peak_heat", "dedupe_key": "eq.%s" % host, "limit": "1"})
    prior = 0
    if previous:
        try:
            prior = int(previous[0].get("peak_heat") or 0)
        except (TypeError, ValueError):
            prior = 0
    heat = int(report.get("heat") or 0)
    body = {
        "dedupe_key": host,
        "host": host,
        "url": "https://%s/" % host,
        "heat": heat,
        "peak_heat": max(prior, heat),
        "score_state": report.get("score_state") or "provisional",
        "pending_stages": report.get("pending_stages") or [],
        "findings": report.get("findings") or [],
        "heat_breakdown": {"facts": report.get("facts") or [], "mode": report.get("mode") or "passive"},
        "mode": report.get("mode") or "passive",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    saved = _req("POST", {"on_conflict": "dedupe_key"}, body)
    return {"status": "ok" if saved else "skipped", "host": host, "heat": heat, "peak_heat": body["peak_heat"]}
