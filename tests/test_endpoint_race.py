"""Hugging Face endpoint selection in WisprStudio (canonical-only, zero unsolicited mirrors)."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))


@pytest.fixture
def er(monkeypatch, tmp_path):
    from core import prefs

    monkeypatch.setattr(prefs, "_PREFS_PATH", str(tmp_path / "prefs.json"))
    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    monkeypatch.delenv("OMNIVOICE_HF_ENDPOINT_MODE", raising=False)
    import services.endpoint_race as er_mod

    monkeypatch.setattr(er_mod, "_FAILOVER_ATTEMPTED", set())
    return er_mod


def test_candidates_contain_only_canonical_huggingface(er):
    assert er.COMMUNITY_MIRROR == ""
    assert er.candidates(cn_hint=False) == [er.CANONICAL_ENDPOINT]
    assert er.candidates(cn_hint=True) == [er.CANONICAL_ENDPOINT]


@pytest.mark.parametrize(
    "endpoint",
    [
        "file:///etc/passwd",
        "http://huggingface.co",
        "https://hf-mirror.com",
        "https://hf-mirror.com/",
        "https://huggingface.co.evil.example",
        "https://huggingface.co@evil.example",
        "https://huggingface.co:444",
        "https://huggingface.co/model",
        "https://huggingface.co?redirect=file:///etc/passwd",
    ],
)
def test_probe_rejects_unapproved_and_third_party_mirror_origins(er, endpoint):
    assert er._is_allowed_probe_endpoint(endpoint) is False


def test_probe_allows_only_canonical_huggingface_origin(er):
    assert er._is_allowed_probe_endpoint("https://huggingface.co") is True


def test_explicit_setting_and_env_still_respected_when_configured_by_user(er, monkeypatch):
    monkeypatch.setenv("HF_ENDPOINT", "https://custom-hf.internal.example")
    assert er.effective_endpoint() == "https://custom-hf.internal.example"


def test_auto_mode_uses_canonical_without_mirror_failover(er):
    assert er.effective_endpoint() in (None, er.CANONICAL_ENDPOINT)
    assert er.download_endpoint() in (None, er.CANONICAL_ENDPOINT)
    assert er.candidates(cn_hint=True) == [er.CANONICAL_ENDPOINT]
