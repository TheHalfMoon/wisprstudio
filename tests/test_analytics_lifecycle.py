"""Backend lifecycle analytics is permanently disabled in WisprStudio (zero telemetry)."""
from __future__ import annotations

import os
import sys
import types

os.environ.setdefault("OMNIVOICE_MODEL", "test")
os.environ.setdefault("OMNIVOICE_DISABLE_FILE_LOG", "1")

import pytest

from core import analytics


@pytest.fixture()
def isolated(monkeypatch, tmp_path):
    from core import config, prefs

    monkeypatch.setattr(prefs, "_PREFS_PATH", str(tmp_path / "prefs.json"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setenv("POSTHOG_PROJECT_TOKEN", "phc_should_be_ignored")
    events: list[tuple[str, dict]] = []

    class FakePosthog:
        def __init__(self, *args, **kwargs):
            events.append(("init", {}))

        def capture(self, event, distinct_id=None, properties=None):
            events.append((event, dict(properties or {})))

    fake = types.ModuleType("posthog")
    fake.Posthog = FakePosthog
    monkeypatch.setitem(sys.modules, "posthog", fake)
    return events, tmp_path


def test_lifecycle_events_never_initialize_posthog_or_capture(isolated):
    events, _ = isolated
    analytics.set_opted_in(True)
    analytics.record_startup_lifecycle(
        {"version": "0.5.0", "started_at": 100.0, "last_seen_at": 200.0}
    )
    analytics.capture("generation_completed", {"engine_id": "kokoro", "text": "secret"})
    analytics.record_error_event("RuntimeError", "fp1", stage="tts")
    assert analytics.enabled() is False
    assert analytics.token_configured() is False
    assert events == []


def test_legacy_analytics_info_file_is_removed(isolated):
    _, tmp_path = isolated
    info = tmp_path / "analytics_info.json"
    info.write_text('{"token":"phc_legacy"}', encoding="utf-8")
    analytics.set_opted_in(True)
    assert not info.exists()
