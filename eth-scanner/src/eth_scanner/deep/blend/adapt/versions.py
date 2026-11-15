"""Reference pins for the adaptation layer.

These are the upstream revisions the Python transfers were checked against.
The scanner does not install or run those projects. CI prints this table.
"""

from __future__ import annotations

ADAPTATION_PINS = {
    "syzkaller": {
        "version": "819ebe34df0f",
        "upstream": "https://github.com/google/syzkaller",
    },
    "restler": {
        "version": "v9.3.1",
        "upstream": "https://github.com/microsoft/restler-fuzzer",
    },
    "daikon": {
        "version": "v5.9.0",
        "upstream": "https://github.com/codespecs/daikon",
    },
    "lithium": {
        "version": "v4.0.0",
        "upstream": "https://github.com/MozillaSecurity/lithium",
    },
    "creduce": {
        "version": "31e855e29097",
        "upstream": "https://github.com/csmith-project/creduce",
    },
    "jepsen": {
        "version": "v0.3.15",
        "upstream": "https://github.com/jepsen-io/jepsen",
    },
    "randoop": {
        "version": "v4.3.4",
        "upstream": "https://github.com/randoop/randoop",
    },
    "learnlib": {
        "version": "0.16.0",
        "upstream": "https://github.com/LearnLib/learnlib",
    },
    "stateright": {
        "version": "v0.30.0",
        "upstream": "https://github.com/stateright/stateright",
    },
    "pict": {
        "version": "v3.7.4",
        "upstream": "https://github.com/microsoft/pict",
    },
    "openspiel": {
        "version": "v1.5",
        "upstream": "https://github.com/google-deepmind/open_spiel",
    },
    "picire": {
        "version": "21.8",
        "upstream": "https://github.com/renatahodovan/picire",
    },
    "picireny": {
        "version": "21.8",
        "upstream": "https://github.com/renatahodovan/picireny",
    },
}


def pin_version(name: str) -> str:
    return str((ADAPTATION_PINS.get(name) or {}).get("version") or "")
