"""Pinned Blend engine versions. CI installs these exact builds.

Ityfuzz is the fork-aware fuzzer. Halmos is symbolic. Medusa and Echidna
fuzz the same conservation harness. Pins are defensive-tool versions only.
"""

from __future__ import annotations

from typing import Any

# Four engines, one pin each. Do not float these to "latest".
PINNED: dict[str, dict[str, str]] = {
    "ityfuzz": {
        "version": "nightly-35b7f08962fdd0c2e02df7ef8a43164913d514d9",
        "asset": "ityfuzz_nightly_linux_amd64.tar.gz",
        "url": (
            "https://github.com/fuzzland/ityfuzz/releases/download/"
            "nightly-35b7f08962fdd0c2e02df7ef8a43164913d514d9/"
            "ityfuzz_nightly_linux_amd64.tar.gz"
        ),
    },
    "halmos": {
        "version": "0.3.3",
        "pip": "halmos==0.3.3",
    },
    "medusa": {
        "version": "1.5.1",
        "asset": "medusa-linux-x64.tar.gz",
        "url": "https://github.com/crytic/medusa/releases/download/v1.5.1/medusa-linux-x64.tar.gz",
    },
    "echidna": {
        "version": "2.4.0",
        "asset": "echidna-2.4.0-x86_64-linux.tar.gz",
        "url": (
            "https://github.com/crytic/echidna/releases/download/v2.4.0/"
            "echidna-2.4.0-x86_64-linux.tar.gz"
        ),
    },
}

BLEND_ENGINES = ("ityfuzz", "halmos", "medusa", "echidna")
# These three share one local anvil fork and a project directory.
FORK_ENGINES = ("medusa", "echidna", "ityfuzz")
# Symbolic execution does not take the anvil fork.
SYMBOLIC_ENGINES = ("halmos",)


def pin_version(engine: str) -> str:
    row = PINNED.get(engine) or {}
    return str(row.get("version") or "")


def pins_public() -> dict[str, Any]:
    """Versions only. Download URLs stay in CI, not in the receipt."""
    return {name: {"version": pin_version(name)} for name in BLEND_ENGINES}
