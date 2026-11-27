"""Local sidecar launch authentication for WisprStudio (`Ninerr`-style).

Enforces four defence-in-depth invariants for the local FastAPI sidecar:
1. Bind host restricted to IPv4 loopback (`127.0.0.1`) when desktop sidecar
   containment / launch authentication is enabled.
2. Per-launch 256-bit secret token read once from `stdin` (`WISPRSTUDIO_STDIN_LAUNCH_TOKEN=1`),
   held exclusively in process memory (never logged, never written to `os.environ`
   where child processes could inherit it).
3. Constant-time token verification (`hmac.compare_digest`) via
   `X-WisprStudio-Launch-Token` or `Authorization: Bearer <token>`.
4. Strict `Host` (`127.0.0.1` / `127.0.0.1:<port>`) and `Origin` validation
   refusing DNS-rebinding hostnames and foreign browser origins.

Imports cleanly with zero ML/PyTorch dependencies.
"""

from __future__ import annotations

import hmac
import os
import re
import secrets
import sys
import threading
from collections.abc import Collection, Mapping, Sequence
from typing import TextIO
from urllib.parse import parse_qs, urlsplit

from core.ws_ticket import consume_ws_ticket

LOOPBACK_BIND_HOST = "127.0.0.1"
STDIN_LAUNCH_TOKEN_ENV = "WISPRSTUDIO_STDIN_LAUNCH_TOKEN"
LAUNCH_TOKEN_HEADER = "x-wisprstudio-launch-token"
MIN_TOKEN_LENGTH = 32  # >= 32 ASCII chars; 64 hex chars = 256 bits

TRUSTED_DESKTOP_ORIGINS: frozenset[str] = frozenset(
    {
        "app://wisprstudio",
        "app://voicestudio",
        "app://.",
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
    }
)

_HEX_256_RE = re.compile(r"^[0-9a-fA-F]{64,256}$")
_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9._~+/-]{43,256}=*$")
_TRUTHY = frozenset({"1", "true", "yes", "on"})

_lock = threading.RLock()
_active_token: str | None = None
_expected_port: int | None = None
_extra_allowed_origins: frozenset[str] = frozenset()


class LaunchAuthConfigError(RuntimeError):
    """Raised when sidecar launch authentication is enabled with an invalid token or host."""


def generate_launch_token() -> str:
    """Generate a fresh 256-bit (64-hex-char) per-launch sidecar token."""
    return secrets.token_hex(32)


def is_valid_launch_token_shape(token: str | None) -> bool:
    """Verify `token` carries at least 256 bits of secret material (64 hex or >=43 base64url chars)."""
    if not isinstance(token, str):
        return False
    candidate = token.strip()
    if len(candidate) < MIN_TOKEN_LENGTH:
        return False
    return bool(_HEX_256_RE.fullmatch(candidate) or _SAFE_TOKEN_RE.fullmatch(candidate))


def validate_loopback_bind_host(host: str, *, allow_non_loopback: bool = False) -> str:
    """Ensure the sidecar binds strictly to `127.0.0.1` unless explicitly overridden."""
    cleaned = (host or "").strip()
    if allow_non_loopback:
        if not cleaned:
            raise LaunchAuthConfigError("Bind host must not be empty")
        return cleaned
    if cleaned != LOOPBACK_BIND_HOST:
        raise LaunchAuthConfigError(
            f"WisprStudio sidecar must bind exclusively to {LOOPBACK_BIND_HOST!r} (got {cleaned!r})"
        )
    return LOOPBACK_BIND_HOST


def configure_launch_auth(
    token: str | None,
    *,
    expected_port: int | None = None,
    extra_allowed_origins: Sequence[str] = (),
) -> None:
    """Configure or clear the in-memory launch token and host/origin expectations."""
    global _active_token, _expected_port, _extra_allowed_origins
    with _lock:
        if token is None:
            _active_token = None
            _expected_port = None
            _extra_allowed_origins = frozenset()
            return
        cleaned = token.strip()
        if not is_valid_launch_token_shape(cleaned):
            raise LaunchAuthConfigError(
                "Launch token must be at least 256 bits (64 hex chars or >=43 base64url chars)"
            )
        if expected_port is not None and not (1 <= int(expected_port) <= 65535):
            raise LaunchAuthConfigError(f"Invalid expected_port: {expected_port!r}")
        normalized_origins: set[str] = set()
        for origin in extra_allowed_origins:
            norm = _normalize_origin(origin)
            if norm:
                normalized_origins.add(norm)
        _active_token = cleaned
        _expected_port = int(expected_port) if expected_port is not None else None
        _extra_allowed_origins = frozenset(normalized_origins)


def reset_launch_auth() -> None:
    """Clear armed launch auth state (intended for unit tests)."""
    configure_launch_auth(None)


clear_launch_token_for_tests = reset_launch_auth


def get_active_launch_token() -> str | None:
    """Return the armed in-memory launch token, or None when disarmed."""
    with _lock:
        return _active_token


def is_launch_auth_armed() -> bool:
    """Return True when per-launch token authentication is active."""
    with _lock:
        return _active_token is not None


def read_stdin_launch_token(
    stream: TextIO | None = None,
    *,
    env: Mapping[str, str] | None = None,
    expected_port: int | None = None,
) -> str | None:
    """Read and arm a 256-bit launch token from `stdin` when `WISPRSTUDIO_STDIN_LAUNCH_TOKEN=1`.

    Reads exactly one line from `stream` (default `sys.stdin`) so an open desktop
    parent-liveness pipe remains open for EOF monitoring afterwards.
    """
    environ = env if env is not None else os.environ
    flag = (environ.get(STDIN_LAUNCH_TOKEN_ENV) or "").strip().lower()
    if flag not in _TRUTHY:
        return None
    source = stream if stream is not None else sys.stdin
    if source is None:
        raise LaunchAuthConfigError(
            f"{STDIN_LAUNCH_TOKEN_ENV}=1 is set, but stdin is unavailable"
        )
    raw_line = source.readline(512)
    if not raw_line:
        raise LaunchAuthConfigError(
            f"{STDIN_LAUNCH_TOKEN_ENV}=1 is set, but stdin closed before delivering a launch token"
        )
    token = raw_line.rstrip("\r\n").strip()
    port = expected_port
    if port is None:
        raw_port = (environ.get("OMNIVOICE_PORT") or "").strip()
        if raw_port.isdigit():
            port = int(raw_port)
    configure_launch_auth(token, expected_port=port)
    return token


def verify_launch_token(presented: str | None) -> bool:
    """Verify `presented` against the armed launch token in constant time."""
    with _lock:
        expected = _active_token
    if not expected or not isinstance(presented, str) or not presented:
        return False
    candidate = presented.strip()
    try:
        expected_bytes = expected.encode("ascii")
        candidate_bytes = candidate.encode("ascii")
    except UnicodeEncodeError:
        return False
    return hmac.compare_digest(candidate_bytes, expected_bytes)


def validate_loopback_host_header(
    host_header: str | None,
    *,
    expected_port: int | None = None,
) -> bool:
    """Validate that `Host` strictly names `127.0.0.1` (with optional or expected `<port>`)."""
    if not host_header or not isinstance(host_header, str):
        return False
    raw = host_header.strip()
    if not raw or any(ch in raw for ch in "/?#@\\ \t\r\n"):
        return False
    try:
        parsed = urlsplit(f"//{raw}")
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return False
    if hostname != LOOPBACK_BIND_HOST:
        return False
    with _lock:
        configured_port = expected_port if expected_port is not None else _expected_port
    if configured_port is not None:
        return port == configured_port
    return port is None or (1 <= port <= 65535)


def _normalize_origin(origin: str | None) -> str | None:
    if not origin or not isinstance(origin, str):
        return None
    raw = origin.strip()
    if not raw or raw.lower() == "null":
        return None
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return None
    if not parsed.scheme or not parsed.netloc or parsed.username or parsed.password:
        return None
    if parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        return None
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def validate_request_origin(
    origin_header: str | None,
    *,
    expected_port: int | None = None,
    extra_allowed_origins: Collection[str] = (),
) -> bool:
    """Allow native/CLI requests (no `Origin`) or trusted desktop/loopback origins; refuse foreign browser origins."""
    if origin_header is None:
        return True
    raw = origin_header.strip()
    if not raw or raw.lower() == "null":
        return False
    normalized = _normalize_origin(raw)
    if normalized is None:
        return False
    if normalized in TRUSTED_DESKTOP_ORIGINS:
        return True
    with _lock:
        configured_port = expected_port if expected_port is not None else _expected_port
        allowed = set(_extra_allowed_origins)
    for item in extra_allowed_origins:
        norm = _normalize_origin(item)
        if norm:
            allowed.add(norm)
    if configured_port is not None:
        allowed.add(f"http://127.0.0.1:{configured_port}")
    return normalized in allowed


def _extract_presented_token(headers: Mapping[str, str]) -> str | None:
    direct = headers.get(LAUNCH_TOKEN_HEADER)
    if direct:
        return direct.strip()
    auth = headers.get("authorization") or ""
    scheme, _, rest = auth.partition(" ")
    if scheme.lower() == "bearer" and rest.strip():
        return rest.strip()
    return None


def _is_loopback_peer(scope: dict) -> bool:
    client = scope.get("client")
    if not client:
        return True
    host = str(client[0] or "").strip().lower()
    return host in {"127.0.0.1", "::1", "localhost", "testclient"}


class LaunchAuthMiddleware:
    """Pure-ASGI sidecar authentication gate (zero response buffering)."""

    def __init__(
        self,
        app,
        *,
        expected_token: str | None = None,
        expected_port: int | None = None,
        extra_allowed_origins: Sequence[str] = (),
    ):
        self.app = app
        self._instance_token = expected_token.strip() if isinstance(expected_token, str) and expected_token.strip() else None
        if self._instance_token is not None and not is_valid_launch_token_shape(self._instance_token):
            raise LaunchAuthConfigError("expected_token must be at least 256 bits")
        self._instance_port = int(expected_port) if expected_port is not None else None
        self._instance_origins = tuple(extra_allowed_origins)

    async def __call__(self, scope, receive, send) -> None:
        armed = (self._instance_token is not None) or is_launch_auth_armed()
        if scope["type"] not in ("http", "websocket") or not armed:
            await self.app(scope, receive, send)
            return

        raw_headers = scope.get("headers") or ()
        host_headers: list[str] = []
        headers: dict[str, str] = {}
        for raw_k, raw_v in raw_headers:
            k_str = raw_k.decode("latin-1").lower()
            v_str = raw_v.decode("latin-1")
            if k_str == "host":
                host_headers.append(v_str)
            headers[k_str] = v_str

        if not _is_loopback_peer(scope):
            await self._reject(scope, receive, send, 403, "Loopback client required")
            return

        server = scope.get("server")
        if server and len(server) >= 1 and server[0]:
            srv_host = str(server[0]).strip().lower()
            allow_non_loopback = (
                os.environ.get("OMNIVOICE_ALLOW_NON_LOOPBACK", "").strip().lower() in _TRUTHY
                or os.environ.get("OMNIVOICE_SERVER_MODE", "").strip().lower() in _TRUTHY
            )
            if not allow_non_loopback and srv_host not in {"127.0.0.1", "localhost", "testserver"}:
                await self._reject(
                    scope,
                    receive,
                    send,
                    403,
                    "Sidecar listener must bind exclusively to 127.0.0.1",
                )
                return

        if len(host_headers) != 1:
            await self._reject(
                scope,
                receive,
                send,
                403,
                "Exactly one Host header required",
            )
            return

        if not validate_loopback_host_header(
            host_headers[0],
            expected_port=self._instance_port,
        ):
            await self._reject(
                scope,
                receive,
                send,
                403,
                "Invalid Host header; 127.0.0.1:<port> required",
            )
            return

        if "origin" in headers and not validate_request_origin(
            headers.get("origin"),
            expected_port=self._instance_port,
            extra_allowed_origins=self._instance_origins,
        ):
            await self._reject(scope, receive, send, 403, "Foreign browser Origin refused")
            return

        sec_fetch_site = headers.get("sec-fetch-site", "").strip().lower()
        if sec_fetch_site in {"cross-site", "same-site"}:
            await self._reject(
                scope,
                receive,
                send,
                403,
                "Cross-site or same-site browser request refused",
            )
            return

        presented = _extract_presented_token(headers)
        if self._instance_token is not None:
            ok = bool(
                presented
                and hmac.compare_digest(
                    presented.encode("utf-8"),
                    self._instance_token.encode("utf-8"),
                )
            )
        else:
            ok = verify_launch_token(presented)

        if not ok and scope["type"] == "websocket":
            raw_qs = (scope.get("query_string") or b"").decode("latin-1")
            parsed_qs = parse_qs(raw_qs, keep_blank_values=True)
            tickets = parsed_qs.get("ws_ticket") or []
            if len(tickets) == 1 and consume_ws_ticket(tickets[0], scope.get("path") or ""):
                ok = True

        if not ok:
            await self._reject(
                scope,
                receive,
                send,
                401,
                "Valid WisprStudio launch token required",
            )
            return

        await self.app(scope, receive, send)

    @staticmethod
    async def _reject(scope, receive, send, status_code: int, detail: str) -> None:
        if scope["type"] == "websocket":
            await receive()
            await send({"type": "websocket.close", "code": 1008, "reason": detail[:120]})
            return
        from starlette.responses import JSONResponse

        response = JSONResponse({"detail": detail}, status_code=status_code)
        await response(scope, receive, send)
