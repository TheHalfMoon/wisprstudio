"""Single-use, path-bound WebSocket tickets for local launch-authenticated sidecars.

WebSocket upgrades initiated from Chromium's `new WebSocket(...)` API cannot carry
custom headers like `X-WisprStudio-Launch-Token` without exposing long-lived secrets
in URLs. Instead, the Electron main process exchanges its in-memory launch token at
`POST /api/auth/ws-ticket` for a short-lived (30 s), single-use, path-bound
`ovs_ws_ticket_<43-char base64url>` ticket and passes `?ws_ticket=...` on the upgrade.

Imports cleanly with zero ML/PyTorch dependencies.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass

WS_TICKET_PREFIX = "ovs_ws_ticket_"
WS_TICKET_TTL_SECONDS = 30
MAX_ACTIVE_WS_TICKETS = 256
ALLOWED_WS_PATHS: frozenset[str] = frozenset(
    {
        "/ws/transcribe",
        "/ws/events",
        "/ws/tts",
    }
)


@dataclass(frozen=True)
class IssuedLaunchWsTicket:
    token: str
    expires_at: int
    expires_in: int = WS_TICKET_TTL_SECONDS


@dataclass(frozen=True)
class _StoredLaunchTicket:
    path: str
    expires_monotonic: float


_lock = threading.Lock()
_pepper = secrets.token_bytes(32)
_tickets: dict[str, _StoredLaunchTicket] = {}


def _ticket_digest(token: str) -> str:
    return hmac.new(_pepper, token.encode("utf-8"), hashlib.sha256).hexdigest()


def _is_valid_ticket_format(token: str | None) -> bool:
    if not isinstance(token, str) or not token.startswith(WS_TICKET_PREFIX):
        return False
    body = token[len(WS_TICKET_PREFIX) :]
    if len(body) != 43:
        return False
    return all(ch.isalnum() or ch in "-_" for ch in body)


def _purge_expired_locked(now: float) -> None:
    expired = [k for k, entry in _tickets.items() if now >= entry.expires_monotonic]
    for k in expired:
        _tickets.pop(k, None)


def issue_ws_ticket(
    path: str,
    *,
    ttl_seconds: int = WS_TICKET_TTL_SECONDS,
) -> IssuedLaunchWsTicket:
    """Issue a single-use, path-bound WebSocket ticket."""
    cleaned_path = (path or "").strip()
    if cleaned_path not in ALLOWED_WS_PATHS:
        raise ValueError("WebSocket path is not allowed")
    ttl = max(1, min(int(ttl_seconds), 60))
    token = WS_TICKET_PREFIX + secrets.token_urlsafe(32)
    digest = _ticket_digest(token)
    now_mono = time.monotonic()
    expires_wall = int(time.time()) + ttl
    with _lock:
        _purge_expired_locked(now_mono)
        while len(_tickets) >= MAX_ACTIVE_WS_TICKETS:
            oldest_key = next(iter(_tickets))
            _tickets.pop(oldest_key, None)
        _tickets[digest] = _StoredLaunchTicket(
            path=cleaned_path,
            expires_monotonic=now_mono + ttl,
        )
    return IssuedLaunchWsTicket(token=token, expires_at=expires_wall, expires_in=ttl)


def consume_ws_ticket(ticket_token: str | None, path: str) -> bool:
    """Atomically consume a single-use WebSocket ticket for `path`."""
    if not _is_valid_ticket_format(ticket_token):
        return False
    assert isinstance(ticket_token, str)
    cleaned_path = (path or "").strip()
    digest = _ticket_digest(ticket_token)
    now_mono = time.monotonic()
    with _lock:
        _purge_expired_locked(now_mono)
        stored = _tickets.pop(digest, None)
        if stored is None:
            return False
        if now_mono >= stored.expires_monotonic:
            return False
        return hmac.compare_digest(stored.path, cleaned_path)


def clear_ws_tickets_for_tests() -> None:
    """Clear all pending local WebSocket tickets (intended for unit tests)."""
    with _lock:
        _tickets.clear()
