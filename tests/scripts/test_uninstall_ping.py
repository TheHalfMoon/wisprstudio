"""Uninstall scripts never phone home or send PostHog uninstall beacons."""
from __future__ import annotations

import os
import re

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SH = os.path.join(REPO, "scripts", "uninstall.sh")
PS1 = os.path.join(REPO, "scripts", "uninstall.ps1")


def test_uninstall_scripts_contain_no_telemetry_beacon_or_token():
    for path in (SH, PS1):
        with open(path, encoding="utf-8-sig") as f:
            src = f.read()
        assert "posthog" not in src.lower()
        assert "app_uninstalled" not in src
        assert "/capture/" not in src
        assert "Invoke-RestMethod" not in src
        assert not re.search(r"phc_[A-Za-z0-9]{10,}", src)
