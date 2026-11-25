"""Async GETs of a page and a short list of well-known paths. No payloads.

httpx is the client, with HTTP/2 when the server allows it. Each host is
rate-limited, timeouts are bounded, and a transient failure is retried once.
A bot challenge or a WAF block is recorded and not retried.
"""

from __future__ import annotations

import asyncio
import re
import socket
import ssl
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import httpx

USER_AGENT = "beigefield-site-scanner/0.2 (+https://beigefield.com)"
PASSIVE_PATHS = ("/robots.txt", "/", "/.env", "/.git/HEAD", "/admin")
ACTIVE_PATHS = ("/.well-known/security.txt", "/debug")
_MAX_BODY = 80_000
_TIMEOUT = 6.0
_SCRIPT = re.compile(r"<script[^>]+src=[\"']([^\"']+)[\"']", re.I)
_MAP = re.compile(r"sourceMappingURL=(\S+)")
_CHALLENGE = (
    "just a moment",
    "cf-browser-verification",
    "attention required",
    "verify you are human",
    "cf-mitigated",
    "datadome",
    "incapsula incident",
    "g-recaptcha",
    "hcaptcha",
    "akamaighost",
    "errors.edgesuite.net",
)
_RETRY_STATUS = {429, 502, 503, 504}
Sleep = Callable[[float], Awaitable[None] | None]


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


def challenged(status: int, headers: dict[str, str], body: str) -> bool:
    """True when the response is a bot check or a WAF block, not a normal page."""
    if int(status or 0) not in {401, 403, 429, 503}:
        return False
    blob = " ".join([
        " ".join("%s %s" % (key, value) for key, value in (headers or {}).items()),
        (body or "")[:2000],
    ]).lower()
    return any(marker in blob for marker in _CHALLENGE)


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


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        http2=True,
        follow_redirects=True,
        timeout=httpx.Timeout(_TIMEOUT, connect=5.0),
        headers={"User-Agent": USER_AGENT},
        limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
    )


class _HostGate:
    """One host: a gap between requests and a cap on in-flight calls."""

    def __init__(self, pause_s: float, sleep: Callable[[float], Awaitable[None]]) -> None:
        self.pause_s = max(0.0, float(pause_s))
        self.sleep = sleep
        self._lock = asyncio.Lock()
        self._next = 0.0
        self.slots = asyncio.Semaphore(3)

    async def wait(self) -> None:
        async with self._lock:
            delay = self._next - time.monotonic()
            self._next = max(self._next, time.monotonic()) + self.pause_s
        if delay > 0:
            await self.sleep(delay)


async def _get(
    client: httpx.AsyncClient,
    url: str,
    gate: _HostGate,
    sleep: Callable[[float], Awaitable[None]],
) -> dict[str, Any]:
    """GET once, then once more on a transient failure. A challenge stops there."""
    last: dict[str, Any] = {"status": 0, "headers": {}, "body": "", "error": "no-attempt"}
    for attempt in range(2):
        await gate.wait()
        async with gate.slots:
            try:
                response = await client.get(url)
                body = response.text[:_MAX_BODY]
                headers = {key: value for key, value in response.headers.items()}
                page = {"status": int(response.status_code), "headers": headers, "body": body}
            except httpx.HTTPError as exc:
                last = {"status": 0, "headers": {}, "body": "", "error": type(exc).__name__}
                if attempt == 0:
                    await sleep(0.5)
                    continue
                return last
        if challenged(page["status"], page["headers"], page["body"]):
            page["challenged"] = True
            page["body"] = ""
            return page
        if page["status"] not in _RETRY_STATUS or attempt == 1:
            return page
        last = page
        await sleep(0.5 * (attempt + 1))
    return last


def _annotate(page: dict[str, Any], host: str, path: str, tls: dict[str, bool]) -> dict[str, Any]:
    page["path"] = path
    page["url"] = "https://%s%s" % (host, path) if path.startswith("/") else page.get("url") or path
    page["scheme"] = "https"
    page.update(tls)
    return page


async def fetch_host_async(
    host: str,
    *,
    active: bool,
    pause_s: float = 0.4,
    client: httpx.AsyncClient | None = None,
    tls_check: Callable[[str], dict[str, bool]] | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> list[dict[str, Any]]:
    """GET the passive paths. Extra paths run only when active is already authorized."""
    own_client = client is None
    http = client or _client()
    pause = sleep or asyncio.sleep
    gate = _HostGate(pause_s, pause)
    check = tls_check or _tls_flags
    paths = list(PASSIVE_PATHS)
    if active:
        paths.extend(ACTIVE_PATHS)
    pages: list[dict[str, Any]] = []
    robots = ""
    tls = check(host)
    try:
        for path in paths:
            if path != "/robots.txt" and robots and _robots_disallows(robots, path):
                pages.append(_annotate(
                    {"status": 0, "headers": {}, "body": "", "skipped": "robots"},
                    host, path, tls,
                ))
                continue
            page = await _get(http, "https://%s%s" % (host, path), gate, pause)
            _annotate(page, host, path, tls)
            pages.append(page)
            if page.get("challenged"):
                return pages
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
            page = await _get(http, url, gate, pause)
            page["url"] = url
            _annotate(page, host, path, tls)
            pages.append(page)
            if page.get("challenged"):
                return pages
            if not mapping:
                mapping = _map_url(host, [page])
        if mapping:
            path = mapping.split(host, 1)[-1] or "/"
            if not (robots and _robots_disallows(robots, path)):
                page = await _get(http, mapping, gate, pause)
                page["url"] = mapping
                _annotate(page, host, path, tls)
                pages.append(page)
        return pages
    finally:
        if own_client:
            await http.aclose()


def fetch_host(
    host: str,
    *,
    active: bool,
    pause_s: float = 0.4,
    opener: Callable[..., Any] | None = None,
    tls_check: Callable[[str], dict[str, bool]] | None = None,
    client: httpx.AsyncClient | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> list[dict[str, Any]]:
    """Synchronous wrapper. ``opener`` remains for older tests and is not the live client."""
    if opener is not None:
        return _fetch_with_opener(host, active=active, pause_s=pause_s, opener=opener, tls_check=tls_check)
    return asyncio.run(fetch_host_async(
        host, active=active, pause_s=pause_s, client=client, tls_check=tls_check, sleep=sleep,
    ))


def _fetch_with_opener(
    host: str,
    *,
    active: bool,
    pause_s: float,
    opener: Callable[..., Any],
    tls_check: Callable[[str], dict[str, bool]] | None,
) -> list[dict[str, Any]]:
    """The previous urllib shape, kept so a test can inject a fake opener."""
    import urllib.error
    import urllib.request

    paths = list(PASSIVE_PATHS)
    if active:
        paths.extend(ACTIVE_PATHS)
    pages: list[dict[str, Any]] = []
    robots = ""
    tls = (tls_check or _tls_flags)(host)
    for index, path in enumerate(paths):
        if index:
            time.sleep(pause_s)
        if path != "/robots.txt" and robots and _robots_disallows(robots, path):
            pages.append(_annotate({"status": 0, "headers": {}, "body": "", "skipped": "robots"}, host, path, tls))
            continue
        request = urllib.request.Request(
            "https://%s%s" % (host, path), method="GET", headers={"User-Agent": USER_AGENT},
        )
        try:
            with opener(request, timeout=_TIMEOUT) as response:
                body = response.read(_MAX_BODY + 1)[:_MAX_BODY].decode("utf-8", errors="replace")
                headers = {key: value for key, value in response.headers.items()}
                page = {"status": int(getattr(response, "status", 200) or 200), "headers": headers, "body": body}
        except urllib.error.HTTPError as exc:
            body = exc.read(_MAX_BODY) if exc.fp else b""
            text = body[:_MAX_BODY].decode("utf-8", errors="replace") if isinstance(body, bytes) else ""
            headers = {key: value for key, value in exc.headers.items()} if exc.headers else {}
            page = {"status": int(exc.code), "headers": headers, "body": text}
        except Exception as exc:
            page = {"status": 0, "headers": {}, "body": "", "error": str(exc)[:160]}
        _annotate(page, host, path, tls)
        pages.append(page)
        if path == "/robots.txt" and page.get("status") == 200:
            robots = str(page.get("body") or "")
        if page.get("status") == 0 and path != "/robots.txt":
            return pages
    return pages
