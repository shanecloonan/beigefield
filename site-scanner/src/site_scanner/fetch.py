"""Single GETs of a page and a short list of well-known paths. No payloads."""

from __future__ import annotations

import re
import socket
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable

PASSIVE_PATHS = ("/robots.txt", "/", "/.env", "/.git/HEAD", "/admin")
ACTIVE_PATHS = ("/.well-known/security.txt", "/debug")
_MAX_BODY = 80_000
_TIMEOUT = 6.0
_SCRIPT = re.compile(r"<script[^>]+src=[\"']([^\"']+)[\"']", re.I)
_MAP = re.compile(r"sourceMappingURL=(\S+)")


def _robots_disallows(text: str, path: str) -> bool:
    """Honor User-agent: * Disallow lines. A missing file does not block."""
    agent = False
    for raw in (text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = [part.strip() for part in line.split(":", 1)]
        if key.lower() == "user-agent":
            agent = value == "*"
            continue
        if agent and key.lower() == "disallow" and value and path.startswith(value):
            return True
    return False


def _tls_flags(host: str) -> dict[str, bool]:
    flags = {"tls_expired": False, "tls_soon": False}
    try:
        context = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=_TIMEOUT) as sock:
            with context.wrap_socket(sock, server_hostname=host) as wrapped:
                cert = wrapped.getpeercert()
    except Exception:
        return flags
    if not cert:
        return flags
    not_after = cert.get("notAfter")
    if not not_after:
        return flags
    try:
        expiry = datetime.strptime(str(not_after), "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    except ValueError:
        return flags
    delta = expiry - datetime.now(timezone.utc)
    flags["tls_expired"] = delta.total_seconds() < 0
    flags["tls_soon"] = 0 <= delta.total_seconds() < 14 * 24 * 3600
    return flags


def _get(url: str, opener: Callable[..., Any]) -> dict[str, Any]:
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": "beigefield-site-scanner/0.1"})
    try:
        with opener(request, timeout=_TIMEOUT) as response:
            body = response.read(_MAX_BODY + 1)[:_MAX_BODY].decode("utf-8", errors="replace")
            headers = {key: value for key, value in response.headers.items()}
            return {"status": int(getattr(response, "status", 200) or 200), "headers": headers, "body": body}
    except urllib.error.HTTPError as exc:
        body = exc.read(_MAX_BODY) if exc.fp else b""
        text = body[:_MAX_BODY].decode("utf-8", errors="replace") if isinstance(body, bytes) else ""
        headers = {key: value for key, value in exc.headers.items()} if exc.headers else {}
        return {"status": int(exc.code), "headers": headers, "body": text}
    except Exception as exc:
        return {"status": 0, "headers": {}, "body": "", "error": str(exc)[:160]}


def _same_origin(host: str, src: str) -> str:
    value = (src or "").strip()
    if value.startswith("//"):
        value = "https:" + value
    if value.startswith("/"):
        return "https://%s%s" % (host, value.split("?", 1)[0])
    prefix = "https://%s/" % host
    if value.startswith(prefix):
        return value.split("?", 1)[0]
    return ""


def _script_urls(host: str, pages: list[dict[str, Any]]) -> list[str]:
    """Up to three same-origin scripts referenced by the home page."""
    html = ""
    for page in pages:
        if page.get("path") == "/" and page.get("status") == 200:
            html = str(page.get("body") or "")
            break
    urls: list[str] = []
    for match in _SCRIPT.finditer(html):
        url = _same_origin(host, match.group(1))
        if url and url not in urls:
            urls.append(url)
        if len(urls) >= 3:
            break
    return urls


def _map_url(host: str, pages: list[dict[str, Any]]) -> str:
    """One same-origin source map named by a script we already fetched."""
    for page in pages:
        if not str(page.get("path") or "").endswith(".js"):
            continue
        mapping = _MAP.search(str(page.get("body") or ""))
        if not mapping:
            continue
        url = _same_origin(host, mapping.group(1))
        if url:
            return url
    return ""


def fetch_host(
    host: str,
    *,
    active: bool,
    pause_s: float = 0.4,
    opener: Callable[..., Any] | None = None,
    tls_check: Callable[[str], dict[str, bool]] | None = None,
) -> list[dict[str, Any]]:
    """GET the passive paths. Extra paths run only when active is already authorized."""
    open_url = opener or urllib.request.urlopen
    check = tls_check or _tls_flags
    paths = list(PASSIVE_PATHS)
    if active:
        paths.extend(ACTIVE_PATHS)
    pages: list[dict[str, Any]] = []
    robots = ""
    tls = check(host)
    for index, path in enumerate(paths):
        if index:
            time.sleep(pause_s)
        if path != "/robots.txt" and robots and _robots_disallows(robots, path):
            pages.append({"path": path, "url": "https://%s%s" % (host, path), "status": 0, "headers": {}, "body": "", "skipped": "robots"})
            continue
        page = _get("https://%s%s" % (host, path), open_url)
        page["path"] = path
        page["url"] = "https://%s%s" % (host, path)
        page["scheme"] = "https"
        page.update(tls)
        pages.append(page)
        if path == "/robots.txt" and page.get("status") == 200:
            robots = str(page.get("body") or "")
        if page.get("status") == 0 and path != "/robots.txt":
            return pages
    extras = _script_urls(host, pages)
    mapping = ""
    for url in extras:
        path = url.split(host, 1)[-1] or "/"
        if robots and _robots_disallows(robots, path):
            continue
        time.sleep(pause_s)
        page = _get(url, open_url)
        page["path"] = path
        page["url"] = url
        page["scheme"] = "https"
        page.update(tls)
        pages.append(page)
        if not mapping:
            mapping = _map_url(host, [page])
    if mapping:
        path = mapping.split(host, 1)[-1] or "/"
        if not (robots and _robots_disallows(robots, path)):
            time.sleep(pause_s)
            page = _get(mapping, open_url)
            page["path"] = path
            page["url"] = mapping
            page["scheme"] = "https"
            page.update(tls)
            pages.append(page)
    return pages
