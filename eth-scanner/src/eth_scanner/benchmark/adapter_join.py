"""Addresses named by a DefiLlama TVL adapter. Read-only, no adapter execution.

The adapter source is public text. Addresses are the literals in that file
for the incident's chain. A remote vault API is not called. At most four
addresses are returned, and the protocol's own listed address is skipped.
"""

from __future__ import annotations

import posixpath
import re
import urllib.request
from typing import Optional

_ADAPTER = "https://raw.githubusercontent.com/DefiLlama/DefiLlama-Adapters/main/projects/{path}"
_CHAIN_ID = {"ethereum": "1", "bsc": "56", "arbitrum": "42161", "base": "8453"}
_ADDR = re.compile(r"0x[a-fA-F0-9]{40}")
_CHAIN_KEY = re.compile(
    r"(?m)^[ \t]{0,8}(ethereum|bsc|arbitrum|base|polygon|optimism|avalanche|era)\s*:",
)
_REQUIRE = re.compile(r"require\(\s*['\"](\.\.?/[^'\"]+)['\"]\s*\)")
_CACHE: dict[str, str] = {}
_MAX = 4


def _http(url: str) -> str:
    req = urllib.request.Request(url, headers={"Accept": "text/plain", "User-Agent": "beigefield-scanner"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _fetch_adapter(module: str) -> str:
    path = (module or "").strip().lstrip("/")
    if not path or ".." in path.split("/") or path.startswith("http"):
        return ""
    if path in _CACHE:
        return _CACHE[path]
    try:
        text = _http(_ADAPTER.format(path=path))
    except (OSError, TimeoutError, ValueError):
        text = ""
    if len(_ADDR.findall(text)) < 3:
        followed = _follow_require(path, text)
        if followed:
            text = followed
    _CACHE[path] = text
    return text


def _follow_require(module: str, text: str) -> str:
    match = _REQUIRE.search(text or "")
    if not match:
        return ""
    rel = match.group(1)
    if "helper" in rel:
        return ""
    base = posixpath.dirname(module)
    joined = posixpath.normpath(posixpath.join(base, rel))
    if joined.startswith("..") or joined.startswith("/"):
        return ""
    candidates = [joined] if joined.endswith(".js") else [joined + ".js", joined + "/index.js"]
    for candidate in candidates:
        if ".." in candidate.split("/"):
            continue
        try:
            followed = _http(_ADAPTER.format(path=candidate))
        except (OSError, TimeoutError, ValueError):
            continue
        if _ADDR.findall(followed):
            return followed
    return ""


def _chain_text(text: str, chain: str) -> str:
    want = _CHAIN_ID.get(chain, "")
    if re.search(r"chainId\s*:\s*\d+", text):
        parts: list[str] = []
        for match in re.finditer(r"chainId\s*:\s*(\d+)", text):
            if match.group(1) == want:
                parts.append(text[match.start():match.start() + 700])
        return "\n".join(parts)
    keys = list(_CHAIN_KEY.finditer(text))
    for index, match in enumerate(keys):
        if match.group(1) != chain:
            continue
        end = keys[index + 1].start() if index + 1 < len(keys) else match.end() + 8000
        return text[match.end():end]
    if re.search(r"\b%s\b" % re.escape(chain), text, re.I) and len(_ADDR.findall(text)) <= 8:
        return text
    return ""


def adapter_addresses(module: str, chain: str, *, skip: str = "") -> list[str]:
    """Up to four adapter addresses on this chain, excluding the listed token."""
    text = _fetch_adapter(module)
    if not text:
        return []
    scoped = _chain_text(text, chain)
    found: list[str] = []
    seen = {(skip or "").lower()}
    for addr in _ADDR.findall(scoped):
        cleaned = addr.lower()
        if cleaned in seen:
            continue
        seen.add(cleaned)
        found.append(cleaned)
        if len(found) >= _MAX:
            break
    return found


def clear_adapter_cache() -> None:
    _CACHE.clear()
