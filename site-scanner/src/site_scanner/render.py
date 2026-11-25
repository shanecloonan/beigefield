"""Optional home-page render. Off unless SITE_SCAN_RENDER=1.

Playwright drives ordinary headless Chromium. There is no stealth plugin and
no attempt to pass a bot check. A challenge is recorded and the browser stops.
The saved result is an inventory: script URLs without query strings, cookie
flags, a console-error count, and localStorage key names. Values are dropped.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any
from urllib.parse import urlparse

from site_scanner.fetch import USER_AGENT, challenged
from site_scanner.redact import redact

HOST_BUDGET_S = 8.0
RUN_BUDGET_S = 25.0
_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_VERSION = re.compile(r"^[0-9][0-9A-Za-z._-]{0,20}$")
_STORAGE = re.compile(r"(?i)token|secret|password|jwt|session")
_GLOBALS = """() => {
  const read = (fn) => {
    try {
      const value = fn();
      return value == null ? "" : String(value).slice(0, 40);
    } catch (e) {
      return "";
    }
  };
  return {
    "jQuery.fn.jquery": read(() => window.jQuery && window.jQuery.fn && window.jQuery.fn.jquery),
    "angular.version.full": read(() => window.angular && window.angular.version && window.angular.version.full),
    "React.version": read(() => window.React && window.React.version),
  };
}"""


def render_enabled() -> bool:
    return os.environ.get("SITE_SCAN_RENDER", "").strip().lower() in {"1", "true", "yes"}


class RenderBudget:
    """One budget for a whole run, so a slow host cannot consume the rest."""

    def __init__(self, total_s: float = RUN_BUDGET_S, now: float | None = None) -> None:
        start = time.monotonic() if now is None else now
        self.deadline = start + max(0.0, float(total_s))

    def remaining(self, now: float | None = None) -> float:
        clock = time.monotonic() if now is None else now
        return self.deadline - clock


def _safe_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw.startswith(("http://", "https://")):
        return ""
    parsed = urlparse(raw)
    if not parsed.hostname:
        return ""
    return "%s://%s%s" % (parsed.scheme, parsed.hostname, parsed.path or "/")


def _cookie_header(cookie: dict[str, Any]) -> str:
    name = str(cookie.get("name") or "")
    if not _NAME.match(name):
        return ""
    bits = ["%s=1" % name]
    if cookie.get("httpOnly") or cookie.get("httponly"):
        bits.append("HttpOnly")
    if cookie.get("secure"):
        bits.append("Secure")
    same = str(cookie.get("sameSite") or cookie.get("samesite") or "")
    if same.lower() in {"strict", "lax", "none"}:
        bits.append("SameSite=%s" % same[:8])
    return "; ".join(bits)


def storage_note(keys: list[str]) -> dict[str, str] | None:
    hits = []
    for key in keys:
        name = str(key or "")
        if _STORAGE.search(name) and name not in hits:
            hits.append(name[:80])
    if not hits:
        return None
    return {"id": "storage-token", "evidence": "localStorage key: %s" % ", ".join(hits[:5])}


def page_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """A scanner page. Cookie values, query strings, and storage values are not copied."""
    status = int(snapshot.get("status") or 0)
    if snapshot.get("challenged"):
        return {
            "path": "/rendered",
            "scheme": "https",
            "status": status or 403,
            "headers": {},
            "body": "",
            "challenged": True,
            "rendered": True,
            "render_status": "challenged",
            "script_count": 0,
            "console_errors": 0,
            "storage_keys": [],
        }
    scripts = []
    for url in snapshot.get("scripts") or []:
        safe = _safe_url(str(url))
        if safe and safe not in scripts:
            scripts.append(safe)
        if len(scripts) >= 30:
            break
    styles = []
    for url in snapshot.get("styles") or []:
        safe = _safe_url(str(url))
        if safe and safe not in styles:
            styles.append(safe)
    parts = ['<script src="%s"></script>' % url for url in scripts]
    parts.extend('<link rel="stylesheet" href="%s">' % url for url in styles)
    cookies = [header for header in (_cookie_header(item) for item in snapshot.get("cookies") or []) if header]
    headers: dict[str, Any] = {}
    if len(cookies) == 1:
        headers["set-cookie"] = cookies[0]
    elif cookies:
        headers["set-cookie"] = cookies
    globals_: dict[str, str] = {}
    for key, value in (snapshot.get("js_globals") or {}).items():
        text = str(value or "")
        if _VERSION.match(text):
            globals_[str(key)[:80]] = text
    storage = []
    for key in snapshot.get("storage_keys") or []:
        name = str(key or "").strip()[:80]
        if name and name not in storage:
            storage.append(name)
        if len(storage) >= 20:
            break
    note, _kinds = redact(str(snapshot.get("console_message") or ""))
    return {
        "path": "/rendered",
        "scheme": "https",
        "status": status or 200,
        "headers": headers,
        "body": "\n".join(parts),
        "js_globals": globals_,
        "rendered": True,
        "render_status": "rendered",
        "script_count": len(scripts),
        "console_errors": int(snapshot.get("console_errors") or 0),
        "console_note": note[:80],
        "storage_keys": storage,
    }


def render_summary(pages: list[dict[str, Any]]) -> dict[str, Any] | None:
    rendered = [page for page in pages if page.get("rendered")]
    if not rendered:
        return None
    page = rendered[0]
    return {
        "status": str(page.get("render_status") or "rendered"),
        "scripts": int(page.get("script_count") or 0),
        "console_errors": int(page.get("console_errors") or 0),
        "console_note": str(page.get("console_note") or ""),
        "storage_keys": list(page.get("storage_keys") or [])[:8],
    }


async def _playwright_snapshot(host: str, budget_s: float) -> dict[str, Any]:
    """Load one home page. Imported only when rendering is turned on."""
    from playwright.async_api import async_playwright

    console: list[str] = []
    resources: list[str] = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            context = await browser.new_context(user_agent=USER_AGENT)
            page = await context.new_page()
            page.on("console", lambda msg: console.append(msg.text) if msg.type == "error" else None)
            page.on("response", lambda response: resources.append(response.url))
            response = await page.goto(
                "https://%s/" % host,
                wait_until="domcontentloaded",
                timeout=int(max(1.0, budget_s) * 1000),
            )
            status = int(response.status) if response is not None else 0
            html = await page.content()
            title = await page.title()
            headers = dict(response.headers) if response is not None else {}
            if challenged(status, headers, "%s\n%s" % (title, html[:2000])):
                return {"status": status, "challenged": True}
            cookies = await context.cookies()
            scripts = await page.eval_on_selector_all("script[src]", "nodes => nodes.map(node => node.src).slice(0, 30)")
            styles = await page.eval_on_selector_all(
                "link[rel='stylesheet']",
                "nodes => nodes.map(node => node.href).slice(0, 15)",
            )
            storage = await page.evaluate("() => { try { return Object.keys(window.localStorage).slice(0, 20); } catch (e) { return []; } }")
            globals_ = await page.evaluate(_GLOBALS)
            message = console[0] if console else ""
            return {
                "status": status or 200,
                "scripts": scripts or [],
                "styles": styles or [],
                "resources": resources[:40],
                "cookies": [
                    {"name": item.get("name"), "httpOnly": item.get("httpOnly"), "secure": item.get("secure"), "sameSite": item.get("sameSite")}
                    for item in cookies
                ],
                "js_globals": globals_ or {},
                "storage_keys": storage or [],
                "console_errors": len(console),
                "console_message": message[:160],
            }
        finally:
            await browser.close()


async def render_home(host: str, budget: RenderBudget) -> dict[str, Any] | None:
    """One rendered page, or a short status when the budget or the browser is missing."""
    remaining = budget.remaining()
    if remaining < 1:
        return {"path": "/rendered", "scheme": "https", "status": 0, "headers": {}, "body": "", "rendered": True, "render_status": "budget", "script_count": 0, "console_errors": 0, "storage_keys": []}
    try:
        snapshot = await _playwright_snapshot(host, min(HOST_BUDGET_S, remaining))
    except ImportError:
        return {"path": "/rendered", "scheme": "https", "status": 0, "headers": {}, "body": "", "rendered": True, "render_status": "unavailable", "script_count": 0, "console_errors": 0, "storage_keys": []}
    except Exception:
        return {"path": "/rendered", "scheme": "https", "status": 0, "headers": {}, "body": "", "rendered": True, "render_status": "error", "script_count": 0, "console_errors": 0, "storage_keys": []}
    return page_from_snapshot(snapshot)
