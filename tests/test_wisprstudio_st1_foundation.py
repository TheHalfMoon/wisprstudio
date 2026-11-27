"""ST-1 Qualification Suite: WisprStudio Identity, Zero-Egress Offline & Pure-DSP Watermarking."""
from __future__ import annotations

import json
import math
import os
import socket
import tomllib
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_wisprstudio_identity_and_agpl_notices():
    app_cfg = json.loads((REPO_ROOT / "config" / "app.json").read_text(encoding="utf-8"))
    assert app_cfg["productName"] == "WisprStudio"
    assert app_cfg["appId"] == "com.wispral.wisprstudio"

    from core.app_config import APP_ID, PRODUCT_NAME

    assert PRODUCT_NAME == "WisprStudio"
    assert APP_ID == "com.wispral.wisprstudio"

    pyproject_raw = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    pyproject = tomllib.loads(pyproject_raw)
    assert pyproject["project"]["license"] == "AGPL-3.0-only"
    assert "WisprStudio" in pyproject["project"]["description"]
    assert "hi@voicestudio.sh" not in pyproject_raw
    assert not any(dep.startswith("posthog") for dep in pyproject["project"]["dependencies"])
    assert pyproject["project"]["urls"]["Repository"] == "https://github.com/TheHalfMoon/wisprstudio"

    electron_pkg = json.loads((REPO_ROOT / "electron" / "package.json").read_text(encoding="utf-8"))
    assert electron_pkg["license"] == "AGPL-3.0-only"
    assert "WisprStudio" in electron_pkg["description"]
    assert "hi@voicestudio.sh" not in json.dumps(electron_pkg)
    assert electron_pkg["homepage"] == "https://github.com/TheHalfMoon/wisprstudio"

    license_txt = (REPO_ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in license_txt
    assert "Version 3, 19 November 2007" in license_txt

    notice_txt = (REPO_ROOT / "NOTICE").read_text(encoding="utf-8")
    assert "AGPL-3.0-only" in notice_txt
    assert "Debpalash" in notice_txt
    assert "Han Zhu" in notice_txt
    assert "https://github.com/TheHalfMoon/wisprstudio" in notice_txt
    assert "hi@voicestudio.sh" not in notice_txt

    readme_txt = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "WisprStudio" in readme_txt
    assert "https://github.com/TheHalfMoon/wisprstudio" in readme_txt
    assert "app.supermetry.com" not in readme_txt
    assert "voicestudio.sh/pro" not in readme_txt


def test_quiet_signal_studio_violet_tokens():
    css = (REPO_ROOT / "electron" / "src" / "renderer" / "src" / "styles" / "t3-theme.css").read_text(
        encoding="utf-8"
    )
    assert "#6340D0" in css
    assert "#A98BFF" in css

    palettes = (
        REPO_ROOT / "electron" / "src" / "renderer" / "src" / "lib" / "themes" / "t3-palettes.ts"
    ).read_text(encoding="utf-8")
    assert "#6340D0" in palettes
    assert "#A98BFF" in palettes


def test_telemetry_upsells_mirrors_and_ytdlp_disabled():
    from core import analytics
    from core.url_safety import remote_url_ingest_enabled
    from services import endpoint_race

    assert analytics.enabled() is False
    assert analytics.token_configured() is False
    analytics.set_opted_in(True)
    assert analytics.enabled() is False
    assert analytics.user_opted_in() is False

    # Unsolicited mirrors removed
    assert endpoint_race.COMMUNITY_MIRROR == ""
    assert endpoint_race.candidates(cn_hint=True) == [endpoint_race.CANONICAL_ENDPOINT]
    assert endpoint_race._is_allowed_probe_endpoint("https://hf-mirror.com") is False

    runtime_ts = (REPO_ROOT / "electron" / "src" / "main" / "runtime-project.ts").read_text(
        encoding="utf-8"
    )
    pypi_ts = (REPO_ROOT / "electron" / "src" / "main" / "pypi-mirror.ts").read_text(
        encoding="utf-8"
    )
    assert "gh-proxy.com" not in runtime_ts
    assert "ghproxy.net" not in runtime_ts
    assert "mirrors.aliyun.com" not in runtime_ts
    assert "mirrors.aliyun.com" not in pypi_ts

    # Account cloud disabled
    account_cfg = json.loads((REPO_ROOT / "config" / "account.json").read_text(encoding="utf-8"))
    assert "voicestudio.sh" not in json.dumps(account_cfg)
    assert all(env["clientId"] == "" for env in account_cfg["environments"].values())

    # Uninstall scripts carry zero outbound capture calls
    assert "/capture/" not in (REPO_ROOT / "scripts" / "uninstall.ps1").read_text(encoding="utf-8")
    assert "/capture/" not in (REPO_ROOT / "scripts" / "uninstall.sh").read_text(encoding="utf-8")

    # yt-dlp remote URL scraping disabled by default
    assert remote_url_ingest_enabled() is False
    from services import media_tools

    with pytest.raises(PermissionError, match="disabled by default"):
        media_tools.update_ytdlp()


@pytest.mark.parametrize("sample_rate", [8000, 16000, 22050, 24000, 32000, 44100, 48000])
def test_pure_dsp_qim_watermarker_roundtrip_and_snr(tmp_path, sample_rate):
    from services import watermark_dsp as wd

    payload = bytes.fromhex("fedcba98765432100123456789abcdef")
    t = np.arange(int(sample_rate * 1.0), dtype=np.float64) / sample_rate
    signal = 0.28 * np.sin(2 * math.pi * 440.0 * t) + 0.14 * np.sin(2 * math.pi * 1210.0 * t)

    marked = wd.embed_qim_watermark(signal, sample_rate, payload)
    snr_db = wd.compute_snr_db(signal, marked)
    assert snr_db >= 32.0, f"Expected SNR >= 32 dB at {sample_rate} Hz, got {snr_db:.2f} dB"

    verified = wd.extract_and_verify_watermark(marked, sample_rate, expected_payload=payload)
    assert verified["verified"] is True
    assert verified["scheme"] == "wispral-qim-v1"
    assert verified["payload_bytes"] == payload
    assert verified["crc16_valid"] is True

    # 16-bit PCM WAV round-trip via stdlib wave
    wav_file = tmp_path / f"marked_{sample_rate}.wav"
    wd.write_pcm16_wav(wav_file, marked, sample_rate)
    reloaded, sr_out, _ = wd.read_pcm16_wav(wav_file)
    assert sr_out == sample_rate
    verified_wav = wd.extract_and_verify_watermark(reloaded, sr_out, expected_payload=payload)
    assert verified_wav["verified"] is True
    assert verified_wav["payload_bytes"] == payload


def test_pure_dsp_qim_pure_python_fallback_and_tamper_fail_closed():
    from services import watermark_dsp as wd

    sr = 16000
    payload = bytes.fromhex("aabbccddeeff00112233445566778899")
    samples = [0.22 * math.sin(2 * math.pi * 520.0 * n / sr) for n in range(sr)]
    marked = wd.embed_qim_watermark(samples, sr, payload, force_pure_python=True)
    assert wd.compute_snr_db(samples, marked) >= 32.0

    ok = wd.extract_and_verify_watermark(marked, sr, expected_payload=payload, force_pure_python=True)
    assert ok["verified"] is True
    assert ok["payload_bytes"] == payload

    # Unwatermarked fails closed
    assert wd.extract_and_verify_watermark(samples, sr)["verified"] is False

    # Wrong expected payload fails closed
    wrong = wd.extract_and_verify_watermark(marked, sr, expected_payload=b"\x00" * 16)
    assert wrong["verified"] is False
    assert wrong["tampered"] is True

    # Mid-clip zeroing / splice fails closed
    spliced = list(marked)
    for idx in range(len(spliced) // 3):
        spliced[idx] = 0.0
    tamp = wd.extract_and_verify_watermark(spliced, sr)
    assert tamp["verified"] is False
    assert tamp["tampered"] is True


def test_socket_guard_blocks_non_loopback_and_allows_loopback():
    assert os.environ.get("HF_HUB_OFFLINE") == "1"

    # Non-loopback TCP connect must fail immediately under the unit-test guard
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as ext_sock:
        with pytest.raises(ConnectionRefusedError, match="Blocked non-loopback network egress"):
            ext_sock.connect(("198.51.100.42", 443))

    with pytest.raises(ConnectionRefusedError, match="Blocked non-loopback network egress"):
        socket.create_connection(("example.com", 443), timeout=0.5)

    # Loopback TCP server + client must remain allowed
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        with socket.create_connection(("127.0.0.1", port), timeout=2.0) as cli:
            conn, _ = srv.accept()
            with conn:
                cli.sendall(b"ok")
                assert conn.recv(2) == b"ok"


def test_windows_git_bash_and_filename_sanitization(monkeypatch):
    from core.path_security import portable_filename
    from core.shell_tools import is_wsl_bash_stub, posix_bash_path, resolve_posix_bash

    assert is_wsl_bash_stub(r"C:\Windows\System32\bash.exe") is True
    assert is_wsl_bash_stub(r"C:\Windows\Sysnative\bash.exe") is True
    assert is_wsl_bash_stub(r"C:\Users\dev\AppData\Local\Microsoft\WindowsApps\bash.exe") is True
    assert is_wsl_bash_stub(r"C:\Program Files\Git\bin\bash.exe") is False

    resolved = resolve_posix_bash(
        which=lambda _name: r"C:\Windows\System32\bash.exe",
        env={"ProgramFiles": r"Z:\nonexistent-git", "ProgramW6432": r"Z:\nonexistent-git", "LOCALAPPDATA": r"Z:\nonexistent"},
    )
    assert resolved is None

    path_val = posix_bash_path(["D:/fake-bin"], bash_executable=None)
    assert ":/usr/bin:/bin" not in path_val if os.name == "nt" else True

    assert portable_filename('Voice: <Test> "A|B?*\\/"') == "Voice_ _Test_ _A_B_____"
    assert portable_filename("CON.wav") == "_CON.wav"
    assert portable_filename("NUL") == "_NUL"


def test_long_waveform_over_35s_24khz_roundtrip_and_clone_force_watermark(monkeypatch):
    """Regression guard for >30s chunk phase alignment and mandatory clone watermarking."""
    import math
    import numpy as np
    from services import watermark as wm_mod
    from services.watermark_dsp import compute_snr_db, extract_and_verify_watermark

    sr = 24000
    duration_s = 36.5  # >35s -> spans multiple _iter_chunks slices at 24 kHz
    t = np.arange(int(duration_s * sr), dtype=np.float32) / float(sr)
    waveform = (
        0.25 * np.sin(2.0 * math.pi * 220.0 * t)
        + 0.15 * np.sin(2.0 * math.pi * 440.0 * t)
        + 0.10 * np.sin(2.0 * math.pi * 880.0 * t)
    ).astype(np.float32)

    payload = b"wispr-long36s-ok"
    # Even if user sets `watermark.invisible = False`, `watermark_required=True` MUST mark!
    monkeypatch.setattr(wm_mod, "is_enabled", lambda: False)
    marked = wm_mod.mark_synthetic(
        waveform,
        sr,
        context="test.long_clone",
        watermark_required=True,
        payload=payload,
    )
    assert compute_snr_db(waveform, marked) >= 32.0
    verdict = extract_and_verify_watermark(marked, sr, expected_payload=payload)
    assert verdict["verified"] is True, verdict
    assert verdict["tampered"] is False
    assert verdict["payload_bytes"] == payload
    assert verdict["frame_count"] >= 200

    # Fail-closed when required watermarker is unavailable
    monkeypatch.setattr(wm_mod, "_audioseal_available", False)
    with pytest.raises(wm_mod.WatermarkError):
        wm_mod.mark_synthetic(
            waveform[: sr * 2],
            sr,
            context="test.unavailable_clone",
            watermark_required=True,
            payload=payload,
        )
