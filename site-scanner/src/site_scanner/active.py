"""Fixed-path existence checks. GET only, and only after the allowlist says yes.

The paths are a short original list in the spirit of Nikto's well-known-file
checks. Nikto's database is GPL and is not included. There is no fuzzing, no
payload, and no query string. A 200 is not enough: the body has to match a
signature. Evidence names the path and not the body.
"""

from __future__ import annotations

import re
from typing import Any

ACTIVE_PATHS = (
    "/.env",
    "/.git/HEAD",
    "/.env.bak",
    "/.env.old",
    "/.env~",
    "/wp-config.php.bak",
    "/config.php.bak",
    "/web.config.bak",
    "/server-status",
    "/phpinfo.php",
    "/info.php",
    "/admin",
    "/wp-admin/",
    "/administrator/",
    "/phpmyadmin/",
    "/.well-known/security.txt",
    "/debug",
)

_ENV_PATHS = frozenset({"/.env", "/.env.bak", "/.env.old", "/.env~"})
_CONFIG_PATHS = frozenset({"/wp-config.php.bak", "/config.php.bak", "/web.config.bak"})
_PHPINFO_PATHS = frozenset({"/phpinfo.php", "/info.php"})
_ENV_LINE = re.compile(r"(?im)^[A-Za-z0-9_]*(?:secret|password|api[_-]?key|db_password)[A-Za-z0-9_]*\s*=")
_CONFIG_MARKER = re.compile(r"(?i)db_password|db_name|connectionstring|<configuration")


def exposure(page: dict[str, Any]) -> dict[str, str] | None:
    """One signature hit, or nothing. A normal 200 page is not a hit."""
    if page.get("challenged") or page.get("skipped") or page.get("same_as_home"):
        return None
    if int(page.get("status") or 0) != 200:
        return None
    path = str(page.get("path") or "/")
    body = str(page.get("body") or "")
    lowered = body.lower()
    if path in _ENV_PATHS and _ENV_LINE.search(body):
        fact = "exposed-env" if path == "/.env" else "exposed-backup"
        return {"id": fact, "evidence": "credential assignment on %s" % path}
    if path == "/.git/HEAD" and lowered.startswith("ref: refs/"):
        return {"id": "exposed-git", "evidence": "git HEAD on /.git/HEAD"}
    if path in _CONFIG_PATHS and _CONFIG_MARKER.search(body):
        return {"id": "exposed-backup", "evidence": "config backup on %s" % path}
    if path == "/server-status" and "apache server status" in lowered:
        return {"id": "exposed-server-status", "evidence": "server status page on /server-status"}
    if path in _PHPINFO_PATHS and "phpinfo" in lowered and "php version" in lowered:
        return {"id": "exposed-phpinfo", "evidence": "phpinfo page on %s" % path}
    if _open_admin(path, lowered):
        return {"id": "open-admin", "evidence": "admin console on %s" % path}
    return None


def _open_admin(path: str, lowered: str) -> bool:
    if path == "/admin" or path.startswith("/admin/"):
        return any(token in lowered for token in ("dashboard", "admin panel", "wp-admin"))
    if path == "/wp-admin/" and 'id="wpbody"' in lowered:
        return True
    if path == "/administrator/" and "com_cpanel" in lowered:
        return True
    if path == "/phpmyadmin/" and "server_databases" in lowered:
        return True
    return False
