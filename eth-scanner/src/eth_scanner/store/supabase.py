"""Queue + results persistence.

Remote writes use the Supabase service-role key (server-side only).
When the key is absent, a local JSON store under work/ is used (dry-run).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Protocol

from eth_scanner.config import Settings
from eth_scanner.types import FunnelResult, SourceArtifact, Target, to_plain


def normalize_address(addr: str) -> str:
    a = (addr or "").strip().lower()
    if not a.startswith("0x"):
        a = "0x" + a
    if len(a) != 42 or any(c not in "0123456789abcdef" for c in a[2:]):
        raise ValueError("invalid Ethereum address: %s" % addr)
    return a


class ScanStore(Protocol):
    def upsert_target(self, target: Target) -> Target: ...
    def get_target(self, address: str) -> Optional[dict[str, Any]]: ...
    def closed_no_hashes(self) -> set[str]: ...
    def save_artifact(self, address: str, kind: str, payload: dict[str, Any], confidence: str) -> None: ...
    def save_result(self, address: str, result: FunnelResult) -> None: ...
    def claim_pending(self, limit: int, worker_id: str) -> list[dict[str, Any]]: ...
    def claim_lane_b(self, limit: int, worker_id: str) -> list[dict[str, Any]]: ...
    def list_targets(self, bucket: Optional[str] = None, limit: int = 200) -> list[dict[str, Any]]: ...
    def list_results(self, address: Optional[str] = None, limit: int = 200) -> list[dict[str, Any]]: ...
    def list_artifacts(self, address: Optional[str] = None, kind: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]: ...


class MemoryStore:
    """In-process + optional JSONL under work/ for dry-run."""

    def __init__(self, work_dir: Optional[Path] = None):
        self.work_dir = work_dir
        self.targets: dict[str, dict[str, Any]] = {}
        self.artifacts: list[dict[str, Any]] = []
        self.results: list[dict[str, Any]] = []
        if work_dir:
            work_dir.mkdir(parents=True, exist_ok=True)
            self._load()

    def upsert_target(self, target: Target) -> Target:
        addr = normalize_address(target.address)
        target.address = addr
        now = _now()
        prev = self.targets.get(addr, {})
        row = {
            "address": addr,
            "bytecode_hash": target.bytecode_hash,
            "tvl_usd": target.tvl_usd,
            "status": target.status,
            "src_confidence": None,
            "ir_confidence": None,
            "heat": 0,
            "bucket": None,
            "funds_usd": target.funds_usd,
            "funds_breakdown": list(target.funds_breakdown or []),
            "funds_status": target.funds_status,
            "funds_checked_at": target.funds_checked_at,
            "claimed_by": prev.get("claimed_by"),
            "claimed_at": prev.get("claimed_at"),
            "updated_at": now,
            "created_at": prev.get("created_at") or now,
        }
        row.update({k: v for k, v in prev.items() if v is not None and k not in {"updated_at"}})
        row["bytecode_hash"] = target.bytecode_hash or prev.get("bytecode_hash")
        row["tvl_usd"] = target.tvl_usd if target.tvl_usd is not None else prev.get("tvl_usd")
        row["status"] = target.status or prev.get("status") or "pending"
        if target.funds_usd is not None:
            row["funds_usd"] = target.funds_usd
        if target.funds_breakdown:
            row["funds_breakdown"] = list(target.funds_breakdown)
        if target.funds_status:
            row["funds_status"] = target.funds_status
        if target.funds_checked_at:
            row["funds_checked_at"] = target.funds_checked_at
        self.targets[addr] = row
        self._flush()
        return target

    def get_target(self, address: str) -> Optional[dict[str, Any]]:
        return self.targets.get(normalize_address(address))

    def closed_no_hashes(self) -> set[str]:
        out: set[str] = set()
        for row in self.targets.values():
            if row.get("bucket") == "human-no-candidate" and row.get("bytecode_hash"):
                # Human-stamped no is represented as status=done + that bucket.
                if row.get("status") == "done":
                    out.add(row["bytecode_hash"])
        return out

    def save_artifact(self, address: str, kind: str, payload: dict[str, Any], confidence: str) -> None:
        addr = normalize_address(address)
        self.artifacts.append({
            "id": str(uuid.uuid4()),
            "address": addr,
            "kind": kind,
            "path_or_json": payload,
            "confidence": confidence,
            "created_at": _now(),
        })
        self._flush()

    def save_result(self, address: str, result: FunnelResult) -> None:
        addr = normalize_address(address)
        row = {
            "id": str(uuid.uuid4()),
            "address": addr,
            "bucket": result.bucket,
            "heat": result.heat,
            "stage_trace": to_plain(result.stage_trace),
            "hypotheses": to_plain(result.hypotheses),
            "notes": "\n".join(result.notes),
            "value_movers": list(result.value_movers),
            "contract_class": result.contract_class,
            "scope": result.scope,
            "src_confidence": result.src_confidence,
            "ir_confidence": result.ir_confidence,
            "dropped": result.dropped,
            "drop_reason": result.drop_reason,
            "funds_usd": result.funds_usd,
            "funds_breakdown": list(result.funds_breakdown or []),
            "funds_status": result.funds_status,
            "funds_checked_at": result.funds_checked_at,
            "created_at": _now(),
        }
        self.results.append(row)
        tgt = self.targets.setdefault(addr, {"address": addr, "created_at": _now()})
        tgt["bucket"] = result.bucket
        tgt["heat"] = result.heat
        tgt["src_confidence"] = result.src_confidence
        tgt["ir_confidence"] = result.ir_confidence
        tgt["status"] = "skipped" if result.dropped else "done"
        if result.funds_usd is not None:
            tgt["funds_usd"] = result.funds_usd
            tgt["tvl_usd"] = result.funds_usd if tgt.get("tvl_usd") is None else tgt.get("tvl_usd")
        if result.funds_breakdown:
            tgt["funds_breakdown"] = list(result.funds_breakdown)
        if result.funds_status:
            tgt["funds_status"] = result.funds_status
        if result.funds_checked_at:
            tgt["funds_checked_at"] = result.funds_checked_at
        tgt["updated_at"] = _now()
        self._flush()

    def claim_pending(self, limit: int, worker_id: str) -> list[dict[str, Any]]:
        claimed: list[dict[str, Any]] = []
        now = _now()
        for row in self.targets.values():
            if row.get("status") != "pending":
                continue
            row["status"] = "running"
            row["claimed_by"] = worker_id
            row["claimed_at"] = now
            claimed.append(dict(row))
            if len(claimed) >= limit:
                break
        self._flush()
        return claimed

    def claim_lane_b(self, limit: int, worker_id: str) -> list[dict[str, Any]]:
        claimed: list[dict[str, Any]] = []
        now = _now()
        for row in self.targets.values():
            if row.get("bucket") not in {"lane-b-queue", "manual-review"}:
                continue
            if row.get("status") == "running" and row.get("claimed_by") != worker_id:
                continue
            row["status"] = "running"
            row["claimed_by"] = worker_id
            row["claimed_at"] = now
            claimed.append(dict(row))
            if len(claimed) >= limit:
                break
        self._flush()
        return claimed

    def claim_deep(self, limit: int, worker_id: str) -> list[dict[str, Any]]:
        """Claim lane-b / manual-review rows that still need Phase A deep engines."""
        claimed: list[dict[str, Any]] = []
        now = _now()
        for row in self.targets.values():
            if row.get("bucket") not in {"lane-b-queue", "manual-review"}:
                continue
            if row.get("deep_status") in {"done", "running"}:
                continue
            if row.get("status") == "running" and row.get("claimed_by") not in {None, worker_id}:
                continue
            row["deep_status"] = "running"
            row["claimed_by"] = worker_id
            row["claimed_at"] = now
            claimed.append(dict(row))
            if len(claimed) >= limit:
                break
        self._flush()
        return claimed

    def patch_deep_status(
        self,
        address: str,
        *,
        deep_status: str,
        contract_name: Optional[str] = None,
        engine_findings: Optional[list[Any]] = None,
        engine_agreement: Optional[dict[str, Any]] = None,
    ) -> None:
        addr = normalize_address(address)
        tgt = self.targets.setdefault(addr, {"address": addr, "created_at": _now()})
        tgt["deep_status"] = deep_status
        if contract_name:
            tgt["contract_name"] = contract_name
        if engine_findings is not None:
            tgt["engine_findings"] = list(engine_findings)
        if engine_agreement is not None:
            tgt["engine_agreement"] = dict(engine_agreement)
        tgt["updated_at"] = _now()
        self._flush()

    def list_targets(self, bucket: Optional[str] = None, limit: int = 200) -> list[dict[str, Any]]:
        rows = list(self.targets.values())
        if bucket:
            rows = [r for r in rows if r.get("bucket") == bucket]
        rows.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
        return rows[:limit]

    def list_results(self, address: Optional[str] = None, limit: int = 200) -> list[dict[str, Any]]:
        rows = list(self.results)
        if address:
            addr = normalize_address(address)
            rows = [r for r in rows if r.get("address") == addr]
        rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
        return rows[:limit]

    def list_artifacts(self, address: Optional[str] = None, kind: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]:
        rows = list(self.artifacts)
        if address:
            addr = normalize_address(address)
            rows = [r for r in rows if r.get("address") == addr]
        if kind:
            rows = [r for r in rows if r.get("kind") == kind]
        rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
        return rows[:limit]

    def _path(self) -> Optional[Path]:
        if not self.work_dir:
            return None
        return self.work_dir / "dry-run-store.json"

    def _load(self) -> None:
        p = self._path()
        if not p or not p.exists():
            return
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self.targets = {r["address"]: r for r in data.get("targets", [])}
        self.artifacts = list(data.get("artifacts", []))
        self.results = list(data.get("results", []))

    def _flush(self) -> None:
        p = self._path()
        if not p:
            return
        p.write_text(json.dumps({
            "targets": list(self.targets.values()),
            "artifacts": self.artifacts,
            "results": self.results,
        }, indent=2), encoding="utf-8")


class SupabaseStore:
    def __init__(self, url: str, service_role_key: str, timeout_s: float = 20.0):
        if not service_role_key:
            raise ValueError("SUPABASE_SERVICE_ROLE_KEY is required for remote persist")
        self.url = url.rstrip("/")
        self.key = service_role_key
        self.timeout_s = timeout_s

    def upsert_target(self, target: Target) -> Target:
        addr = normalize_address(target.address)
        target.address = addr
        body: dict[str, Any] = {
            "address": addr,
            "bytecode_hash": target.bytecode_hash,
            "tvl_usd": target.tvl_usd,
            "status": target.status,
        }
        if target.funds_usd is not None:
            body["funds_usd"] = target.funds_usd
        if target.funds_breakdown is not None:
            body["funds_breakdown"] = list(target.funds_breakdown or [])
        if target.funds_status:
            body["funds_status"] = target.funds_status
        if target.funds_checked_at:
            body["funds_checked_at"] = target.funds_checked_at
        self._req("POST", "eth_scan_targets", body, prefer="return=minimal,resolution=merge-duplicates")
        return target

    def get_target(self, address: str) -> Optional[dict[str, Any]]:
        rows = self._req("GET", "eth_scan_targets", query={"address": "eq.%s" % normalize_address(address)})
        return rows[0] if rows else None

    def closed_no_hashes(self) -> set[str]:
        rows = self._req("GET", "eth_scan_targets", query={
            "bucket": "eq.human-no-candidate",
            "status": "eq.done",
            "select": "bytecode_hash",
        })
        return {r["bytecode_hash"] for r in rows if r.get("bytecode_hash")}

    def save_artifact(self, address: str, kind: str, payload: dict[str, Any], confidence: str) -> None:
        self._req("POST", "eth_scan_artifacts", {
            "address": normalize_address(address),
            "kind": kind,
            "path_or_json": payload,
            "confidence": confidence,
        }, prefer="return=minimal")

    def save_result(self, address: str, result: FunnelResult) -> None:
        addr = normalize_address(address)
        result_body: dict[str, Any] = {
            "address": addr,
            "bucket": result.bucket,
            "heat": result.heat,
            "stage_trace": to_plain(result.stage_trace),
            "hypotheses": to_plain(result.hypotheses),
            "notes": "\n".join(result.notes),
        }
        if result.funds_usd is not None:
            result_body["funds_usd"] = result.funds_usd
        if result.funds_breakdown is not None:
            result_body["funds_breakdown"] = list(result.funds_breakdown or [])
        if result.funds_status:
            result_body["funds_status"] = result.funds_status
        if result.funds_checked_at:
            result_body["funds_checked_at"] = result.funds_checked_at
        if getattr(result, "invariant_results", None) is not None:
            result_body["invariant_results"] = list(result.invariant_results or [])
        if getattr(result, "heat_breakdown", None) is not None:
            result_body["heat_breakdown"] = dict(result.heat_breakdown or {})
        if getattr(result, "known_safe", False):
            result_body["known_safe"] = True
        if getattr(result, "contract_name", None):
            result_body["contract_name"] = result.contract_name
        if getattr(result, "pattern_leads", None) is not None:
            result_body["pattern_leads"] = to_plain(result.pattern_leads)
        self._req("POST", "eth_scan_results", result_body, prefer="return=minimal")
        patch: dict[str, Any] = {
            "bucket": result.bucket,
            "heat": result.heat,
            "src_confidence": result.src_confidence,
            "ir_confidence": result.ir_confidence,
            "status": "skipped" if result.dropped else "done",
        }
        if result.funds_usd is not None:
            patch["funds_usd"] = result.funds_usd
            patch["tvl_usd"] = result.funds_usd
        if result.funds_breakdown is not None:
            patch["funds_breakdown"] = list(result.funds_breakdown or [])
        if result.funds_status:
            patch["funds_status"] = result.funds_status
        if result.funds_checked_at:
            patch["funds_checked_at"] = result.funds_checked_at
        if getattr(result, "known_safe", False):
            patch["known_safe"] = True
        if getattr(result, "contract_name", None):
            patch["contract_name"] = result.contract_name
        if getattr(result, "heat_breakdown", None) is not None:
            patch["heat_breakdown"] = dict(result.heat_breakdown or {})
        self._req("PATCH", "eth_scan_targets", patch, query={"address": "eq.%s" % addr})

    def claim_pending(self, limit: int, worker_id: str) -> list[dict[str, Any]]:
        rows = self._req("GET", "eth_scan_targets", query={
            "status": "eq.pending",
            "order": "updated_at.asc",
            "limit": str(limit),
        })
        return self._mark_running(rows, worker_id)

    def claim_lane_b(self, limit: int, worker_id: str) -> list[dict[str, Any]]:
        rows = self._req("GET", "eth_scan_targets", query={
            "bucket": "in.(lane-b-queue,manual-review)",
            "order": "updated_at.asc",
            "limit": str(limit),
        })
        return self._mark_running(rows, worker_id)

    def claim_deep(self, limit: int, worker_id: str) -> list[dict[str, Any]]:
        # Prefer never-deep-scanned lane-b / manual-review rows.
        rows = self._req("GET", "eth_scan_targets", query={
            "bucket": "in.(lane-b-queue,manual-review)",
            "or": "(deep_status.is.null,deep_status.eq.pending,deep_status.eq.error)",
            "order": "updated_at.asc",
            "limit": str(max(limit * 3, limit)),
        })
        if not isinstance(rows, list):
            rows = []
        # Fall back if the deep_status column is not migrated yet.
        if not rows:
            rows = self._req("GET", "eth_scan_targets", query={
                "bucket": "in.(lane-b-queue,manual-review)",
                "order": "updated_at.asc",
                "limit": str(limit),
            })
        picked = (rows or [])[:limit]
        now = _now()
        out: list[dict[str, Any]] = []
        for row in picked:
            try:
                self._req("PATCH", "eth_scan_targets", {
                    "deep_status": "running",
                    "claimed_by": worker_id,
                    "claimed_at": now,
                }, query={"address": "eq.%s" % row["address"]})
            except Exception:  # noqa: BLE001
                # Column may be missing — still return the claim for local processing.
                pass
            row = dict(row)
            row["deep_status"] = "running"
            row["claimed_by"] = worker_id
            row["claimed_at"] = now
            out.append(row)
        return out

    def patch_deep_status(
        self,
        address: str,
        *,
        deep_status: str,
        contract_name: Optional[str] = None,
        engine_findings: Optional[list[Any]] = None,
        engine_agreement: Optional[dict[str, Any]] = None,
    ) -> None:
        addr = normalize_address(address)
        patch: dict[str, Any] = {"deep_status": deep_status}
        if contract_name:
            patch["contract_name"] = contract_name
        if engine_findings is not None:
            patch["engine_findings"] = list(engine_findings)
        if engine_agreement is not None:
            patch["engine_agreement"] = dict(engine_agreement)
        try:
            self._req("PATCH", "eth_scan_targets", patch, query={"address": "eq.%s" % addr})
        except Exception:  # noqa: BLE001
            # Soft-fail when migration not applied yet.
            pass
        # Always keep a result-side copy when possible.
        if engine_findings is not None or engine_agreement is not None:
            body: dict[str, Any] = {"address": addr}
            if engine_findings is not None:
                body["engine_findings"] = list(engine_findings)
            if engine_agreement is not None:
                body["engine_agreement"] = dict(engine_agreement)
            try:
                # Append a thin results row so /test history can show engine output.
                body["bucket"] = (self.get_target(addr) or {}).get("bucket") or "manual-review"
                body["heat"] = (self.get_target(addr) or {}).get("heat") or 0
                body["stage_trace"] = [{"stage": "deep-A", "decision": deep_status}]
                body["notes"] = "phase-A deep engines"
                self._req("POST", "eth_scan_results", body, prefer="return=minimal")
            except Exception:  # noqa: BLE001
                pass

    def list_targets(self, bucket: Optional[str] = None, limit: int = 200) -> list[dict[str, Any]]:
        q: dict[str, str] = {"order": "updated_at.desc", "limit": str(limit)}
        if bucket:
            q["bucket"] = "eq.%s" % bucket
        return self._req("GET", "eth_scan_targets", query=q)

    def list_results(self, address: Optional[str] = None, limit: int = 200) -> list[dict[str, Any]]:
        q: dict[str, str] = {"order": "created_at.desc", "limit": str(limit)}
        if address:
            q["address"] = "eq.%s" % normalize_address(address)
        return self._req("GET", "eth_scan_results", query=q)

    def list_artifacts(self, address: Optional[str] = None, kind: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]:
        q: dict[str, str] = {"order": "created_at.desc", "limit": str(limit)}
        if address:
            q["address"] = "eq.%s" % normalize_address(address)
        if kind:
            q["kind"] = "eq.%s" % kind
        return self._req("GET", "eth_scan_artifacts", query=q)

    def _mark_running(self, rows: list[dict[str, Any]], worker_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        now = _now()
        for row in rows:
            self._req("PATCH", "eth_scan_targets", {
                "status": "running",
                "claimed_by": worker_id,
                "claimed_at": now,
            }, query={"address": "eq.%s" % row["address"]})
            row = dict(row)
            row["status"] = "running"
            row["claimed_by"] = worker_id
            row["claimed_at"] = now
            out.append(row)
        return out

    def _req(
        self,
        method: str,
        table: str,
        body: Optional[dict[str, Any]] = None,
        query: Optional[dict[str, str]] = None,
        prefer: str = "return=representation",
    ) -> list[dict[str, Any]]:
        qs = ("?" + urllib.parse.urlencode(query)) if query else ""
        url = "%s/rest/v1/%s%s" % (self.url, table, qs)
        data = json.dumps(body).encode("utf-8") if body is not None and method != "GET" else None
        headers = {
            "apikey": self.key,
            "Authorization": "Bearer %s" % self.key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Prefer": prefer,
        }
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            err = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError("supabase %s %s failed: HTTP %s %s" % (method, table, exc.code, err[:400])) from exc
        if not raw:
            return []
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
        return []


def open_store(settings: Settings) -> ScanStore:
    if settings.persist_remote:
        return SupabaseStore(settings.supabase_url, settings.supabase_service_role_key)
    settings.work_dir.mkdir(parents=True, exist_ok=True)
    return MemoryStore(settings.work_dir)


def artifact_payload(art: SourceArtifact) -> dict[str, Any]:
    raw = to_plain(art)
    content = raw.get("content") or ""
    if len(content) > 80_000:
        raw["content"] = content[:80_000]
        raw["content_truncated"] = True
    return raw


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
