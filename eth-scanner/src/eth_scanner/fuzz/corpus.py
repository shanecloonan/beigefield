"""Plan an Actions cache for Echidna, Medusa, and ityfuzz seeds.

The key is ``fuzz-corpus-<engine>-<hash>-<run_id>``. The restore prefix
drops the run id, so a later run can resume from the newest seeds for
that source. The tools are not started here. Heat stays 0.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Optional

ENGINES = ("echidna", "medusa", "ityfuzz")
_RUN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SEED = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")

DEFAULT_SOURCE = (
    "contract Properties {\n"
    "    function echidna_true() public pure returns (bool) {\n"
    "        return true;\n"
    "    }\n"
    "}\n"
)


def code_hash(source: str) -> str:
    """SHA-256 of the source. Whitespace at the ends does not change it."""
    text = (source or "").strip().encode("utf-8")
    return hashlib.sha256(text).hexdigest()


def _run_id(value: str) -> Optional[str]:
    token = (value or "").strip() or "local"
    if ".." in token or not _RUN.match(token):
        return None
    return token


def cache_key(engine: str, digest: str, run_id: str) -> str:
    return "fuzz-corpus-%s-%s-%s" % (engine, digest, run_id)


def restore_prefix(engine: str, digest: str) -> str:
    return "fuzz-corpus-%s-%s-" % (engine, digest)


def corpus_dir(dest: Path, engine: str, digest: str) -> Path:
    return dest / engine / digest


def write_seed(dest: Path, engine: str, digest: str, name: str, payload: bytes) -> Path:
    """Place one seed under the corpus directory. Names cannot escape it."""
    if engine not in ENGINES:
        raise ValueError("unknown engine")
    if not _SEED.match(name) or ".." in name:
        raise ValueError("seed name")
    folder = corpus_dir(dest, engine, digest)
    folder.mkdir(parents=True, exist_ok=True)
    target = (folder / name).resolve()
    if target.parent != folder.resolve():
        raise ValueError("seed path")
    target.write_bytes(payload)
    return target


def seed_names(dest: Path, engine: str, digest: str) -> list[str]:
    folder = corpus_dir(dest, engine, digest)
    if not folder.is_dir():
        return []
    names = []
    for path in folder.iterdir():
        if path.is_file() and _SEED.match(path.name) and ".." not in path.name:
            names.append(path.name)
    return sorted(names)


def plan_corpus(
    source: str,
    *,
    run_id: str = "local",
    dest: Optional[Path] = None,
) -> dict[str, Any]:
    """Name the cache slots. A bad run id is refused and no directory is written."""
    token = _run_id(run_id)
    report: dict[str, Any] = {
        "status": "skipped",
        "run_id": token or "",
        "code_hash": "",
        "engines": {},
        "fuzz_corpus": False,
        "heat_contribution": 0,
        "note": "",
    }
    if token is None:
        report["status"] = "refused"
        report["note"] = "Run id must be a short token. No corpus directory was written."
        return report
    if not (source or "").strip():
        report["note"] = "Source is required to name a corpus."
        return report
    digest = code_hash(source)
    report["code_hash"] = digest
    engines: dict[str, dict[str, str]] = {}
    for engine in ENGINES:
        key = cache_key(engine, digest, token)
        prefix = restore_prefix(engine, digest)
        engines[engine] = {
            "key": key,
            "restore": prefix,
            "path": "%s/%s" % (engine, digest),
        }
        if dest is not None:
            corpus_dir(dest, engine, digest).mkdir(parents=True, exist_ok=True)
    report["engines"] = engines
    if dest is not None:
        payload = {
            "code_hash": digest,
            "run_id": token,
            "engines": engines,
            "heat_contribution": 0,
            "note": "Seeds stay in the Actions cache. They are not committed.",
        }
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "plan.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        report["files"] = ["plan.json"]
    report["status"] = "ok"
    report["fuzz_corpus"] = True
    report["note"] = (
        "Cache key fuzz-corpus-<engine>-<hash>-<run_id>. "
        "The restore prefix drops the run id. Fuzzers are not started. Heat stays 0."
    )
    return report


def github_output(report: dict[str, Any]) -> str:
    """One line per key for ``$GITHUB_OUTPUT``. No source and no seed bytes."""
    lines = []
    engines = report.get("engines") or {}
    for engine in ENGINES:
        row = engines.get(engine) or {}
        lines.append("%s_key=%s" % (engine, row.get("key") or ""))
        lines.append("%s_restore=%s" % (engine, row.get("restore") or ""))
        lines.append("%s_path=fuzz-corpus/%s" % (engine, row.get("path") or engine))
    return "\n".join(lines) + "\n"


def public_report(report: dict[str, Any]) -> dict[str, Any]:
    """Fields safe to print. Source text is not one of them."""
    engines = report.get("engines") or {}
    return {
        "status": report.get("status"),
        "code_hash": report.get("code_hash"),
        "run_id": report.get("run_id"),
        "keys": {name: (engines.get(name) or {}).get("key") for name in ENGINES},
        "restore_keys": {name: (engines.get(name) or {}).get("restore") for name in ENGINES},
        "fuzz_corpus": bool(report.get("fuzz_corpus")),
        "heat": 0,
        "heat_breakdown": {"fuzz_corpus": bool(report.get("fuzz_corpus"))},
        "note": report.get("note"),
    }
