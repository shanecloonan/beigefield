"""Optional free/existing-key LLM pass for plain-language triage notes.

Hard rules:
- Skip entirely when no key is configured.
- Explanation ranks/clarifies only — never adds heat by itself.
- Defensive language only; no exploit recipes.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Optional


def llm_configured() -> bool:
    return bool(
        (os.environ.get("OPENAI_API_KEY") or "").strip()
        or (os.environ.get("ETH_SCANNER_LLM_API_KEY") or "").strip()
    )


def explain_finding(
    finding: dict[str, Any],
    *,
    context: Optional[dict[str, Any]] = None,
    timeout_s: float = 20.0,
) -> dict[str, Any]:
    """Return {skipped|ok, explanation, model?}. Never mutates heat."""
    key = (os.environ.get("ETH_SCANNER_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        return {
            "status": "skipped",
            "explanation": "LLM triage skipped — no OPENAI_API_KEY / ETH_SCANNER_LLM_API_KEY configured.",
            "adds_heat": False,
        }

    base = (os.environ.get("ETH_SCANNER_LLM_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("ETH_SCANNER_LLM_MODEL") or "gpt-4o-mini"
    prompt = _build_prompt(finding, context or {})
    body = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a defensive smart-contract triage assistant. "
                    "Explain whether a finding looks like a real funds-at-risk issue or a false positive. "
                    "Never provide exploit steps, calldata, or attack transactions. "
                    "Keep the answer under 120 words."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    }
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer %s" % key,
            "User-Agent": "eth-scanner/0.4 (defensive triage; no exploits)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        text = (
            (((payload.get("choices") or [{}])[0].get("message") or {}).get("content"))
            or ""
        ).strip()
        return {
            "status": "ok",
            "explanation": text[:2000] or "(empty model response)",
            "model": model,
            "adds_heat": False,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "explanation": "LLM triage failed: %s" % str(exc)[:200],
            "adds_heat": False,
        }


def _build_prompt(finding: dict[str, Any], context: dict[str, Any]) -> str:
    return (
        "Finding (defensive desk):\n"
        + json.dumps({
            "engine": finding.get("engine"),
            "rule": finding.get("rule"),
            "title": finding.get("title"),
            "class": finding.get("funds_class") or finding.get("class"),
            "severity": finding.get("severity"),
            "confidence": finding.get("confidence"),
            "evidence": str(finding.get("evidence") or "")[:400],
            "agreement_engines": finding.get("agreement_engines"),
        }, indent=2)
        + "\nContext:\n"
        + json.dumps({
            "address": context.get("address"),
            "contract_name": context.get("contract_name"),
            "funds_usd": context.get("funds_usd"),
            "bucket": context.get("bucket"),
            "known_safe": context.get("known_safe"),
        }, indent=2)
        + "\nIs this likely a true funds-at-risk issue or a false positive? Why?"
    )
