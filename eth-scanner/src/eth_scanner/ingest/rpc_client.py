"""Shared JSON-RPC client with a per-URL circuit breaker.

Hard provider errors — monthly capacity / quota exceeded, 401/403 auth
failures, and repeated 5xx — open a short cooldown so a set-but-dead
ETH_RPC_URL is treated like "no usable RPC". Stages that need a private
RPC (fork-verify, fuzz, fresh-deploy) skip gracefully instead of
crashing or hammering the provider.

Ordinary rate limits are retried with a capped backoff and do not open
the long circuit. Never sends a transaction. Logs never include the
full RPC URL (API keys live in the path).
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional

log = logging.getLogger("eth_scanner.rpc")

DEFAULT_COOLDOWN_S = 900.0
DEFAULT_TRANSIENT_RETRIES = 2  # retries after the first try (3 attempts)
DEFAULT_TRANSIENT_BACKOFF_S = 0.5
DEFAULT_5XX_THRESHOLD = 3
DEFAULT_USER_AGENT = "eth-scanner/0.3 (defensive; read-only)"

# Alchemy's exhausted-plan message, plus close quota wording.
_HARD_QUOTA_RE = re.compile(
    r"(monthly\s+capacity|capacity\s+limit\s+exceeded|quota\s+(exceeded|exhausted)"
    r"|exceeded\s+(your\s+)?(monthly\s+)?(compute\s+unit\s+)?quota"
    r"|credit\s+limit|plan\s+capacity)",
    re.I,
)
_PER_SECOND_RE = re.compile(r"per[-\s]?second|compute units per second|cu/s|too many requests", re.I)
# Provider auth only — not Solidity reverts such as "execution reverted: UNAUTHORIZED".
_AUTH_RE = re.compile(
    r"(must be authenticated|invalid (api )?key|api key .*invalid|not authenticated)",
    re.I,
)
_EXECUTION_REVERT_RE = re.compile(r"execution reverted|vm exception|reverted", re.I)


class RpcUnavailable(RuntimeError):
    """The RPC URL is unset or has been circuit-broken as unusable."""

    def __init__(self, reason: str, host: str = ""):
        self.reason = reason
        self.host = host
        super().__init__(reason)


class RpcTransientError(RuntimeError):
    """A capped-retry rate limit or short outage; circuit stays closed."""


@dataclass
class _Circuit:
    opened_at: float = 0.0
    cooldown_s: float = DEFAULT_COOLDOWN_S
    reason: str = ""
    warned: bool = False
    consecutive_5xx: int = 0
    open: bool = False


_CIRCUITS: dict[str, _Circuit] = {}
_LOCK = threading.Lock()


def cooldown_s() -> float:
    raw = (os.environ.get("ETH_SCANNER_RPC_COOLDOWN_S") or "").strip()
    if not raw:
        return DEFAULT_COOLDOWN_S
    try:
        return max(1.0, float(raw))
    except (TypeError, ValueError):
        return DEFAULT_COOLDOWN_S


def transient_retries() -> int:
    raw = (os.environ.get("ETH_SCANNER_RPC_TRANSIENT_RETRIES") or "").strip()
    if not raw:
        return DEFAULT_TRANSIENT_RETRIES
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_TRANSIENT_RETRIES


def transient_backoff_s() -> float:
    raw = (os.environ.get("ETH_SCANNER_RPC_TRANSIENT_BACKOFF_S") or "").strip()
    if not raw:
        return DEFAULT_TRANSIENT_BACKOFF_S
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return DEFAULT_TRANSIENT_BACKOFF_S


def five_xx_threshold() -> int:
    raw = (os.environ.get("ETH_SCANNER_RPC_5XX_THRESHOLD") or "").strip()
    if not raw:
        return DEFAULT_5XX_THRESHOLD
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_5XX_THRESHOLD


def host_only(url: Optional[str]) -> str:
    """Hostname (no path, no key) for logs and skip reasons."""
    if not url:
        return ""
    try:
        return urllib.parse.urlparse(url).netloc or ""
    except Exception:  # noqa: BLE001
        return ""


def reset_rpc_circuits() -> None:
    """Test helper: drop all circuit state."""
    with _LOCK:
        _CIRCUITS.clear()


def classify_rpc_failure(http_status: Optional[int], body: Any) -> tuple[str, str]:
    """Classify a provider failure as 'hard', 'transient', 'server', or 'other'.

    'hard' opens the circuit (quota/auth). 'transient' is an ordinary rate
    limit (capped retry). 'server' is a 5xx (retry, open after a streak).
    """
    text = _body_text(body)
    err_code, err_msg = _jsonrpc_error(body, text)
    blob = " ".join(p for p in (text, err_msg, str(err_code or "")) if p)

    if _is_provider_auth(http_status, err_code, blob):
        return "hard", _detail("auth failure", http_status, err_code, err_msg or text)

    if _is_hard_quota(blob, err_code, http_status):
        return "hard", _detail("capacity/quota exceeded", http_status, err_code, err_msg or text)

    if http_status == 429 or err_code == 429 or _PER_SECOND_RE.search(blob) or _is_rate_limit_code(err_code):
        return "transient", _detail("rate limited", http_status, err_code, err_msg or text)

    if http_status is not None and http_status >= 500:
        return "server", _detail("server error", http_status, err_code, err_msg or text)

    if err_msg or err_code is not None:
        return "other", _detail("rpc error", http_status, err_code, err_msg or text)

    if http_status is not None and http_status >= 400:
        return "other", _detail("http error", http_status, err_code, text)

    return "other", (text or "rpc error")[:200]


def is_rpc_usable(url: str) -> bool:
    """False when the URL is empty or the circuit is open (cooldown not expired)."""
    url = (url or "").strip()
    if not url:
        return False
    with _LOCK:
        state = _CIRCUITS.get(url)
        if state is None or not state.open:
            return True
        if time.monotonic() - state.opened_at >= state.cooldown_s:
            # Half-open: allow one probe. Keep the reason for logs until success.
            state.open = False
            return True
        return False


def rpc_unusable_reason(url: str = "") -> str:
    """Skip-reason string for a missing or circuit-broken URL."""
    url = (url or "").strip()
    if not url:
        return "ETH_RPC_URL unset"
    with _LOCK:
        state = _CIRCUITS.get(url)
        if state is not None and state.open:
            host = host_only(url)
            detail = state.reason or "provider error"
            remaining = max(0.0, state.cooldown_s - (time.monotonic() - state.opened_at))
            return "ETH_RPC_URL unusable at %s (%s; cooldown %.0fs)" % (host or "rpc", detail, remaining)
    if not is_rpc_usable(url):
        return "ETH_RPC_URL unusable"
    return ""


def probe_rpc(url: str, timeout_s: float = 8.0) -> tuple[bool, str]:
    """Read-only eth_blockNumber. On hard errors opens the circuit.

    Returns (ok, reason). reason is empty on success. Does not hit the
    network when the circuit is already open.
    """
    url = (url or "").strip()
    if not url:
        return False, "ETH_RPC_URL unset"
    if not is_rpc_usable(url):
        return False, rpc_unusable_reason(url)
    try:
        raw = rpc_call(url, "eth_blockNumber", [], timeout_s=timeout_s)
    except RpcUnavailable as exc:
        return False, exc.reason
    except RpcTransientError as exc:
        return False, "ETH_RPC_URL transient error: %s" % str(exc)[:160]
    except Exception as exc:  # noqa: BLE001
        return False, "ETH_RPC_URL probe failed: %s" % str(exc)[:160]
    try:
        if raw is None:
            return False, "ETH_RPC_URL probe failed: empty block number"
        int(raw, 16) if isinstance(raw, str) else int(raw)
    except (TypeError, ValueError):
        return False, "ETH_RPC_URL probe failed: bad block number"
    return True, ""


def rpc_call(
    url: str,
    method: str,
    params: Optional[list[Any]] = None,
    *,
    timeout_s: float = 15.0,
    user_agent: str = "",
    max_retries: Optional[int] = None,
) -> Any:
    """POST a JSON-RPC method. Raises RpcUnavailable when the URL is unusable."""
    url = (url or "").strip()
    if not url:
        raise RpcUnavailable("ETH_RPC_URL unset")
    if not is_rpc_usable(url):
        raise RpcUnavailable(rpc_unusable_reason(url), host=host_only(url))

    attempts = 1 + (transient_retries() if max_retries is None else max(0, int(max_retries)))
    backoff = transient_backoff_s()
    ua = user_agent or DEFAULT_USER_AGENT
    last_exc: Optional[BaseException] = None

    for attempt in range(attempts):
        if not is_rpc_usable(url):
            raise RpcUnavailable(rpc_unusable_reason(url), host=host_only(url))
        try:
            body, status = _post_json(url, method, params or [], timeout_s=timeout_s, user_agent=ua)
        except urllib.error.HTTPError as exc:
            raw = _read_http_error(exc)
            kind, detail = classify_rpc_failure(exc.code, raw)
            last_exc = _handle_classified(url, kind, detail, exc)
            if last_exc is None:
                last_exc = RpcTransientError(detail)
                if attempt + 1 < attempts:
                    time.sleep(_backoff(backoff, attempt))
                    continue
                raise last_exc
            raise last_exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_exc = RpcTransientError("network error: %s" % str(exc)[:160])
            if attempt + 1 < attempts:
                time.sleep(_backoff(backoff, attempt))
                continue
            raise last_exc from exc

        if isinstance(body, dict) and body.get("error"):
            kind, detail = classify_rpc_failure(status, body)
            last_exc = _handle_classified(url, kind, detail, None)
            if last_exc is None:
                last_exc = RpcTransientError(detail)
                if attempt + 1 < attempts:
                    time.sleep(_backoff(backoff, attempt))
                    continue
                raise last_exc
            raise last_exc

        _clear_failures(url)
        return body.get("result") if isinstance(body, dict) else body

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("rpc_call exhausted retries with no result")


def _handle_classified(
    url: str,
    kind: str,
    detail: str,
    cause: Optional[BaseException],
) -> Optional[BaseException]:
    """Return an exception to raise, or None to retry the request."""
    if kind == "hard":
        _open_circuit(url, detail)
        exc = RpcUnavailable(rpc_unusable_reason(url) or detail, host=host_only(url))
        if cause is not None:
            exc.__cause__ = cause
        return exc
    if kind == "server":
        opened = _bump_5xx(url, detail)
        if opened:
            exc = RpcUnavailable(rpc_unusable_reason(url) or detail, host=host_only(url))
            if cause is not None:
                exc.__cause__ = cause
            return exc
        return None  # retry
    if kind == "transient":
        return None  # retry; caller raises RpcTransientError if attempts run out
    err = RuntimeError(detail)
    if cause is not None:
        err.__cause__ = cause
    return err


def _post_json(
    url: str,
    method: str,
    params: list[Any],
    *,
    timeout_s: float,
    user_agent: str,
) -> tuple[Any, int]:
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": user_agent},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        status = int(getattr(resp, "status", None) or getattr(resp, "code", None) or 200)
    if not raw:
        return {}, status
    try:
        return json.loads(raw), status
    except json.JSONDecodeError as exc:
        raise RuntimeError("non-JSON RPC response (%s): %s" % (status, raw[:160])) from exc


def _open_circuit(url: str, reason: str) -> None:
    host = host_only(url) or "rpc"
    cool = cooldown_s()
    with _LOCK:
        state = _CIRCUITS.setdefault(url, _Circuit())
        already = state.open and state.warned
        state.open = True
        state.opened_at = time.monotonic()
        state.cooldown_s = cool
        state.reason = reason
        if already:
            return
        state.warned = True
    log.warning(
        "ETH_RPC_URL at %s is unusable (%s) — skipping RPC-dependent stages "
        "for %.0fs instead of retrying. Live fuzz / fork-verify / fresh-deploy "
        "stay dormant until a working key is set.",
        host,
        reason,
        cool,
    )


def _bump_5xx(url: str, detail: str) -> bool:
    threshold = five_xx_threshold()
    with _LOCK:
        state = _CIRCUITS.setdefault(url, _Circuit())
        state.consecutive_5xx += 1
        count = state.consecutive_5xx
    if count >= threshold:
        _open_circuit(url, "repeated 5xx (%s)" % detail)
        return True
    return False


def _clear_failures(url: str) -> None:
    with _LOCK:
        state = _CIRCUITS.get(url)
        if state is None:
            return
        state.consecutive_5xx = 0
        state.open = False
        state.reason = ""
        state.warned = False


def _is_provider_auth(http_status: Optional[int], err_code: Optional[int], blob: str) -> bool:
    """True for a dead/forbidden RPC key, not for a contract-level revert."""
    if _EXECUTION_REVERT_RE.search(blob or ""):
        return False
    if http_status in {401, 403}:
        return True
    if err_code in {401, 403}:
        return True
    return bool(_AUTH_RE.search(blob or ""))


def _is_hard_quota(blob: str, err_code: Optional[int], http_status: Optional[int]) -> bool:
    if _PER_SECOND_RE.search(blob or ""):
        return False
    if _HARD_QUOTA_RE.search(blob or ""):
        return True
    # Bare 429 without quota wording is treated as a transient rate limit.
    return False


def _is_rate_limit_code(err_code: Optional[int]) -> bool:
    # Common provider rate-limit codes (not monthly quota).
    return err_code in {-32005, -32016}


def _jsonrpc_error(body: Any, text: str) -> tuple[Optional[int], str]:
    obj: Any = body
    if isinstance(body, str):
        try:
            obj = json.loads(body)
        except json.JSONDecodeError:
            obj = None
    if isinstance(obj, dict):
        err = obj.get("error")
        if isinstance(err, dict):
            code = err.get("code")
            try:
                code_i = int(code) if code is not None else None
            except (TypeError, ValueError):
                code_i = None
            return code_i, str(err.get("message") or "")
        if err:
            return None, str(err)
    return None, ""


def _body_text(body: Any) -> str:
    if body is None:
        return ""
    if isinstance(body, bytes):
        return body.decode("utf-8", errors="replace")
    if isinstance(body, str):
        return body
    try:
        return json.dumps(body)
    except (TypeError, ValueError):
        return str(body)


def _detail(kind: str, http_status: Optional[int], err_code: Optional[int], msg: str) -> str:
    bits = [kind]
    if http_status is not None:
        bits.append("http %s" % http_status)
    if err_code is not None:
        bits.append("rpc %s" % err_code)
    text = (msg or "").strip().replace("\n", " ")
    if text:
        bits.append(text[:160])
    return ": ".join((bits[0], "; ".join(bits[1:]))) if len(bits) > 1 else bits[0]


def _read_http_error(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read()
    except Exception:  # noqa: BLE001
        raw = b""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw or "")


def _backoff(base: float, attempt: int) -> float:
    return float(base) * (2 ** attempt)

