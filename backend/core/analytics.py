"""Zero-telemetry analytics stub for WisprStudio.

WisprStudio permanently disables product telemetry and outbound analytics
beacons. All public functions retain their call signatures for internal caller
compatibility while guaranteeing zero network calls, zero PostHog SDK imports,
and zero telemetry files on disk.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Optional

logger = logging.getLogger("omnivoice.analytics")

_client = None
_client_key: Optional[str] = None

_KILL_SWITCH = "OMNIVOICE_ANALYTICS_DISABLED"
_OFF_VALUES = {"1", "true", "yes", "on"}

_PUBLIC_PROJECT_TOKEN = ""
_DEFAULT_HOST = ""

_ALLOWED_PROPS: frozenset[str] = frozenset({
    "engine_id",
    "language",
    "mode",
    "kind",
    "source",
    "input_type",
    "effect_preset",
    "error_type",
    "duration_seconds",
    "gen_time_seconds",
    "text_length",
    "has_profile",
    "stream",
    "app_version",
    "platform",
    "from_version",
    "to_version",
    "exit_kind",
    "uptime_bucket",
    "error_class",
    "stage",
    "install_channel",
})

_MAX_STR_LEN = 64

_INSTALL_MARKER = "analytics_install_recorded"
_LAST_VERSION_MARKER = "analytics_last_version"
_ERROR_EVENT_CAP = 10
_error_fingerprints_sent: set[str] = set()
UNINSTALL_PING_INFO_BASENAME = "analytics_info.json"


def _kill_switched() -> bool:
    return True


def user_opted_in() -> bool:
    """Telemetry is permanently disabled in WisprStudio."""
    return False


def set_opted_in(enabled: bool) -> None:
    """Persist disabled state and remove any legacy uninstall-ping file."""
    try:
        from core import prefs

        prefs.set_("analytics_enabled", False)
        prefs.set_("analytics_prompted", True)
    except Exception:  # noqa: BLE001
        pass
    shutdown()
    sync_uninstall_ping_info()


def user_prompted() -> bool:
    """Never prompt the user for telemetry consent."""
    return True


def _resolved_token() -> str:
    return ""


def _resolved_host() -> str:
    return ""


def token_configured() -> bool:
    return False


def enabled() -> bool:
    return False


def _get_client():
    return None


def shutdown() -> None:
    global _client, _client_key
    _client, _client_key = None, None


def installation_id() -> str:
    from core import prefs

    iid = prefs.get("installation_id")
    if not iid:
        iid = str(uuid.uuid4())
        try:
            prefs.set_("installation_id", iid)
        except Exception:  # noqa: BLE001
            pass
    return str(iid)


def sanitize_properties(properties: Optional[dict]) -> dict:
    out: dict[str, Any] = {}
    for k, v in (properties or {}).items():
        if k not in _ALLOWED_PROPS:
            continue
        if isinstance(v, str) and len(v) > _MAX_STR_LEN:
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v
    return out


def capture(event: str, properties: Optional[dict] = None) -> None:
    """No-op: WisprStudio never transmits analytics events."""
    return None


def _app_version() -> str:
    try:
        from core.version import APP_VERSION

        return str(APP_VERSION)
    except Exception:  # noqa: BLE001
        return "unknown"


def _platform() -> str:
    import platform as _pl

    return {"darwin": "macos"}.get(_pl.system().lower(), _pl.system().lower() or "unknown")


def install_channel() -> str:
    ch = (os.environ.get("OMNIVOICE_INSTALL_CHANNEL", "") or "").strip().lower()
    if ch in {"installer", "docker", "source"}:
        return ch
    if (os.environ.get("OMNIVOICE_SERVER_MODE", "") or "").strip().lower() in _OFF_VALUES:
        return "docker"
    return "source"


def uptime_bucket(seconds: Optional[float]) -> str:
    if seconds is None:
        return "unknown"
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        return "unknown"
    if s < 10:
        return "lt_10s"
    if s < 60:
        return "lt_1m"
    if s < 600:
        return "lt_10m"
    if s < 3600:
        return "lt_1h"
    if s < 86400:
        return "lt_1d"
    return "ge_1d"


def record_startup_lifecycle(crash_record: Optional[dict] = None) -> None:
    """No-op startup hook; cleans up any legacy analytics_info.json."""
    sync_uninstall_ping_info()


def record_error_event(error_class: str, fingerprint: str, stage: str = "") -> None:
    return None


def _reset_error_events_for_tests() -> None:
    _error_fingerprints_sent.clear()


def sync_uninstall_ping_info() -> None:
    """Ensure no analytics_info.json exists on disk."""
    try:
        from core.config import DATA_DIR

        path = os.path.join(DATA_DIR, UNINSTALL_PING_INFO_BASENAME)
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
    except Exception:  # noqa: BLE001
        pass
