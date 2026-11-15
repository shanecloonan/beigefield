"""Per-key Etherscan budget. Read-only accounting — no chain writes.

Limits come from the environment, not from source constants:

- ``ETH_SCANNER_ETHERSCAN_PER_SECOND`` (default 5) — free-tier calls per second per key
- ``ETH_SCANNER_ETHERSCAN_PER_DAY`` (default 100000) — free-tier calls per UTC day per key
- ``ETH_SCANNER_ETHERSCAN_PACE`` (default 0.95) — fraction of the per-second cap to actually use

Each configured key has its own per-second pace and its own daily counter.
Throughput and the daily ceiling are the sums across ``ETHERSCAN_API_KEYS``.
The pacer sleeps so a key stays just under its per-second cap. The ledger
reserves the next chunk of daily calls *before* they are sent and treats an
unfinished reservation as spent, so a crash cannot carry the process over the cap.
The UTC day rolls at midnight and the counters start over.
"""

from __future__ import annotations

import hashlib
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

# Defaults match the current Etherscan free tier. Env overrides win.
DEFAULT_PER_SECOND = 5.0
DEFAULT_PER_DAY = 100_000
DEFAULT_PACE = 0.95
QUOTA_ID = "etherscan-quota"
_RESERVE_CHUNK = 25

_LEDGER: Optional["QuotaLedger"] = None
_LEDGER_LOCK = threading.Lock()


class DailyBudgetExhausted(Exception):
    """Every configured key is at its daily cap. Not an IngestError on purpose.

    Lane A catches ``IngestError`` and keeps walking. This must stop the walk
    instead of marking the rest of the list scanned with empty source.
    """

    def __init__(self, *, used: int, limit: int, resume_at: str, keys: int):
        super().__init__(
            "etherscan daily budget reached (%d/%d across %d key%s); resumes %s"
            % (used, limit, keys, "" if keys == 1 else "s", resume_at)
        )
        self.used = used
        self.limit = limit
        self.resume_at = resume_at
        self.keys = keys


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return default


def read_limits() -> tuple[float, int, float]:
    """``(per_second, per_day, pace)`` for one API key."""
    per_second = _env_float("ETH_SCANNER_ETHERSCAN_PER_SECOND", DEFAULT_PER_SECOND)
    per_day = _env_int("ETH_SCANNER_ETHERSCAN_PER_DAY", DEFAULT_PER_DAY)
    pace = _env_float("ETH_SCANNER_ETHERSCAN_PACE", DEFAULT_PACE)
    if per_second <= 0:
        per_second = DEFAULT_PER_SECOND
    if per_day < 1:
        per_day = DEFAULT_PER_DAY
    # Pace above 1 would exceed the configured per-second cap.
    if pace <= 0 or pace > 1:
        pace = DEFAULT_PACE
    return per_second, per_day, pace


def interval_for(per_second: float, pace: float) -> float:
    """Seconds between calls on one key. Just under the per-second cap.

    ``ETH_SCANNER_ETHERSCAN_INTERVAL`` may only add delay. A smaller explicit
    interval cannot outrun the configured cap.
    """
    rate = float(per_second) * float(pace)
    if rate <= 0:
        rate = DEFAULT_PER_SECOND * DEFAULT_PACE
    interval = 1.0 / rate
    explicit = os.environ.get("ETH_SCANNER_ETHERSCAN_INTERVAL")
    if explicit is not None and str(explicit).strip():
        try:
            interval = max(interval, float(explicit))
        except (TypeError, ValueError):
            pass
    return max(0.001, min(interval, 30.0))


def utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def next_utc_midnight(now: Optional[datetime] = None) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    tomorrow = (current.astimezone(timezone.utc) + timedelta(days=1)).date()
    return datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=timezone.utc).isoformat()


def key_id(key: str) -> str:
    """Stable id for logs and the quota row. Never the key itself."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


class QuotaLedger:
    """Daily call counts for every key this process has touched."""

    def __init__(self, per_day: int = DEFAULT_PER_DAY, chunk: int = _RESERVE_CHUNK):
        self.per_day = max(1, int(per_day))
        self.chunk = max(1, min(int(chunk), self.per_day))
        self.store: Any = None
        self.day = utc_today()
        self.used: dict[str, int] = {}
        self.reserved: dict[str, int] = {}
        self._lock = threading.Lock()

    def configure(self, *, per_day: int, store: Any) -> None:
        self.per_day = max(1, int(per_day))
        self.chunk = max(1, min(_RESERVE_CHUNK, self.per_day))
        self.store = store

    def has_budget(self, key: str) -> bool:
        with self._lock:
            self._roll_day_locked()
            return self.used.get(key_id(key), 0) < self.per_day

    def exhausted(self, keys: list[str]) -> DailyBudgetExhausted:
        with self._lock:
            self._roll_day_locked()
            used = sum(self.used.get(key_id(k), 0) for k in keys)
        limit = self.per_day * max(1, len(keys))
        return DailyBudgetExhausted(
            used=used,
            limit=limit,
            resume_at=next_utc_midnight(),
            keys=max(1, len(keys)),
        )

    def consume(self, key: str) -> None:
        """Count one call that is about to be sent. Reserves a chunk first."""
        with self._lock:
            self._roll_day_locked()
            kid = key_id(key)
            used = self.used.get(kid, 0)
            if used >= self.per_day:
                raise self._exhausted_locked([key])
            reserved = self.reserved.get(kid, 0)
            if used >= reserved:
                reserved = min(self.per_day, used + self.chunk)
                if reserved <= used:
                    raise self._exhausted_locked([key])
                self.reserved[kid] = reserved
                self._persist_locked()
            self.used[kid] = used + 1

    def snapshot(self, n_keys: int) -> dict[str, Any]:
        with self._lock:
            self._roll_day_locked()
            used = sum(self.used.values())
            n = max(0, int(n_keys))
            return {
                "day": self.day,
                "per_day_each": self.per_day,
                "per_day_total": self.per_day * max(1, n),
                "used": used,
                "keys_seen": len(self.used),
                "resume_at": next_utc_midnight(),
            }

    def load(self) -> None:
        saved = self._read()
        if not saved:
            return
        with self._lock:
            day = str(saved.get("day") or "")
            if day and day != utc_today():
                self.day = utc_today()
                self.used.clear()
                self.reserved.clear()
                return
            self.day = day or utc_today()
            rows = saved.get("keys") if isinstance(saved.get("keys"), dict) else {}
            for kid, row in rows.items():
                if not isinstance(row, dict):
                    continue
                try:
                    used = int(row.get("used") or 0)
                    reserved = int(row.get("reserved") or 0)
                except (TypeError, ValueError):
                    continue
                # An unfinished reservation counts as spent. Never move backwards.
                floor = max(0, used, reserved)
                self.used[kid] = max(self.used.get(kid, 0), floor)
                self.reserved[kid] = max(self.reserved.get(kid, 0), self.used[kid])

    def close(self) -> None:
        """Drop unused reservation so the next process continues at the real count."""
        with self._lock:
            for kid, used in list(self.used.items()):
                self.reserved[kid] = used
            self._persist_locked()

    def _exhausted_locked(self, keys: list[str]) -> DailyBudgetExhausted:
        used = sum(self.used.get(key_id(k), 0) for k in keys)
        return DailyBudgetExhausted(
            used=used,
            limit=self.per_day * max(1, len(keys)),
            resume_at=next_utc_midnight(),
            keys=max(1, len(keys)),
        )

    def _roll_day_locked(self) -> None:
        today = utc_today()
        if self.day == today:
            return
        self.day = today
        self.used.clear()
        self.reserved.clear()
        self._persist_locked()

    def _read(self) -> Optional[dict[str, Any]]:
        store = self.store
        if store is None:
            return None
        getter = getattr(store, "get_backfill", None)
        if not callable(getter):
            return None
        try:
            row = getter(QUOTA_ID)
        except Exception:  # noqa: BLE001 — quota must not sink a scan
            return None
        if not row:
            return None
        stats = row.get("stats") or {}
        if isinstance(stats, str):
            return None
        return dict(stats) if isinstance(stats, dict) else None

    def _persist_locked(self) -> None:
        store = self.store
        if store is None:
            return
        upsert = getattr(store, "upsert_backfill", None)
        if not callable(upsert):
            return
        body = {
            "id": QUOTA_ID,
            "start_block": 0,
            "end_block": 0,
            "cursor_block": int(sum(self.used.values())),
            "status": "running",
            "source": QUOTA_ID,
            "stats": {
                "day": self.day,
                "per_day_each": self.per_day,
                "keys": {
                    kid: {"used": int(self.used.get(kid, 0)), "reserved": int(self.reserved.get(kid, 0))}
                    for kid in set(self.used) | set(self.reserved)
                },
            },
        }
        try:
            upsert(body)
        except Exception:  # noqa: BLE001
            return


def active_ledger() -> QuotaLedger:
    global _LEDGER
    with _LEDGER_LOCK:
        if _LEDGER is None:
            _per_second, per_day, _pace = read_limits()
            _LEDGER = QuotaLedger(per_day=per_day)
        return _LEDGER


def reset_ledger(*, per_day: int = DEFAULT_PER_DAY, store: Any = None, chunk: int = _RESERVE_CHUNK) -> QuotaLedger:
    """Test hook. Replaces the process ledger."""
    global _LEDGER
    with _LEDGER_LOCK:
        ledger = QuotaLedger(per_day=per_day, chunk=chunk)
        ledger.store = store
        _LEDGER = ledger
        return ledger


def bind_quota(store: Any, settings: Any) -> QuotaLedger:
    """Attach the scan store and the configured daily cap. Safe to call twice."""
    per_day = getattr(settings, "etherscan_per_day", None)
    if per_day is None:
        _per_second, per_day, _pace = read_limits()
    ledger = active_ledger()
    ledger.configure(per_day=int(per_day), store=store)
    ledger.load()
    return ledger


def release_quota() -> None:
    ledger = _LEDGER
    if ledger is not None:
        ledger.close()
