"""Sponsor roster lockstep guard for WisprStudio (zero commercial ad/sponsor placements)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_CONFIG = _ROOT / "electron" / "src" / "shared" / "config" / "sponsors.js"
_READMES = [_ROOT / "README.md", *sorted((_ROOT / "docs" / "readme").glob("README_*.md"))]
_LOGO_LINK = re.compile(r'<a href="(?P<url>[^"]+)"><picture>(?P<body>.*?)</picture></a>')


def _config_text() -> str:
    return _CONFIG.read_text(encoding="utf-8")


def _in_app_tiers() -> list[str]:
    match = re.search(r"export const SPONSOR_TIERS = \[([^\]]*)\]", _config_text())
    assert match, "SPONSOR_TIERS not found"
    return re.findall(r"'([^']+)'", match.group(1))


def test_in_app_tiers_match_funding_json():
    plans = json.loads((_ROOT / "funding.json").read_text(encoding="utf-8"))["funding"]["plans"]
    tiers = [p["guid"].removesuffix("-sponsor") for p in plans if p["guid"] != "one-time"]
    assert _in_app_tiers() == list(reversed(tiers))


def test_in_app_sponsors_are_empty():
    assert "export const SPONSORS = [];" in _config_text()


def test_sponsors_md_has_no_active_sponsor_logos():
    text = (_ROOT / "SPONSORS.md").read_text(encoding="utf-8")
    assert "## Current sponsors" in text
    assert _LOGO_LINK.findall(text) == []


@pytest.mark.parametrize("path", _READMES, ids=lambda p: p.name)
def test_readmes_contain_no_supermetry_pixel_or_sponsor_banners(path):
    text = path.read_text(encoding="utf-8")
    assert "app.supermetry.com/px/" not in text
    assert _LOGO_LINK.findall(text) == []
