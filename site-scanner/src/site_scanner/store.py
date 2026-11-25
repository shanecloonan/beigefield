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


class StoreError(RuntimeError):
    def __init__(self, status: int, code: str) -> None:
        self.status = int(status)
        self.code = code
        super().__init__("http-%s" % self.status)


def _error_code(raw: str) -> str:
    try:
        parsed = json.loads(raw or "")
    except json.JSONDecodeError:
        return ""
    if not isinstance(parsed, dict):
        return ""
    code = str(parsed.get("code") or "")
    if code and all(ch.isalnum() or ch == "_" for ch in code) and len(code) <= 40:
        return code
    return ""


def _req(
    method: str,
    query: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    table: str = "site_scan_hits",
) -> tuple[list[dict[str, Any]], int]:
    url, key = _env()
    if not url or not key:
        raise StoreError(0, "no-store")
    qs = ("?" + urllib.parse.urlencode(query)) if query else ""
    data = json.dumps(body).encode("utf-8") if body is not None and method != "GET" else None
    request = urllib.request.Request(
        "%s/rest/v1/%s%s" % (url, table, qs),
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
            status = int(getattr(response, "status", 200) or 200)
    except urllib.error.HTTPError as exc:
        err = exc.read(500).decode("utf-8", errors="replace") if exc.fp else ""
        raise StoreError(int(exc.code), _error_code(err)) from None
    if not raw:
        return [], status
    parsed = json.loads(raw)
    if isinstance(parsed, list):
        return parsed, status
    if isinstance(parsed, dict):
        return [parsed], status
    return [], status


def probe_store() -> dict[str, Any]:
    """Whether the service key can read site_scan_hits. No row bodies are returned."""
    url, key = _env()
    if not url or not key:
        return {"status": "no-store"}
    try:
        rows, status = _req("GET", {"select": "dedupe_key", "limit": "1"})
    except StoreError as exc:
        return {"status": "error", "http": exc.status, "code": exc.code}
    return {"status": "ok", "http": status, "rows": len(rows)}


def build_run(run_id: str, started_at: str, finished_at: str, reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts for one run. The row does not copy findings or page bodies."""
    hosts = [str(item.get("host") or "") for item in reports if item.get("host")]
    findings = 0
    for item in reports:
        rows = item.get("findings")
        if isinstance(rows, list):
            findings += len(rows)
    return {
        "run_id": str(run_id or "")[:80],
        "started_at": started_at,
        "finished_at": finished_at,
        "hosts_scanned": len(hosts),
        "finding_count": findings,
    }


def save_run(record: dict[str, Any]) -> dict[str, Any]:
    """Insert or replace one run summary. Nothing from the page body is written."""
    run_id = str(record.get("run_id") or "")
    if not run_id:
        return {"status": "skipped", "reason": "no run"}
    url, key = _env()
    if not url or not key:
        return {"status": "skipped", "reason": "no-store"}
    body = {
        "run_id": run_id[:80],
        "started_at": record.get("started_at"),
        "finished_at": record.get("finished_at"),
        "hosts_scanned": int(record.get("hosts_scanned") or 0),
        "finding_count": int(record.get("finding_count") or 0),
    }
    try:
        saved, status = _req("POST", {"on_conflict": "run_id"}, body, table="site_scan_runs")
    except StoreError as exc:
        return {"status": "skipped", "reason": "http-%s" % exc.status, "code": exc.code}
    wrote = bool(saved) or status in {200, 201, 204}
    return {"status": "ok" if wrote else "skipped", "reason": "" if wrote else "empty", "run_id": body["run_id"]}


def save_hit(report: dict[str, Any]) -> dict[str, Any]:
    """Write one host. Peak heat only rises. Findings are already redacted."""
    host = str(report.get("host") or "").lower()
    if not host:
        return {"status": "skipped", "reason": "no host"}
    url, key = _env()
    if not url or not key:
        return {"status": "skipped", "reason": "no-store"}
    try:
        previous, _status = _req("GET", {"select": "peak_heat", "dedupe_key": "eq.%s" % host, "limit": "1"})
    except StoreError as exc:
        return {"status": "skipped", "reason": "http-%s" % exc.status, "code": exc.code, "host": host}
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
        "heat_breakdown": {
            "facts": report.get("facts") or [],
            "mode": report.get("mode") or "passive",
            "tech": report.get("tech") or [],
            "render": report.get("render") or {},
        },
        "mode": report.get("mode") or "passive",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        saved, status = _req("POST", {"on_conflict": "dedupe_key"}, body)
    except StoreError as exc:
        return {"status": "skipped", "reason": "http-%s" % exc.status, "code": exc.code, "host": host, "heat": heat}
    wrote = bool(saved) or status in {200, 201, 204}
    return {
        "status": "ok" if wrote else "skipped",
        "reason": "" if wrote else "empty",
        "host": host,
        "heat": heat,
        "peak_heat": body["peak_heat"],
    }


CURSOR_ID = "site-scan"


def load_cursor() -> dict[str, Any]:
    """Hosts already scanned in this cycle. Empty when the store is missing."""
    url, key = _env()
    if not url or not key:
        return {"seen": [], "cycle": 0, "status": "no-store"}
    try:
        rows, _status = _req(
            "GET",
            {"select": "seen,cycle", "id": "eq.%s" % CURSOR_ID, "limit": "1"},
            table="site_scan_cursor",
        )
    except StoreError as exc:
        return {"seen": [], "cycle": 0, "status": "error", "code": exc.code}
    if not rows:
        return {"seen": [], "cycle": 0, "status": "ok"}
    seen = rows[0].get("seen") if isinstance(rows[0].get("seen"), list) else []
    try:
        cycle = int(rows[0].get("cycle") or 0)
    except (TypeError, ValueError):
        cycle = 0
    return {"seen": [str(item) for item in seen if item], "cycle": cycle, "status": "ok"}


def save_cursor(seen: list[str], cycle: int) -> dict[str, Any]:
    """Remember the hosts this cycle has already covered. Capped so the row stays small."""
    url, key = _env()
    if not url or not key:
        return {"status": "skipped", "reason": "no-store"}
    body = {
        "id": CURSOR_ID,
        "seen": seen[-500:],
        "cycle": int(cycle),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        _req("POST", {"on_conflict": "id"}, body, table="site_scan_cursor")
    except StoreError as exc:
        return {"status": "skipped", "reason": "http-%s" % exc.status, "code": exc.code}
    return {"status": "ok", "cycle": int(cycle), "seen": len(body["seen"])}
