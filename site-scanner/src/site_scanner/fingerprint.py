"""Match vendored WebAppAnalyzer signatures. Versions are evidence, not heat.

A known end-of-life release is the only fingerprint that adds heat, and only
when the version was extracted from the page. A name with no version does not.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

VENDOR = Path(__file__).resolve().parents[2] / "vendor" / "webappanalyzer" / "technologies"

# Releases the projects themselves have ended. A detected version has to match.
EolRule = Callable[[str], bool]
EOL_RULES: dict[str, EolRule] = {
    "jquery": lambda version: version.split(".", 1)[0] in {"1", "2"},
    "angularjs": lambda version: version.startswith("1.") or version == "1",
}

_META = re.compile(
    r"<meta[^>]+(?:name|property)=[\"']([^\"']+)[\"'][^>]+content=[\"']([^\"']*)[\"']",
    re.I,
)
_META_REV = re.compile(
    r"<meta[^>]+content=[\"']([^\"']*)[\"'][^>]+(?:name|property)=[\"']([^\"']+)[\"']",
    re.I,
)
_SCRIPT = re.compile(r"<script[^>]+src=[\"']([^\"']+)[\"']", re.I)
_COOKIE = re.compile(r"([^=;,]+)")


def _patterns(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _compile(raw: str) -> tuple[re.Pattern[str] | None, str]:
    body, _, rest = raw.partition("\\;")
    version = ""
    for piece in rest.split("\\;"):
        if piece.startswith("version:"):
            version = piece.split(":", 1)[1]
    if not body:
        return None, version
    try:
        return re.compile(body, re.I), version
    except re.error:
        return None, version


def _version_from(template: str, match: re.Match[str]) -> str:
    if not template or "?" in template:
        return ""

    def group(found: re.Match[str]) -> str:
        try:
            return match.group(int(found.group(1))) or ""
        except (IndexError, ValueError):
            return ""

    text = re.sub(r"\\(\d+)", group, template).strip()
    if not text or not re.fullmatch(r"\d+(?:\.\d+)*", text):
        return ""
    return text


def _headers(page: dict[str, Any]) -> dict[str, str]:
    raw = page.get("headers") if isinstance(page.get("headers"), dict) else {}
    return {str(key).lower(): str(value) for key, value in raw.items()}


def _cookies(page: dict[str, Any]) -> dict[str, str]:
    found: dict[str, str] = {}
    header = _headers(page).get("set-cookie", "")
    for part in header.split(","):
        name = _COOKIE.match(part.strip())
        if not name:
            continue
        token = name.group(1).strip()
        if "=" in token:
            key, value = token.split("=", 1)
            found[key.strip().lower()] = value.strip()
        elif token:
            found[token.lower()] = ""
    return found


def _meta(body: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for match in _META.finditer(body or ""):
        found[match.group(1).lower()] = match.group(2)
    for match in _META_REV.finditer(body or ""):
        found.setdefault(match.group(2).lower(), match.group(1))
    return found


def _scripts(body: str) -> list[str]:
    return [match.group(1) for match in _SCRIPT.finditer(body or "")]


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    if not VENDOR.is_dir():
        return catalog
    for path in sorted(VENDOR.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            catalog.update({str(key): value for key, value in payload.items() if isinstance(value, dict)})
    return catalog


def _hit(name: str, version: str, source: str, rules: dict[str, EolRule]) -> dict[str, Any]:
    rule = rules.get(name.lower())
    eol = bool(version and rule and rule(version))
    return {
        "name": name,
        "version": version,
        "source": source,
        "eol": eol,
        "heat_contribution": 0,
    }


def match_page(
    page: dict[str, Any],
    *,
    catalog: dict[str, dict[str, Any]] | None = None,
    js_globals: dict[str, str] | None = None,
    eol_rules: dict[str, EolRule] | None = None,
) -> list[dict[str, Any]]:
    """Technologies implied by this page. Heat stays 0 here."""
    if page.get("challenged"):
        return []
    techs = catalog if catalog is not None else load_catalog()
    rules = EOL_RULES if eol_rules is None else eol_rules
    body = str(page.get("body") or "")
    headers = _headers(page)
    cookies = _cookies(page)
    meta = _meta(body)
    scripts = _scripts(body)
    globals_ = {str(key): str(value) for key, value in (js_globals or page.get("js_globals") or {}).items()}
    found: dict[str, dict[str, Any]] = {}

    def keep(hit: dict[str, Any]) -> None:
        current = found.get(hit["name"])
        if current is None or (hit["version"] and not current["version"]):
            found[hit["name"]] = hit

    for name, tech in techs.items():
        for field, source, haystacks in (
            ("headers", "headers", None),
            ("cookies", "cookies", None),
            ("meta", "meta", None),
        ):
            spec = tech.get(field)
            if not isinstance(spec, dict):
                continue
            pool = {"headers": headers, "cookies": cookies, "meta": meta}[field]
            for key, raw in spec.items():
                observed = pool.get(str(key).lower())
                if observed is None:
                    continue
                for pattern, template in (_compile(item) for item in _patterns(raw)):
                    if pattern is None:
                        continue
                    matched = pattern.search(observed)
                    if not matched:
                        continue
                    keep(_hit(name, _version_from(template, matched), source, rules))
        for raw in _patterns(tech.get("scriptSrc")):
            pattern, template = _compile(raw)
            if pattern is None:
                continue
            for src in scripts:
                matched = pattern.search(src)
                if matched:
                    keep(_hit(name, _version_from(template, matched), "script", rules))
                    break
        for raw in _patterns(tech.get("html")):
            pattern, template = _compile(raw)
            if pattern is None or not body:
                continue
            matched = pattern.search(body)
            if matched:
                keep(_hit(name, _version_from(template, matched), "html", rules))
                break
        js_spec = tech.get("js")
        if isinstance(js_spec, dict) and globals_:
            for key, raw in js_spec.items():
                if key not in globals_:
                    continue
                for pattern, template in (_compile(item) for item in _patterns(raw)):
                    if pattern is None:
                        continue
                    matched = pattern.search(globals_[key])
                    if matched:
                        keep(_hit(name, _version_from(template, matched), "js", rules))
    return sorted(found.values(), key=lambda item: item["name"].lower())


def fingerprint_pages(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One list for a host. A version replaces a name-only hit."""
    merged: dict[str, dict[str, Any]] = {}
    for page in pages:
        for hit in match_page(page):
            current = merged.get(hit["name"])
            if current is None or (hit["version"] and not current["version"]):
                merged[hit["name"]] = hit
            elif hit["eol"]:
                current["eol"] = True
    return sorted(merged.values(), key=lambda item: item["name"].lower())
