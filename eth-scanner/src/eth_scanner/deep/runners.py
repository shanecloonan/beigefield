"""Spawn static/symbolic engines. Skip if missing. Never send txs.

Binaries expected from owner forks (or PATH overrides via ETH_SCANNER_*_BIN).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from eth_scanner.deep.findings import EngineFinding, apply_agreement, dedupe_findings, make_finding
from eth_scanner.deep.parsers import parse_aderyn, parse_halmos, parse_mythril, parse_slither


@dataclass
class EngineRunResult:
    engine: str
    status: str  # ok | skipped | error
    findings: list[EngineFinding] = field(default_factory=list)
    note: str = ""
    duration_ms: int = 0


def _which(env_key: str, names: list[str]) -> Optional[str]:
    override = (os.environ.get(env_key) or "").strip()
    if override and Path(override).exists():
        return override
    for name in names:
        hit = shutil.which(name)
        if hit:
            return hit
    return None


def slither_bin() -> Optional[str]:
    return _which("ETH_SCANNER_SLITHER_BIN", ["slither"])


def aderyn_bin() -> Optional[str]:
    return _which("ETH_SCANNER_ADERYN_BIN", ["aderyn"])


def mythril_bin() -> Optional[str]:
    return _which("ETH_SCANNER_MYTHRIL_BIN", ["myth", "mythril"])


def halmos_bin() -> Optional[str]:
    return _which("ETH_SCANNER_HALMOS_BIN", ["halmos"])


def hevm_bin() -> Optional[str]:
    """hevm on PATH, or ETH_SCANNER_HEVM_BIN. The shortlist value check uses this."""
    return _which("ETH_SCANNER_HEVM_BIN", ["hevm"])


# Strong-candidate symbolic bounds. The light deep worker keeps its shorter default.
MYTHRIL_EXECUTION_TIMEOUT_S = 300
MYTHRIL_MAX_DEPTH = 22


def semgrep_bin() -> Optional[str]:
    return _which("ETH_SCANNER_SEMGREP_BIN", ["semgrep"])


def forge_bin() -> Optional[str]:
    return _which("ETH_SCANNER_FORGE_BIN", ["forge"])


def anvil_bin() -> Optional[str]:
    return _which("ETH_SCANNER_ANVIL_BIN", ["anvil"])


def medusa_bin() -> Optional[str]:
    return _which("ETH_SCANNER_MEDUSA_BIN", ["medusa"])


def echidna_bin() -> Optional[str]:
    return _which("ETH_SCANNER_ECHIDNA_BIN", ["echidna"])


def ityfuzz_bin() -> Optional[str]:
    return _which("ETH_SCANNER_ITYFUZZ_BIN", ["ityfuzz"])


def engine_availability() -> dict[str, bool]:
    return {
        "slither": bool(slither_bin()),
        "aderyn": bool(aderyn_bin()),
        "mythril": bool(mythril_bin()),
        "halmos": bool(halmos_bin()),
        "hevm": bool(hevm_bin()),
        "kontrol": _kontrol_present(),
        "semgrep": bool(semgrep_bin()),
        "forge": bool(forge_bin()),
        "anvil": bool(anvil_bin()),
        "medusa": bool(medusa_bin()),
        "echidna": bool(echidna_bin()),
        "ityfuzz": bool(ityfuzz_bin()),
        "wake": bool(_added("wake")),
        "heimdall": bool(_added("heimdall")),
        "panoramix": bool(_added("panoramix")),
    }


def _kontrol_present() -> bool:
    try:
        from eth_scanner.advanced.kontrol import kontrol_bin
        return bool(kontrol_bin())
    except Exception:  # noqa: BLE001
        return False


def _added(name: str) -> bool:
    try:
        from eth_scanner.deep.added_engines import added_availability
        return bool(added_availability().get(name))
    except Exception:  # noqa: BLE001
        return False


def _write_source_tree(source: str, contract_name: str = "Target") -> tempfile.TemporaryDirectory[str]:
    tmp = tempfile.TemporaryDirectory(prefix="eth-scanner-deep-")
    root = Path(tmp.name)
    # Minimal foundry-ish layout so Aderyn can walk it.
    (root / "src").mkdir(parents=True, exist_ok=True)
    sol = root / "src" / ("%s.sol" % (contract_name or "Target"))
    text = source if "pragma solidity" in source else (
        "// SPDX-License-Identifier: UNLICENSED\npragma solidity ^0.8.20;\n" + source
    )
    sol.write_text(text, encoding="utf-8")
    (root / "foundry.toml").write_text(
        '[profile.default]\nsrc = "src"\nout = "out"\nlibs = []\n',
        encoding="utf-8",
    )
    return tmp


def run_slither(source: str, *, timeout_s: int = 90, project_dir: Optional[str] = None, detect: str = "all") -> EngineRunResult:
    import time
    bin_path = slither_bin()
    if not bin_path:
        return EngineRunResult("slither", "skipped", note="slither not on PATH")
    t0 = time.time()

    def _run(target: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [bin_path, target, "--json", "-", "--detect", detect or "all", "--disable-color"],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            env=_scrub_env(),
        )

    try:
        if project_dir:
            proc = _run(project_dir)
        else:
            with _write_source_tree(source) as tmp:
                proc = _run(str(Path(tmp) / "src"))
    except subprocess.TimeoutExpired:
        return EngineRunResult("slither", "error", note="timed out after %ss" % timeout_s)
    except OSError as exc:
        return EngineRunResult("slither", "error", note=str(exc)[:200])
    raw = (proc.stdout or "") or (proc.stderr or "")
    findings = parse_slither(raw)
    return EngineRunResult(
        "slither",
        "ok",
        findings=findings,
        note="exit=%s findings=%d" % (proc.returncode, len(findings)),
        duration_ms=int((time.time() - t0) * 1000),
    )


def run_aderyn(source: str, *, timeout_s: int = 90, project_dir: Optional[str] = None) -> EngineRunResult:
    import time
    bin_path = aderyn_bin()
    if not bin_path:
        return EngineRunResult("aderyn", "skipped", note="aderyn not on PATH")
    t0 = time.time()

    def _run(folder: str) -> tuple[subprocess.CompletedProcess[str], str]:
        out_json = Path(folder) / "aderyn-report.json"
        proc = subprocess.run(
            [bin_path, folder, "--output", str(out_json)],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            env=_scrub_env(),
        )
        raw_out = out_json.read_text(encoding="utf-8") if out_json.exists() else (proc.stdout or "")
        return proc, raw_out

    try:
        if project_dir:
            proc, raw = _run(project_dir)
        else:
            with _write_source_tree(source) as tmp:
                proc, raw = _run(tmp)
    except subprocess.TimeoutExpired:
        return EngineRunResult("aderyn", "error", note="timed out after %ss" % timeout_s)
    except OSError as exc:
        return EngineRunResult("aderyn", "error", note=str(exc)[:200])
    findings = parse_aderyn(raw)
    return EngineRunResult(
        "aderyn",
        "ok",
        findings=findings,
        note="exit=%s findings=%d" % (proc.returncode, len(findings)),
        duration_ms=int((time.time() - t0) * 1000),
    )


def mythril_argv(
    bin_path: str,
    sol_path: str,
    *,
    timeout_s: int = 120,
    execution_timeout: Optional[int] = None,
    max_depth: Optional[int] = None,
) -> list[str]:
    """Bounded symbolic execution. No transaction broadcasting."""
    exe = int(execution_timeout) if execution_timeout is not None else min(60, int(timeout_s))
    cmd = [
        bin_path, "analyze", str(sol_path), "-o", "json",
        "--execution-timeout", str(max(1, exe)),
    ]
    if max_depth:
        cmd.extend(["--max-depth", str(int(max_depth))])
    return cmd


def run_mythril(
    source: str,
    *,
    timeout_s: int = 120,
    sol_path: Optional[str] = None,
    execution_timeout: Optional[int] = None,
    max_depth: Optional[int] = None,
) -> EngineRunResult:
    import time
    bin_path = mythril_bin()
    if not bin_path:
        return EngineRunResult("mythril", "skipped", note="mythril not on PATH")
    t0 = time.time()

    def _analyze(sol: Path) -> EngineRunResult:
        cmd = mythril_argv(
            bin_path, str(sol),
            timeout_s=timeout_s,
            execution_timeout=execution_timeout,
            max_depth=max_depth,
        )
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
                env=_tool_env(),
            )
        except subprocess.TimeoutExpired:
            return EngineRunResult("mythril", "error", note="timed out after %ss" % timeout_s)
        except OSError as exc:
            return EngineRunResult("mythril", "error", note=str(exc)[:200])
        raw = (proc.stdout or "") or (proc.stderr or "")
        findings = parse_mythril(raw)
        return EngineRunResult(
            "mythril",
            "ok",
            findings=findings,
            note="exit=%s findings=%d depth=%s exec_timeout=%s" % (
                proc.returncode, len(findings), max_depth, execution_timeout,
            ),
            duration_ms=int((time.time() - t0) * 1000),
        )

    if sol_path:
        return _analyze(Path(sol_path))
    with _write_source_tree(source) as tmp:
        sol = next((Path(tmp) / "src").glob("*.sol"), None)
        if sol is None:
            return EngineRunResult("mythril", "error", note="no .sol to analyze")
        return _analyze(sol)


def run_halmos(*, harness_dir: Optional[Path] = None, timeout_s: int = 120) -> EngineRunResult:
    """Halmos needs a Foundry check_* harness — skip unless ETH_SCANNER_HALMOS_HARNESS is set."""
    import time
    bin_path = halmos_bin()
    if not bin_path:
        return EngineRunResult("halmos", "skipped", note="halmos not on PATH")
    root = harness_dir or Path(os.environ.get("ETH_SCANNER_HALMOS_HARNESS") or "")
    if not root or not root.exists():
        return EngineRunResult(
            "halmos",
            "skipped",
            note="no Foundry check_* harness configured (set ETH_SCANNER_HALMOS_HARNESS)",
        )
    t0 = time.time()
    try:
        proc = subprocess.run(
            [bin_path, "test", "--root", str(root)],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            env=_scrub_env(),
            cwd=str(root),
        )
    except subprocess.TimeoutExpired:
        return EngineRunResult("halmos", "error", note="timed out after %ss" % timeout_s)
    except OSError as exc:
        return EngineRunResult("halmos", "error", note=str(exc)[:200])
    raw = (proc.stdout or "") + "\n" + (proc.stderr or "")
    findings = parse_halmos(raw)
    return EngineRunResult(
        "halmos",
        "ok",
        findings=findings,
        note="exit=%s findings=%d" % (proc.returncode, len(findings)),
        duration_ms=int((time.time() - t0) * 1000),
    )


def _deployed_hex(project: Path) -> str:
    out = project / "out"
    if not out.is_dir():
        return ""
    for path in sorted(out.rglob("*.json")):
        if "build-info" in path.parts:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        inner = payload.get("deployedBytecode") if isinstance(payload, dict) else None
        text = ""
        if isinstance(inner, dict):
            text = str(inner.get("object") or "")
        elif isinstance(inner, str):
            text = inner
        if text.startswith("0x") and len(text) > 10:
            return text
    return ""


def run_hevm_engine(project: str, *, timeout_s: int = 20) -> EngineRunResult:
    """Time-boxed hevm beside Halmos. A missing binary or a timeout is a skip or error, not heat."""
    import time
    exe = hevm_bin()
    if not exe:
        return EngineRunResult("hevm", "skipped", note="hevm not on PATH")
    code = _deployed_hex(Path(project))
    if not code:
        return EngineRunResult("hevm", "skipped", note="no deployed bytecode under out/")
    t0 = time.time()
    try:
        proc = subprocess.run(
            [exe, "symbolic", "--code", code, "--sig", "totalAssets()", "--smttimeout", "5000"],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return EngineRunResult(
            "hevm", "error", note="timed out after %ss" % timeout_s,
            duration_ms=int((time.time() - t0) * 1000),
        )
    except OSError as exc:
        return EngineRunResult("hevm", "error", note=str(exc)[:200])
    raw = ((proc.stdout or "") + "\n" + (proc.stderr or "")).lower()
    findings: list[EngineFinding] = []
    if "assertion violation" in raw or "vmfailure" in raw:
        finding = make_finding(
            engine="hevm",
            rule="symbolic",
            title="hevm reported a local failure",
            severity="info",
            confidence="low",
            evidence="hevm local failure; no caller profit",
        )
        finding.generic = True
        findings.append(finding)
    return EngineRunResult(
        "hevm",
        "ok",
        findings=findings,
        note="exit=%s" % proc.returncode,
        duration_ms=int((time.time() - t0) * 1000),
    )


def run_all_engines(
    source: str,
    *,
    engines: Optional[list[str]] = None,
    timeout_s: int = 90,
) -> tuple[list[EngineFinding], list[EngineRunResult]]:
    """Run selected engines; return deduped+agreement findings and per-engine status."""
    wanted = [e.lower() for e in (engines or ["slither", "aderyn", "mythril", "halmos"])]
    results: list[EngineRunResult] = []
    if "slither" in wanted:
        results.append(run_slither(source, timeout_s=timeout_s))
    if "aderyn" in wanted:
        results.append(run_aderyn(source, timeout_s=timeout_s))
    if "mythril" in wanted:
        results.append(run_mythril(source, timeout_s=timeout_s))
    if "halmos" in wanted:
        results.append(run_halmos(timeout_s=timeout_s))

    merged: list[EngineFinding] = []
    for r in results:
        merged.extend(r.findings)
    merged = apply_agreement(dedupe_findings(merged))
    return merged, results


def semgrep_argv(bin_path: str, project_dir: str, *, rules_dir: str = "") -> list[str]:
    """Solidity rulesets. Metrics off. No autofix, no network exploit payload."""
    cmd = [
        bin_path, "--metrics=off", "--disable-version-check",
        "--quiet", "--json", "--error",
        "--config", "p/solidity",
    ]
    if rules_dir:
        cmd.extend(["--config", rules_dir])
    cmd.append(project_dir)
    return cmd


def forge_fuzz_argv(bin_path: str, *, fork_url: str = "") -> list[str]:
    """Existing Phase B mock/invariant suite. Fork URL is read-only state."""
    cmd = [bin_path, "test", "--match-path", "test/*", "-q", "--no-match-path", "script/*"]
    if fork_url:
        cmd.extend(["--fork-url", fork_url])
    return cmd


def run_semgrep(project_dir: str, *, timeout_s: int = 120, rules_dir: str = "") -> EngineRunResult:
    import time
    bin_path = semgrep_bin()
    if not bin_path:
        return EngineRunResult("semgrep", "skipped", note="semgrep not on PATH")
    rules = rules_dir or (os.environ.get("ETH_SCANNER_SEMGREP_RULES") or "")
    t0 = time.time()
    cmd = semgrep_argv(bin_path, project_dir, rules_dir=rules)
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_s, check=False, env=_tool_env(),
        )
    except subprocess.TimeoutExpired:
        return EngineRunResult("semgrep", "error", note="timed out after %ss" % timeout_s)
    except OSError as exc:
        return EngineRunResult("semgrep", "error", note=str(exc)[:200])
    findings = _parse_semgrep((proc.stdout or "") or (proc.stderr or ""))
    return EngineRunResult(
        "semgrep", "ok", findings=findings,
        note="exit=%s findings=%d" % (proc.returncode, len(findings)),
        duration_ms=int((time.time() - t0) * 1000),
    )


def run_slither_printers(project_dir: str, *, timeout_s: int = 60) -> EngineRunResult:
    """Admin/role printers. Output is evidence, not a heat input."""
    import time
    from eth_scanner.deep.findings import EngineFinding, sanitize_evidence
    bin_path = slither_bin()
    if not bin_path:
        return EngineRunResult("slither-printers", "skipped", note="slither not on PATH")
    t0 = time.time()
    try:
        proc = subprocess.run(
            [bin_path, project_dir, "--print", "vars-and-auth,human-summary", "--disable-color"],
            capture_output=True, text=True, timeout=timeout_s, check=False, env=_tool_env(),
        )
    except subprocess.TimeoutExpired:
        return EngineRunResult("slither-printers", "error", note="timed out after %ss" % timeout_s)
    except OSError as exc:
        return EngineRunResult("slither-printers", "error", note=str(exc)[:200])
    text = sanitize_evidence((proc.stdout or "") + "\n" + (proc.stderr or ""))
    findings = []
    if text:
        findings.append(EngineFinding(
            id="slither-printers:vars-and-auth",
            engine="slither-printers",
            rule="vars-and-auth",
            title="Slither admin/role printer",
            severity="info",
            confidence="low",
            funds_class="access-control",
            evidence=text,
            generic=True,
        ))
    return EngineRunResult(
        "slither-printers", "ok", findings=findings,
        note="exit=%s" % proc.returncode,
        duration_ms=int((time.time() - t0) * 1000),
    )


def run_property_fuzz(
    *,
    fork_url: str = "",
    timeout_s: int = 180,
    suite_dir: Optional[Path] = None,
) -> EngineRunResult:
    """Foundry/Medusa/Echidna on the existing invariant suite.

    A fork URL is passed only to anvil/forge as read-only state. This never
    broadcasts a transaction and never builds an attack script.
    """
    import time
    from eth_scanner.deep.findings import EngineFinding, sanitize_evidence
    root = suite_dir or Path(__file__).resolve().parents[3] / "research" / "fuzz"
    if not (root / "foundry.toml").is_file():
        return EngineRunResult("forge-fuzz", "skipped", note="invariant suite missing")
    forge = forge_bin()
    if not forge:
        return EngineRunResult("forge-fuzz", "skipped", note="forge not on PATH")
    t0 = time.time()
    notes: list[str] = []
    anvil_proc = None
    local_fork = ""
    try:
        if fork_url and anvil_bin():
            anvil_proc, local_fork = _start_anvil(fork_url)
            if local_fork:
                notes.append("anvil fork (local, no broadcast)")
        url = local_fork or (fork_url if fork_url and not anvil_proc else "")
        cmd = forge_fuzz_argv(forge, fork_url=url)
        try:
            proc = subprocess.run(
                cmd, cwd=str(root), capture_output=True, text=True,
                timeout=timeout_s, check=False, env=_tool_env(),
            )
        except subprocess.TimeoutExpired:
            return EngineRunResult("forge-fuzz", "error", note="forge timed out after %ss" % timeout_s)
        text = (proc.stdout or "") + "\n" + (proc.stderr or "")
        notes.append("forge exit=%s" % proc.returncode)
        findings: list[EngineFinding] = []
        if proc.returncode not in {0}:
            failed = re_fail_names(text)
            findings.append(EngineFinding(
                id="forge-fuzz:suite",
                engine="forge-fuzz",
                rule="invariant-suite",
                title="Foundry invariant suite reported a failure",
                severity="medium",
                confidence="low",
                funds_class="invariant-violation",
                evidence=sanitize_evidence(
                    "mock/fork suite only; not a live confirmation. "
                    + (", ".join(failed) if failed else "see elided log")
                ),
                generic=True,
            ))
        extra = _optional_fuzz_bins(root, timeout_s=min(90, timeout_s))
        notes.extend(extra)
        return EngineRunResult(
            "forge-fuzz", "ok", findings=findings,
            note="; ".join(notes)[:300],
            duration_ms=int((time.time() - t0) * 1000),
        )
    finally:
        if anvil_proc is not None:
            anvil_proc.kill()
            try:
                anvil_proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                pass


def re_fail_names(text: str) -> list[str]:
    import re
    return re.findall(r"\[FAIL[^\]]*\]\s+([A-Za-z0-9_]+)", text)[:8]


def _start_anvil(fork_url: str):
    """Local fork only. No unlocked production keys, no broadcast."""
    import socket
    bin_path = anvil_bin()
    if not bin_path or not fork_url:
        return None, ""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    proc = subprocess.Popen(
        [bin_path, "--fork-url", fork_url, "--port", str(port), "--silent"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=_tool_env(),
    )
    url = "http://127.0.0.1:%d" % port
    import time
    for _ in range(20):
        if proc.poll() is not None:
            return None, ""
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return proc, url
        except OSError:
            time.sleep(0.25)
    proc.kill()
    return None, ""


def _optional_fuzz_bins(root: Path, *, timeout_s: int) -> list[str]:
    """Medusa and Echidna run as their own deep-lane engines."""
    del root, timeout_s
    return []


def _run_named(bin_path: str, args: list[str], root: Path, timeout_s: int, label: str) -> str:
    try:
        proc = subprocess.run(
            [bin_path, *args], cwd=str(root), capture_output=True, text=True,
            timeout=timeout_s, check=False, env=_tool_env(),
        )
    except subprocess.TimeoutExpired:
        return "%s timeout" % label
    except OSError as exc:
        return "%s error %s" % (label, str(exc)[:80])
    return "%s exit=%s" % (label, proc.returncode)


def _parse_semgrep(raw: str) -> list:
    import json
    from eth_scanner.deep.findings import EngineFinding, normalize_severity, sanitize_evidence
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return []
    out = []
    for row in (data.get("results") or [])[:40]:
        extra = row.get("extra") or {}
        rule = str(row.get("check_id") or "semgrep")
        start = (row.get("start") or {})
        out.append(EngineFinding(
            id="semgrep:%s:%s" % (rule, start.get("line") or 0),
            engine="semgrep",
            rule=rule.split(".")[-1][:80],
            title=str(extra.get("message") or rule)[:180],
            severity=normalize_severity(extra.get("severity") or "info"),
            confidence="low",
            funds_class="other",
            file=str(row.get("path") or "") or None,
            line=int(start["line"]) if str(start.get("line") or "").isdigit() else None,
            evidence=sanitize_evidence(extra.get("lines") or extra.get("message") or ""),
            generic=True,
        ))
    return out


def _scrub_env() -> dict[str, str]:
    """Drop secrets from child env — engines only need PATH/HOME/TMP."""
    return _tool_env()


def _tool_env() -> dict[str, str]:
    """Child env for engines. Keeps certs and toolchain paths. No private keys."""
    keep_prefix = ("SSL_", "REQUESTS_", "PYTHON", "LC_", "SEMGREP_")
    drop = {"ETH_RPC_URL", "SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY", "ETHERSCAN_API_KEYS"}
    out: dict[str, str] = {}
    for key, value in os.environ.items():
        if key in drop or "KEY" in key or "TOKEN" in key or "SECRET" in key:
            continue
        if key.startswith(keep_prefix) or key in {
            "PATH", "HOME", "TMPDIR", "TMP", "TEMP", "LANG", "TERM",
            "USER", "LOGNAME", "SHELL", "XDG_CACHE_HOME", "LOCALAPPDATA",
            "FOUNDRY_DIR", "FOUNDRY_PROFILE",
            "ETH_SCANNER_SLITHER_BIN", "ETH_SCANNER_ADERYN_BIN",
            "ETH_SCANNER_MYTHRIL_BIN", "ETH_SCANNER_HALMOS_BIN",
            "ETH_SCANNER_HALMOS_HARNESS", "ETH_SCANNER_SEMGREP_BIN",
            "ETH_SCANNER_SEMGREP_RULES", "ETH_SCANNER_FORGE_BIN",
            "ETH_SCANNER_ANVIL_BIN", "ETH_SCANNER_MEDUSA_BIN",
            "ETH_SCANNER_ECHIDNA_BIN",
        }:
            out[key] = value
    out.setdefault("PATH", os.environ.get("PATH", ""))
    out.setdefault("FOUNDRY_PROFILE", "default")
    return out
