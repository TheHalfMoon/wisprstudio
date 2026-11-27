"""Zero PostHog token guard for WisprStudio.

WisprStudio ships with telemetry permanently disabled; NO `phc_` token literal
may appear in any tracked file in the repository.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_POSTHOG_KEY_RE = re.compile(r"phc_[A-Za-z0-9]{20,}")
_SKIP_DIRS = {"node_modules", ".git", "target", "dist", "build", ".venv", "zig-out"}
_SCAN_EXT = {".ts", ".tsx", ".js", ".jsx", ".py", ".rs", ".json", ".yml", ".yaml", ".md", ".env"}


def _tracked_files():
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=_REPO, capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout
    for name in (n for n in out.split("\0") if n):
        p = Path(name)
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        if p.suffix.lower() in _SCAN_EXT:
            yield name, _REPO / p


def test_no_posthog_token_literals_anywhere_in_repo():
    offenders = []
    for name, path in _tracked_files():
        if name == "tests/test_no_committed_analytics_token.py":
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if _POSTHOG_KEY_RE.search(text):
            offenders.append(name)

    assert not offenders, f"PostHog token literal found in tracked files: {offenders}"


def test_analytics_permanently_disabled():
    from core import analytics

    assert analytics.token_configured() is False
    assert analytics.user_opted_in() is False
    assert analytics.enabled() is False
    analytics.set_opted_in(True)
    assert analytics.enabled() is False
