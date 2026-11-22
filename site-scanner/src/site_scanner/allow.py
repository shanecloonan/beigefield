"""Active checks run only on owned hosts or an explicit bounty-scope list."""

from __future__ import annotations

OWNED_HOSTS = frozenset({
    "beigefield.vercel.app",
    "www.beigefield.com",
    "beigefield.com",
    "dap-ashy.vercel.app",
})


def host_of(value: str) -> str:
    text = (value or "").strip().lower()
    if "://" in text:
        text = text.split("://", 1)[1]
    text = text.split("/", 1)[0].split("?", 1)[0].split(":", 1)[0]
    if text.startswith("www.") and text != "www.beigefield.com":
        return text
    return text.rstrip(".")


def active_allowed(host: str, bounty_hosts: set[str] | None = None) -> bool:
    """True only for Shane-owned domains or a program scope that was loaded in."""
    name = host_of(host)
    if not name:
        return False
    if name in OWNED_HOSTS:
        return True
    extra = {host_of(item) for item in (bounty_hosts or set())}
    return name in extra
