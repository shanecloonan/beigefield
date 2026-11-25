"""Passive findings on pages that were already fetched. No extra requests.

The categories follow the OWASP ZAP passive scan rules (Apache-2.0,
https://github.com/zaproxy/zaproxy): cookie flags, CSP weaknesses, clickjacking
and content-type headers, server banners, private addresses, verbose errors,
mixed active content, and directory listings. This module is original
Beigefield code. No ZAP source is included.

Left out on purpose, because they are noisy or they need another request:
image-only mixed content, timestamps, HTML comments, cache headers, and
cross-domain script inclusion. Path probes such as backup files, phpinfo, and
server-status are active checks and do not live here.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

_SESSION_PARTS = frozenset({
    "sid",
    "session",
    "sessionid",
    "phpsessid",
    "jsessionid",
    "auth",
    "token",
    "jwt",
    "remember",
    "login",
})
_PRIVATE = re.compile(
    r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3})\b"
)
_VERSIONED = re.compile(r"[A-Za-z][A-Za-z0-9_-]*/\d")
_ERRORS: tuple[tuple[str, re.Pattern[str], bool], ...] = (
    ("python-traceback", re.compile(r"Traceback \(most recent call last\)"), False),
    ("sql-error", re.compile(r"(?i)you have an error in your sql syntax|unclosed quotation mark after the character string|pg_query\(\)|ORA-\d{5}|SQLSTATE\["), False),
    ("php-fatal", re.compile(r"(?i)fatal error:.+on line \d+"), False),
    ("debug-page", re.compile(r"(?i)\bdebug\s*=\s*true\b|whitelabel error page"), True),
    ("stack-trace", re.compile(r"(?i)\bstack trace:"), True),
)
_LISTING = (
    "<title>index of",
    "<h1>index of",
    "directory listing for",
    "parent directory</a>",
    "[to parent directory]",
)
_SCHEME_SOURCE = frozenset({"*", "http:", "https:", "ws:", "wss:", "data:"})


def _header(headers: dict[str, Any], name: str) -> str:
    for key, value in (headers or {}).items():
        if str(key).lower() == name.lower() and not isinstance(value, list):
            return str(value or "")
    return ""


def _set_cookies(headers: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for key, value in (headers or {}).items():
        if str(key).lower() != "set-cookie":
            continue
        if isinstance(value, list):
            found.extend(str(item) for item in value if str(item).strip())
        elif str(value).strip():
            found.append(str(value))
    return found


def _cookie_name(raw: str) -> str:
    return raw.split("=", 1)[0].strip()


def _cookie_attrs(raw: str) -> set[str]:
    return {part.strip().lower() for part in raw.split(";")[1:] if part.strip()}


def _session_cookie(name: str) -> bool:
    parts = [part for part in name.lower().replace("-", "_").replace(".", "_").split("_") if part]
    return any(part in _SESSION_PARTS or part.startswith("sess") for part in parts)


def _names(names: list[str]) -> str:
    shown = names[:5]
    text = ", ".join(shown)
    if len(names) > len(shown):
        text += ", ..."
    return text


def _directives(policy: str) -> dict[str, list[str]]:
    parsed: dict[str, list[str]] = {}
    for part in (policy or "").split(";"):
        tokens = part.strip().split()
        if not tokens:
            continue
        parsed[tokens[0].lower()] = [token.lower() for token in tokens[1:]]
    return parsed


def _script_sources(directives: dict[str, list[str]]) -> list[str] | None:
    if "script-src" in directives:
        return directives["script-src"]
    if "default-src" in directives:
        return directives["default-src"]
    return None


def _private_ips(text: str) -> list[str]:
    found: list[str] = []
    for match in _PRIVATE.finditer(text or ""):
        ip = match.group(0)
        if any(int(part) > 255 for part in ip.split(".")):
            continue
        if ip not in found:
            found.append(ip)
        if len(found) >= 3:
            break
    return found


def _host_of_url(url: str) -> str:
    host = urlparse(url).hostname or ""
    return host or "unknown-host"


def _mixed_urls(html: str) -> list[str]:
    urls: list[str] = []

    def take(pattern: str, text: str) -> None:
        for match in re.finditer(pattern, text, re.I):
            url = match.group(1)
            if url.startswith(("http://localhost", "http://127.0.0.1")):
                continue
            if url not in urls:
                urls.append(url)

    take(r"<script\b[^>]*\bsrc\s*=\s*[\"'](http://[^\"']+)", html)
    take(r"<iframe\b[^>]*\bsrc\s*=\s*[\"'](http://[^\"']+)", html)
    for match in re.finditer(r"<link\b[^>]*>", html, re.I):
        tag = match.group(0)
        if not re.search(r"\brel\s*=\s*[\"']stylesheet[\"']", tag, re.I):
            continue
        take(r"\bhref\s*=\s*[\"'](http://[^\"']+)", tag)
    return urls


def _cookie_findings(cookies: list[str], *, https: bool) -> list[dict[str, str]]:
    httponly: list[str] = []
    secure: list[str] = []
    samesite: list[str] = []
    none_site: list[str] = []
    for raw in cookies:
        name = _cookie_name(raw)
        if not name:
            continue
        attrs = _cookie_attrs(raw)
        session = _session_cookie(name)
        if https and "secure" not in attrs:
            secure.append(name)
        if session and "httponly" not in attrs:
            httponly.append(name)
        same = next((attr for attr in attrs if attr.startswith("samesite=")), "")
        if session and not same:
            samesite.append(name)
        elif session and same == "samesite=none":
            none_site.append(name)
    found: list[dict[str, str]] = []
    if httponly:
        found.append({"id": "cookie-no-httponly", "evidence": "session cookie missing HttpOnly: %s" % _names(httponly)})
    if secure:
        found.append({"id": "cookie-no-secure", "evidence": "cookies missing Secure: %s" % _names(secure)})
    if samesite:
        found.append({"id": "cookie-no-samesite", "evidence": "session cookie missing SameSite: %s" % _names(samesite)})
    if none_site:
        found.append({"id": "cookie-samesite-none", "evidence": "session cookie SameSite=None: %s" % _names(none_site)})
    return found


def _csp_findings(policy: str) -> list[dict[str, str]]:
    sources = _script_sources(_directives(policy))
    if sources is None:
        return []
    found: list[dict[str, str]] = []
    if "'unsafe-inline'" in sources:
        found.append({"id": "csp-unsafe-inline", "evidence": "script source contains 'unsafe-inline'"})
    if "'unsafe-eval'" in sources:
        found.append({"id": "csp-unsafe-eval", "evidence": "script source contains 'unsafe-eval'"})
    broad = [token for token in sources if token in _SCHEME_SOURCE]
    if broad:
        found.append({"id": "csp-wildcard", "evidence": "script source allows %s" % ", ".join(broad)})
    return found


def _banner(headers: dict[str, Any]) -> str:
    bits: list[str] = []
    server = _header(headers, "server")
    if _VERSIONED.search(server):
        bits.append("server: %s" % server[:60])
    for name in ("x-powered-by", "x-aspnet-version", "x-aspnetmvc-version"):
        value = _header(headers, name).strip()
        if value:
            bits.append("%s: %s" % (name, value[:60]))
    return "; ".join(bits)


def passive_on(page: dict[str, Any]) -> list[dict[str, str]]:
    """Findings for one stored page. Evidence names the issue and never a cookie value or body."""
    if page.get("challenged") or page.get("skipped"):
        return []
    status = int(page.get("status") or 0)
    if not status:
        return []
    headers = page.get("headers") if isinstance(page.get("headers"), dict) else {}
    body = str(page.get("body") or "")
    path = str(page.get("path") or "/")
    https = str(page.get("scheme") or "https") == "https"
    home = path in {"/", ""}
    found: list[dict[str, str]] = _cookie_findings(_set_cookies(headers), https=https)

    if home:
        nosniff = _header(headers, "x-content-type-options").lower()
        if "nosniff" not in nosniff:
            note = "no X-Content-Type-Options on %s" % path
            if nosniff.strip():
                note = "X-Content-Type-Options is not nosniff on %s" % path
            found.append({"id": "missing-nosniff", "evidence": note})
        frame = _header(headers, "x-frame-options").strip()
        ancestors = "frame-ancestors" in _directives(_header(headers, "content-security-policy"))
        if not frame and not ancestors:
            found.append({"id": "missing-frame-options", "evidence": "no X-Frame-Options or frame-ancestors on %s" % path})
        banner = _banner(headers)
        if banner:
            found.append({"id": "server-banner", "evidence": banner})
        found.extend(_csp_findings(_header(headers, "content-security-policy")))

    lowered = body.lower()
    if status == 200 and any(phrase in lowered for phrase in _LISTING):
        found.append({"id": "open-directory", "evidence": "directory listing on %s" % path})

    addresses = _private_ips(body)
    if addresses:
        found.append({
            "id": "private-ip",
            "evidence": "private address %s on %s" % (", ".join(addresses), path),
        })

    for label, pattern, errors_only in _ERRORS:
        if errors_only and status < 400:
            continue
        if pattern.search(body):
            found.append({"id": "verbose-error", "evidence": "%s on %s" % (label, path)})
            break

    mixed = _mixed_urls(body) if https and status == 200 else []
    if mixed:
        hosts: list[str] = []
        for url in mixed:
            host = _host_of_url(url)
            if host not in hosts:
                hosts.append(host)
        found.append({"id": "mixed-content", "evidence": "active content over http from %s on %s" % (_names(hosts), path)})
    return found
