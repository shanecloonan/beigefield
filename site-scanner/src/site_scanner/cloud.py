"""Metadata checks only. Never request table rows or store response bodies."""

from __future__ import annotations

import json
import urllib.request
from typing import Any

from site_scanner.analyze import cloud_hints
from site_scanner.fetch import USER_AGENT


def _get(url: str, headers: dict[str, str] | None = None) -> tuple[int, str]:
    request = urllib.request.Request(url, method="GET", headers=headers or {"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            body = response.read(20_000).decode("utf-8", errors="replace")
            return int(getattr(response, "status", 200) or 200), body
    except Exception:
        return 0, ""


def annotate_cloud(pages: list[dict[str, Any]]) -> None:
    """Mark schema-open / root-open flags. Bodies of those checks are discarded."""
    blob = "\n".join(str(page.get("body") or "") for page in pages)
    hints = cloud_hints(blob)
    if hints["supabase_ref"]:
        status, body = _get("https://%s.supabase.co/rest/v1/" % hints["supabase_ref"])
        open_schema = status == 200 and ("paths" in body or "swagger" in body or "openapi" in body)
        if pages:
            pages[0]["supabase_schema_open"] = open_schema
        del body
    if hints["firebase_ref"]:
        status, body = _get("https://%s.firebaseio.com/.json" % hints["firebase_ref"])
        readable = False
        if status == 200 and body and body.strip() not in {"null", "{}", "[]"}:
            try:
                parsed = json.loads(body)
                readable = parsed not in (None, {}, [])
            except json.JSONDecodeError:
                readable = False
        if pages:
            pages[0]["firebase_root_open"] = readable
        del body
