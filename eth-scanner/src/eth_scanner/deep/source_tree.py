"""Write a verified Etherscan project so engines compile the real sources.

Multi-file Standard JSON keeps compiler settings and remappings. Paths are
stripped of `..` so a verified payload cannot escape the work directory.
Read-only. No network.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from eth_scanner.ingest.unpack import (
    _loads_etherscan_json,
    parse_etherscan_sources,
    safe_relpath,
    unpack_to_dir,
)
from eth_scanner.types import SourceArtifact

_SOLC_RE = re.compile(r"(\d+\.\d+\.\d+)")


def solc_version_of(compiler: Optional[str]) -> str:
    match = _SOLC_RE.search(compiler or "")
    return match.group(1) if match else ""


def compiler_settings(raw: str) -> dict[str, Any]:
    data = _loads_etherscan_json(raw or "")
    if not isinstance(data, dict):
        return {}
    settings = data.get("settings") if isinstance(data.get("settings"), dict) else {}
    remappings: list[str] = []
    for item in settings.get("remappings") or []:
        text = str(item).strip()
        if not text or ".." in text:
            continue
        remappings.append(text)
    optimizer = settings.get("optimizer") if isinstance(settings.get("optimizer"), dict) else {}
    return {
        "remappings": remappings,
        "optimizer": bool(optimizer.get("enabled")),
        "optimizer_runs": int(optimizer.get("runs") or 200),
        "evm_version": str(settings.get("evmVersion") or "") or None,
        "via_ir": bool(settings.get("viaIR")),
    }


def write_verified_project(artifact: SourceArtifact, root: Path) -> dict[str, Any]:
    """Materialize sources + foundry.toml. Returns compiler metadata."""
    root.mkdir(parents=True, exist_ok=True)
    raw = artifact.content or ""
    files = parse_etherscan_sources(raw)
    single = False
    if not files:
        single = True
        name = safe_relpath((artifact.contract_name or "Target") + ".sol")
        if not name.lower().endswith((".sol", ".vy")):
            name += ".sol"
        files = {"src/%s" % name: raw}
    unpack_to_dir(files, root)
    meta = compiler_settings(raw)
    solc = solc_version_of(artifact.compiler)
    _write_foundry_toml(root, meta, solc, src="." if not single else "src")
    if meta["remappings"]:
        (root / "remappings.txt").write_text(
            "\n".join(meta["remappings"]) + "\n",
            encoding="utf-8",
        )
    primary = _primary_file(root, files, artifact.contract_name)
    return {
        "solc": solc,
        "compiler": artifact.compiler,
        "contract_name": artifact.contract_name,
        "remappings": list(meta["remappings"]),
        "files": len(files),
        "primary": str(primary) if primary else "",
        "language": artifact.language,
    }


def _primary_file(root: Path, files: dict[str, str], contract_name: Optional[str]) -> Optional[Path]:
    name = (contract_name or "").strip()
    candidates = [root / safe_relpath(rel) for rel in files]
    if name:
        for path in candidates:
            if path.stem == name and path.is_file():
                return path
    sols = [p for p in candidates if p.suffix == ".sol" and p.is_file()]
    if not sols:
        return candidates[0] if candidates and candidates[0].is_file() else None
    return max(sols, key=lambda p: p.stat().st_size)


def _write_foundry_toml(root: Path, meta: dict[str, Any], solc: str, *, src: str) -> None:
    lines = [
        "[profile.default]",
        'src = "%s"' % src,
        'out = "out"',
        'libs = ["lib"]',
        "optimizer = %s" % ("true" if meta.get("optimizer") else "false"),
        "optimizer_runs = %d" % int(meta.get("optimizer_runs") or 200),
        "ffi = false",
    ]
    if solc:
        lines.append('solc = "%s"' % solc)
    if meta.get("evm_version"):
        lines.append('evm_version = "%s"' % meta["evm_version"])
    if meta.get("via_ir"):
        lines.append("via_ir = true")
    remappings = meta.get("remappings") or []
    if remappings:
        quoted = ", ".join('"%s"' % r.replace('"', "") for r in remappings)
        lines.append("remappings = [%s]" % quoted)
    (root / "foundry.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
