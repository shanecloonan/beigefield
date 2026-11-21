"""Decompile fallback stubs (Heimdall / Panoramix).

Hypothesis generators only. Always `src_confidence=low`. Never proof of
safety or theft. If neither CLI is present, still return a low-confidence
stub so the funnel routes to manual-review.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from eth_scanner.types import SourceArtifact


FUNDS_FLOOR_USD = 100.0


def decompile_unverified_funded(
    address: str,
    *,
    funds_usd: float | None,
    verified: bool = False,
    bytecode: str = "",
    floor_usd: float = FUNDS_FLOOR_USD,
    heimdall=None,
    panoramix=None,
) -> dict:
    """Decompile only an unverified contract at or above the funds floor.

    The result is always lower confidence. It adds no heat. A missing
    Heimdall CLI falls through to Panoramix, and a missing Panoramix CLI
    returns an empty stub.
    """
    base = {
        "address": address,
        "src_confidence": "low",
        "lower_confidence": True,
        "heat_contribution": 0,
        "tool": "none",
        "content": "",
        "ran": False,
    }
    if verified:
        base["skipped"] = "verified"
        base["note"] = "Verified source is kept. Decompilation is not run."
        return base
    if funds_usd is None or funds_usd < floor_usd:
        base["skipped"] = "unfunded"
        base["note"] = "Below the funds floor. Decompilation is not run."
        return base
    text = _from_runner(heimdall, address, bytecode) if heimdall is not None else _try_heimdall(address, bytecode)[0]
    tool = "heimdall" if text else ""
    if not text:
        text = _from_runner(panoramix, address, bytecode) if panoramix is not None else _try_panoramix(address, bytecode)[0]
        tool = "panoramix" if text else "none"
    base["ran"] = True
    base["tool"] = tool
    base["content"] = (text or "")[:200_000]
    if tool == "none":
        base["skipped"] = "no-tool"
        base["note"] = "Heimdall and Panoramix are not available. The stub stays low confidence."
    else:
        base["skipped"] = None
        base["note"] = "Decompiled with %s. This is lower confidence than verified source and adds no heat." % tool
    return base


def _from_runner(runner, address: str, bytecode: str) -> str | None:
    try:
        out = runner(address, bytecode)
    except Exception:  # noqa: BLE001 — a tool failure falls through
        return None
    text = (out or "").strip() if isinstance(out, str) else ""
    return text or None


def decompile(address: str, bytecode: str = "") -> SourceArtifact:
    notes = [
        "Decompile is a hypothesis generator only — never proof.",
        "src_confidence=low forces the manual-review bucket (Do Not Auto-Dismiss).",
    ]
    text, tool = _try_heimdall(address, bytecode)
    if text is None:
        text, tool = _try_panoramix(address, bytecode)
    if text is None:
        notes.append("heimdall/panoramix CLI not present or failed; empty decompile stub")
        tool = "none"
        text = ""
    else:
        notes.append("used %s CLI; treat output as untrusted IR input" % tool)
    return SourceArtifact(
        kind="decompile",
        language="unknown",
        content=text,
        src_confidence="low",
        verified_match="none",
        tool=tool,
        notes=notes,
    )


def _try_heimdall(address: str, bytecode: str) -> tuple[str | None, str]:
    exe = shutil.which("heimdall")
    if not exe:
        return None, "heimdall"
    try:
        if bytecode and bytecode not in ("0x", "0x0"):
            with tempfile.TemporaryDirectory(prefix="eth-scanner-heimdall-") as tmp:
                hex_path = Path(tmp) / "code.hex"
                hex_path.write_text(bytecode.replace("0x", ""), encoding="utf-8")
                proc = subprocess.run(
                    [exe, "decompile", str(hex_path), "-o", tmp],
                    capture_output=True, text=True, timeout=45, check=False,
                )
                out = (proc.stdout or "").strip() or _first_text(Path(tmp))
                if out:
                    return out[:200_000], "heimdall"
        proc = subprocess.run(
            [exe, "decompile", address],
            capture_output=True, text=True, timeout=45, check=False,
        )
        out = (proc.stdout or "").strip()
        return (out[:200_000], "heimdall") if out else (None, "heimdall")
    except (OSError, subprocess.TimeoutExpired):
        return None, "heimdall"


def _try_panoramix(address: str, bytecode: str) -> tuple[str | None, str]:
    exe = shutil.which("panoramix") or shutil.which("panoramix.py")
    if not exe:
        return None, "panoramix"
    try:
        target = bytecode if bytecode and bytecode not in ("0x", "0x0") else address
        proc = subprocess.run(
            [exe, target],
            capture_output=True, text=True, timeout=45, check=False,
        )
        out = (proc.stdout or "").strip()
        return (out[:200_000], "panoramix") if out else (None, "panoramix")
    except (OSError, subprocess.TimeoutExpired):
        return None, "panoramix"


def _first_text(folder: Path) -> str:
    for p in folder.rglob("*"):
        if p.is_file() and p.suffix in {".sol", ".vy", ".txt", ".md"}:
            try:
                return p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
    return ""
