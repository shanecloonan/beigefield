"""Record that a protocol names a bridge.

A role or a source word of bridge, inbox, outbox, or messenger is a
witness. The note stores the name only. It does not build a call and
it adds no heat.
"""

from __future__ import annotations

import re
from typing import Any

_ROLES = {"bridge", "inbox", "outbox", "messenger"}
_WORD = re.compile(r"\b(bridge|inbox|outbox|messenger)\b", re.I)


def bridge_note(roles: list[str], source: str = "") -> dict[str, Any]:
    kept = sorted({str(role or "").strip().lower() for role in roles or []} & _ROLES)
    names = sorted({match.group(1).lower() for match in _WORD.finditer(source or "")})
    if not kept and not names:
        return {
            "status": "skipped",
            "reason": "no bridge name",
            "roles": [],
            "names": [],
            "heat_contribution": 0,
        }
    return {
        "status": "ok",
        "reason": "",
        "roles": kept,
        "names": names,
        "heat_contribution": 0,
        "note": "A bridge name is a witness. No call is built and heat stays 0.",
    }
