"""Opt-in analytics gates remain permanently false in WisprStudio."""
from __future__ import annotations

import os

os.environ.setdefault("OMNIVOICE_MODEL", "test")
os.environ.setdefault("OMNIVOICE_DISABLE_FILE_LOG", "1")

from core import analytics


def test_analytics_permanently_disabled_regardless_of_env_or_prefs(monkeypatch, tmp_path):
    from core import config, prefs

    monkeypatch.setattr(prefs, "_PREFS_PATH", str(tmp_path / "prefs.json"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setenv("POSTHOG_PROJECT_TOKEN", "phc_ignored")

    assert analytics.token_configured() is False
    assert analytics.user_opted_in() is False
    assert analytics.user_prompted() is True
    assert analytics.enabled() is False

    analytics.set_opted_in(True)
    assert analytics.user_opted_in() is False
    assert analytics.enabled() is False
