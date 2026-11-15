"""Durable Blend journal. Each stage is written before the next one starts.

Production uses SupabaseStore. A failed write is logged, the run is marked
error when that second write succeeds, and the exception propagates. Stages
already stored stay stored, so a crash mid-run leaves a trail.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("eth_scanner.blend.journal")

STAGES = (
    "intake",
    "facts",
    "spec",
    "symbolic",
    "engine-medusa",
    "engine-echidna",
    "engine-ityfuzz",
    "engine-halmos",
    "fuzz-foundry",
    "mutation",
    "fusion",
    "decision",
)


class PersistError(RuntimeError):
    """A Supabase (or store) write failed. The run has been marked when possible."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clip(payload: Any) -> Any:
    if isinstance(payload, dict):
        out = {}
        for key, value in payload.items():
            if key in {"annotations", "log", "log_excerpt"} and isinstance(value, str) and len(value) > 500:
                out[key] = value[:500]
            else:
                out[key] = _clip(value)
        return out
    if isinstance(payload, list):
        return [_clip(item) for item in payload[:40]]
    if isinstance(payload, str) and len(payload) > 800:
        return payload[:800]
    return payload


class BlendJournal:
    def __init__(
        self,
        store: Any,
        *,
        address: str,
        chain: str = "ethereum",
        discovery_source: str = "blend",
        funds_usd: Optional[float] = None,
        list_id: Optional[str] = None,
        contract_name: str = "",
    ):
        self.store = store
        self.address = address or ""
        self.chain = chain or "ethereum"
        self.discovery_source = discovery_source or "blend"
        self.funds_usd = funds_usd
        self.list_id = list_id
        self.contract_name = contract_name or ""
        self.dedupe_key = "blend:%s:%s" % (self.discovery_source, (address or "unknown").lower())
        self.run_id: Optional[str] = None
        self.mode = "supabase" if type(store).__name__ == "SupabaseStore" else "memory"
        self.written: list[str] = []
        self._lock = threading.Lock()
        self._opened = False

    @classmethod
    def open(cls, store: Any, **kwargs: Any) -> "BlendJournal":
        if store is None:
            return NullJournal(**kwargs)
        return cls(store, **kwargs)

    def summary(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "dedupe_key": self.dedupe_key,
            "run_id": self.run_id,
            "stages": list(self.written),
        }

    def open_run(self, *, status: str = "running", drop_reason: Optional[str] = None) -> None:
        """Insert the run row before any engine starts."""
        row = self._run_body(status=status, drop_reason=drop_reason)
        row["started_at"] = _now()
        saved = self._call("open_run", lambda: self.store.save_blend_run(row))
        if isinstance(saved, dict):
            self.run_id = str(saved.get("id") or "") or self.run_id
            self.dedupe_key = str(saved.get("dedupe_key") or self.dedupe_key)
        self._opened = True

    def stage(self, name: str, payload: dict[str, Any], *, status: str = "ok") -> None:
        """Persist one stage, then its findings. A failure stops the pipeline."""
        body = {
            "run_id": self.run_id,
            "dedupe_key": self.dedupe_key,
            "address": self.address,
            "stage": name,
            "status": status,
            "heat_contribution": int((payload or {}).get("heat_contribution") or 0),
            "bug_classes": list((payload or {}).get("bug_classes") or []),
            "payload": _clip(payload or {}),
            "started_at": _now(),
            "finished_at": _now(),
        }
        with self._lock:
            self._call("stage:%s" % name, lambda: self.store.save_blend_stage(body))
            self.written.append(name)
        for finding in (payload or {}).get("findings") or []:
            self.finding(name, finding if isinstance(finding, dict) else {"title": str(finding)})

    def finding(self, stage: str, row: dict[str, Any]) -> None:
        if not self.run_id:
            return
        engine = str(row.get("engine") or stage)
        rule = str(row.get("rule") or row.get("id") or stage)
        key = "%s:%s:%s" % (stage, engine, rule)
        severity = "high" if row.get("kind") == "drain-proof" else "info"
        confidence = "high" if int(row.get("agreement_count") or 0) >= 2 else "low"
        body = {
            "finding_key": key[:180],
            "kind": "blend",
            "address": self.address or None,
            "chain": self.chain,
            "engine": engine[:80],
            "rule": rule[:180],
            "layer": stage[:80],
            "title": str(row.get("title") or rule)[:180],
            "severity": severity,
            "confidence": confidence,
            "funds_at_risk_class": "invariant-violation",
            "evidence": str(row.get("evidence") or row.get("detail") or "")[:500],
            "defensive_only": True,
            "raw": _clip({
                "heat_contribution": int(row.get("heat_contribution") or 0),
                "label": row.get("label") or "evidence only",
                "caller_profit_delta": int(row.get("caller_profit_delta") or 0),
                "kind": row.get("kind") or "evidence-only",
                "agreement_score": row.get("agreement_score"),
                "engines_agreeing": row.get("engines_agreeing"),
                "passes_agreeing": row.get("passes_agreeing"),
            }),
        }
        self._call("finding:%s" % key, lambda: self.store.save_test_scan_findings(self.run_id, [body]))

    def finish(self, report: dict[str, Any]) -> None:
        """Final decision: bucket, heat, proof-vs-evidence, agreement, receipt."""
        proofs = [row for row in report.get("findings") or [] if row.get("kind") == "drain-proof"]
        top = proofs[0] if proofs else ((report.get("findings") or [None])[0])
        body = self._run_body(status="done")
        body.update({
            "blend_bucket": report.get("bucket"),
            "blend_heat": int(report.get("heat") or 0),
            "heat": int(report.get("heat") or 0),
            "proven_caller_profit": bool(proofs),
            "evidence_only": not bool(proofs),
            "drain_probability": report.get("drain_probability"),
            "agreement_score": (top or {}).get("agreement_score") if isinstance(top, dict) else None,
            "engines_agreeing": (top or {}).get("engines_agreeing") if isinstance(top, dict) else [],
            "bug_classes": list(report.get("bug_classes") or []),
            "known_safe": bool((report.get("heat_breakdown") or {}).get("known_safe")),
            "blend_receipt": _clip({
                "schema": report.get("schema"),
                "bucket": report.get("bucket"),
                "heat": report.get("heat"),
                "bug_classes": report.get("bug_classes"),
                "drain_probability": report.get("drain_probability"),
                "findings": report.get("findings"),
                "layers": {
                    name: {
                        "status": block.get("status"),
                        "heat_contribution": block.get("heat_contribution"),
                        "label": block.get("label"),
                    }
                    for name, block in (report.get("layers") or {}).items()
                    if isinstance(block, dict)
                },
                "heat_breakdown": report.get("heat_breakdown"),
            }),
            "finished_at": _now(),
            "raw": {
                "feed": "blend",
                "discovery_source": self.discovery_source,
                "list_id": self.list_id,
                "persistence_stages": list(self.written),
            },
        })
        self._call("finish", lambda: self.store.save_blend_run(body))
        if isinstance(top, dict):
            self.finding("decision", {
                "engine": "blend",
                "rule": top.get("rule") or report.get("bucket") or "decision",
                "title": top.get("title") or "blend decision",
                "kind": top.get("kind"),
                "label": top.get("label"),
                "heat_contribution": int(top.get("heat_contribution") or 0),
                "caller_profit_delta": int(top.get("caller_profit_delta") or 0),
                "agreement_score": top.get("agreement_score"),
                "engines_agreeing": top.get("engines_agreeing"),
                "passes_agreeing": top.get("passes_agreeing"),
                "evidence": top.get("evidence") or "",
            })
        self.stage("decision", {
            "heat_contribution": 0,
            "bug_classes": list(report.get("bug_classes") or []),
            "bucket": report.get("bucket"),
            "heat": int(report.get("heat") or 0),
            "proven_caller_profit": bool(proofs),
            "label": "drain proof" if proofs else "evidence only",
            "drain_probability": report.get("drain_probability"),
            "agreement_score": body.get("agreement_score"),
            "findings": [],
        }, status="ok")

    def finish_drop(self, reason: str) -> None:
        body = self._run_body(status="dropped", drop_reason=reason)
        body["finished_at"] = _now()
        body["blend_bucket"] = "no"
        body["evidence_only"] = True
        body["proven_caller_profit"] = False
        self._call("drop", lambda: self.store.save_blend_run(body))

    def fail(self, message: str) -> None:
        """Mark the run error. Used for pipeline exceptions, not for persist errors."""
        logger.error("blend run %s failed: %s", self.dedupe_key, message)
        try:
            marker = getattr(self.store, "mark_blend_run_error", None)
            if callable(marker) and self._opened:
                marker(self.dedupe_key, message[:500])
        except Exception as exc:  # noqa: BLE001
            logger.error("blend run %s could not be marked: %s", self.dedupe_key, exc)

    def _run_body(self, *, status: str, drop_reason: Optional[str] = None) -> dict[str, Any]:
        return {
            "dedupe_key": self.dedupe_key,
            "kind": "blend",
            "chain": self.chain,
            "address": self.address,
            "contract_name": self.contract_name or None,
            "discovery_source": self.discovery_source,
            "list_id": self.list_id,
            "funds_usd": self.funds_usd,
            "tvl_usd": self.funds_usd,
            "status": status,
            "dropped": status == "dropped",
            "drop_reason": drop_reason,
            "heat": 0,
            "started_at": _now(),
        }

    def _call(self, what: str, fn):
        try:
            return fn()
        except PersistError:
            raise
        except Exception as exc:
            self._explode(what, exc)

    def _explode(self, what: str, exc: Exception) -> None:
        logger.error("blend persist failed stage=%s run=%s: %s", what, self.dedupe_key, exc)
        try:
            marker = getattr(self.store, "mark_blend_run_error", None)
            if callable(marker):
                marker(self.dedupe_key, "%s: %s" % (what, exc)[:500])
        except Exception as mark_exc:  # noqa: BLE001
            logger.error("blend persist could not mark run %s: %s", self.dedupe_key, mark_exc)
        raise PersistError("%s: %s" % (what, exc)) from exc


class NullJournal(BlendJournal):
    """No store attached. Fixture unit tests use this. Production passes a store."""

    def __init__(self, **kwargs: Any):
        self.store = None
        self.address = kwargs.get("address") or ""
        self.chain = kwargs.get("chain") or "ethereum"
        self.discovery_source = kwargs.get("discovery_source") or "blend"
        self.funds_usd = kwargs.get("funds_usd")
        self.list_id = kwargs.get("list_id")
        self.contract_name = kwargs.get("contract_name") or ""
        self.dedupe_key = ""
        self.run_id = None
        self.mode = "detached"
        self.written = []
        self._lock = threading.Lock()
        self._opened = False

    def open_run(self, *, status: str = "running", drop_reason: Optional[str] = None) -> None:
        return None

    def stage(self, name: str, payload: dict[str, Any], *, status: str = "ok") -> None:
        return None

    def finding(self, stage: str, row: dict[str, Any]) -> None:
        return None

    def finish(self, report: dict[str, Any]) -> None:
        return None

    def finish_drop(self, reason: str) -> None:
        return None

    def fail(self, message: str) -> None:
        return None
