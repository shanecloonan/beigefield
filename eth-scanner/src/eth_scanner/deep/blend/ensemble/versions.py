"""Pins for the ensemble layers. Evidence tools only. Nothing here broadcasts.

Versions are the builds the installer requests. A tool that is not on PATH
is reported as skipped with that pin still recorded. Pins are not floated
to "latest".
"""

from __future__ import annotations

from typing import Any

# Static + abstract interpretation.
LAYER_PINS: dict[str, dict[str, str]] = {
    "slither": {
        "version": "0.11.6",
        "pip": "slither-analyzer==0.11.6",
        "upstream": "https://github.com/crytic/slither",
    },
    "aderyn": {
        "version": "0.6.8",
        "upstream": "https://github.com/Cyfrin/aderyn",
    },
    "pyrometer": {
        "version": "unreleased",
        "upstream": "https://github.com/nascentxyz/pyrometer",
        "install_note": (
            "No GitHub release or tag is published. The layer skips when the "
            "pyrometer binary is absent. Source-shape share-price facts still run."
        ),
    },
    # Spec / property instrumentation. npm latest is 0.7.10; 0.8.x is not published.
    "scribble": {
        "version": "0.7.10",
        "npm": "eth-scribble@0.7.10",
        "upstream": "https://github.com/ConsenSysDiligence/scribble",
    },
    "crytic-properties": {
        "version": "5ea14b8",
        "upstream": "https://github.com/crytic/properties",
    },
    # Symbolic, beside Halmos. solc's built-in SMTChecker (CHC + BMC).
    "smtchecker": {
        "version": "0.8.28",
        "upstream": "https://docs.soliditylang.org/en/latest/smtchecker.html",
    },
    # Foundry invariant fuzz, beside Ityfuzz / Medusa / Echidna.
    "foundry": {
        "version": "1.9.0",
        "upstream": "https://github.com/foundry-rs/foundry",
    },
    # Mutation of the instrumented property suite.
    "gambit": {
        "version": "1.0.6",
        "upstream": "https://github.com/Certora/gambit",
    },
}

LAYER_ORDER = (
    "facts",
    "spec",
    "symbolic",
    "fuzz",
    "mutation",
    "fusion",
)


def pin_version(name: str) -> str:
    return str((LAYER_PINS.get(name) or {}).get("version") or "")


def pins_public() -> dict[str, Any]:
    return {name: {"version": pin_version(name)} for name in LAYER_PINS}
