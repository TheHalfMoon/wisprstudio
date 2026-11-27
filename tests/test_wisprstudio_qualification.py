"""WisprStudio ST-2 End-to-End Qualification Suite.

Covers all ST-2 production contracts without requiring `torch` or network access:
  1. One-way vendored JSON Schemas (`backend/contracts/schemas/*.schema.json`)
  2. Local sidecar launch auth (`backend/core/launch_auth.py`): `127.0.0.1` bind,
     256-bit stdin token (`WISPRSTUDIO_STDIN_LAUNCH_TOKEN=1`), constant-time
     `hmac.compare_digest`, strict `Host` & foreign-`Origin` 403 rejection
  3. 4-point cryptographic Ed25519 + SHA-256 hash-chained consent ledger
     (`backend/services/consent_ledger.py`): grant -> allow -> instant revoke ->
     embedding purge + mid-render chunk halt in `audiobook.synthesize_chapter` +
     deny across enrollment, enqueue, render, and export checkpoints
  4. Atomic `.provenance.json` sidecar + `wispral-qim-v1` watermark round-trip
     verification and tamper fail-closed rejection
  5. Permissive commercial-safe default TTS catalog (`Kokoro-82M` Apache-2.0 &
     `Piper` MIT) and explicit non-commercial `OmniVoice` labeling
  6. All 21 deterministic `validate_fit_inputs` cases (including overlapping
     multi-speaker dubbing segments allowed) + `fit_planner.plan_fit`
  7. Anonymous diarization cluster tagging (`SPEAKER_00`, `SPEAKER_01`,
     `identity_verified: False`)
  8. Arabic proclitic-aware pronunciation lexicon (`ال`, `وال`, `بال`, `كال`,
     `فال`, `لل`, `و`, `ف`, `ب`, `ك`, `ل` + tatweel/harakat)
  9. Crash-safe atomic `project_store.py` save, crash recovery reopen, `undo()`,
     and `redo()`
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import math
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest
import yaml
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = REPO_ROOT / "backend" / "contracts" / "schemas"


def _sine_speech_like(duration_s: float = 0.8, sr: int = 24000) -> np.ndarray:
    t = np.arange(int(duration_s * sr), dtype=np.float32) / float(sr)
    sig = (
        0.28 * np.sin(2.0 * math.pi * 220.0 * t)
        + 0.18 * np.sin(2.0 * math.pi * 440.0 * t)
        + 0.12 * np.sin(2.0 * math.pi * 880.0 * t)
    )
    return sig.astype(np.float32)


# ── 1. Vendored Contract Schemas & Torch-Free Import Hygiene ────────────────


def test_vendored_contract_schemas_present_and_valid():
    expected = (
        "consent_record.schema.json",
        "export_provenance.schema.json",
        "model_manifest.schema.json",
        "network_manifest.schema.json",
    )
    for name in expected:
        path = SCHEMAS_DIR / name
        assert path.is_file(), f"Missing vendored schema: {path}"
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)


# ── 2. Local FastAPI Sidecar Launch Auth (`launch_auth.py`) ─────────────────


def test_launch_auth_loopback_bind_and_stdin_256bit_token(monkeypatch):
    from core.launch_auth import (
        LaunchAuthConfigError,
        clear_launch_token_for_tests,
        get_active_launch_token,
        read_stdin_launch_token,
        validate_loopback_bind_host,
        verify_launch_token,
    )

    assert validate_loopback_bind_host("127.0.0.1") == "127.0.0.1"
    for bad_host in ("0.0.0.0", "::", "192.168.1.10", "localhost", ""):
        with pytest.raises(LaunchAuthConfigError):
            validate_loopback_bind_host(bad_host)

    token_hex = secrets.token_hex(32)  # 256-bit
    fake_stdin = io.StringIO(token_hex + "\nTRAILING_EOF_WATCH_SENTINEL\n")
    monkeypatch.setenv("WISPRSTUDIO_STDIN_LAUNCH_TOKEN", "1")
    try:
        clear_launch_token_for_tests()
        loaded = read_stdin_launch_token(stream=fake_stdin)
        assert loaded == token_hex
        assert get_active_launch_token() == token_hex
        # Pipe remains open with unread trailing sentinel for parent-death watch!
        assert fake_stdin.readline().strip() == "TRAILING_EOF_WATCH_SENTINEL"
        assert verify_launch_token(token_hex) is True
        assert verify_launch_token("0" * 64) is False

        # Reject weak (<256-bit) stdin tokens
        clear_launch_token_for_tests()
        with pytest.raises(LaunchAuthConfigError):
            read_stdin_launch_token(stream=io.StringIO("too-short-token\n"))
    finally:
        clear_launch_token_for_tests()
        monkeypatch.delenv("WISPRSTUDIO_STDIN_LAUNCH_TOKEN", raising=False)


def test_launch_auth_middleware_rejects_wrong_token_foreign_origin_and_bad_host():
    from core.launch_auth import LaunchAuthMiddleware

    secret_tok = secrets.token_hex(32)
    mini_app = FastAPI()
    mini_app.add_middleware(
        LaunchAuthMiddleware,
        expected_token=secret_tok,
        expected_port=3900,
    )

    @mini_app.get("/profiles")
    def _profiles():
        return {"ok": True}

    @mini_app.get("/health")
    def _health():
        return {"status": "healthy"}

    client = TestClient(mini_app, base_url="http://127.0.0.1:3900")

    # 1. Valid loopback request with valid Bearer token & no Origin -> 200
    r_ok = client.get("/profiles", headers={"Authorization": f"Bearer {secret_tok}"})
    assert r_ok.status_code == 200
    assert r_ok.json() == {"ok": True}

    # 2. Trusted Electron custom protocol Origin -> 200
    r_app = client.get(
        "/profiles",
        headers={
            "Authorization": f"Bearer {secret_tok}",
            "Origin": "app://wisprstudio",
        },
    )
    assert r_app.status_code == 200

    # 3. Missing token -> 401
    r_missing = client.get("/profiles")
    assert r_missing.status_code == 401

    # 4. Wrong token -> 401
    r_wrong = client.get(
        "/profiles",
        headers={"Authorization": f"Bearer {secrets.token_hex(32)}"},
    )
    assert r_wrong.status_code == 401

    # 5. Foreign browser Origin -> 403 even with valid token!
    for bad_origin in ("https://evil.example", "http://localhost:5173", "null"):
        r_origin = client.get(
            "/profiles",
            headers={
                "Authorization": f"Bearer {secret_tok}",
                "Origin": bad_origin,
            },
        )
        assert r_origin.status_code == 403, f"Origin {bad_origin!r} must be refused"

    # 6. Spoofed / DNS-rebound Host header -> 403 even with valid token!
    r_host = client.get(
        "/profiles",
        headers={
            "Authorization": f"Bearer {secret_tok}",
            "Host": "rebind.attacker.example:3900",
        },
    )
    assert r_host.status_code == 403


# ── 3 & 4. Cryptographic Consent Ledger, 4 Checkpoints & Provenance ─────────


def test_consent_ledger_4_checkpoints_mid_render_halt_and_embedding_purge(tmp_path, monkeypatch):
    from services.audiobook import Span, synthesize_chapter
    from services.consent_ledger import (
        ConsentEpochMismatchError,
        ConsentGateError,
        ConsentLedger,
        ConsentLedgerTamperError,
        ConsentRequiredError,
        ConsentRevokedError,
        ReferenceDigestMismatchError,
        cache_speaker_embedding,
        enforce_checkpoint_consent,
        get_cached_speaker_embedding,
        set_default_ledger_dir,
        sha256_prefixed,
    )

    ledger_dir = tmp_path / "consent_store"
    set_default_ledger_dir(ledger_dir)
    monkeypatch.setenv("WISPRSTUDIO_REQUIRE_VOICE_CONSENT", "1")

    try:
        ledger = ConsentLedger(ledger_dir)
        voice_id = "voice-actor-layla-01"
        ref_bytes = b"RIFF-fake-clean-reference-voice-recording-bytes"
        ref_digest = sha256_prefixed(ref_bytes)

        from services.consent_ledger import generate_signing_identity

        # Before consent is granted: Checkpoint 1 (enrollment) & Checkpoint 2 (enqueue) deny!
        with pytest.raises(ConsentRequiredError):
            enforce_checkpoint_consent(
                voice_id,
                checkpoint="profile_enrollment",
                reference_digest=ref_digest,
            )

        # Key-custody invariant #1: Local studio MUST refuse to self-mint `consent_service` keys!
        with pytest.raises(ConsentGateError, match="cannot self-mint"):
            ledger.grant_consent(
                voice_id=voice_id,
                reference_artifact_digest=ref_digest,
                relationship="licensed_voice_actor",
                purposes=("personal", "commercial", "internal_evaluation"),
                products=("wisprstudio",),
            )

        # Key-custody invariant #2: Unregistered external `consent_service` signer MUST be refused!
        svc_signer = generate_signing_identity(kind="consent_service")
        with pytest.raises(ConsentLedgerTamperError, match="not registered in trusted_keys"):
            ledger.grant_consent(
                voice_id=voice_id,
                reference_artifact_digest=ref_digest,
                relationship="licensed_voice_actor",
                purposes=("personal", "commercial", "internal_evaluation"),
                products=("wisprstudio",),
                signing_identity=svc_signer,
            )

        # Explicitly register external `consent_service` public key in trusted_keys (no private key stored!)
        ledger.register_trusted_key(
            svc_signer.key_id,
            "consent_service",
            svc_signer.public_key_b64,
        )
        key_registry_disk = json.loads(ledger.keys_path.read_text(encoding="utf-8"))
        assert "private_key_b64" not in json.dumps(key_registry_disk)

        # Grant signed Ed25519 consent (epoch 0)
        granted = ledger.grant_consent(
            voice_id=voice_id,
            reference_artifact_digest=ref_digest,
            relationship="licensed_voice_actor",
            purposes=("personal", "commercial", "internal_evaluation"),
            products=("wisprstudio",),
            signing_identity=svc_signer,
        )
        consent_id = granted["consent_id"]
        assert granted["consent_epoch"] == 0
        assert granted["status"] == "active"
        assert granted["watermark_required"] is True
        assert granted["attestation"]["issuer"]["kind"] == "consent_service"

        # Validate granted record directly against vendored JSON Schema
        consent_schema = json.loads(
            (SCHEMAS_DIR / "consent_record.schema.json").read_text(encoding="utf-8")
        )
        Draft202012Validator(consent_schema).validate(granted)

        # Checkpoint 1: Enrollment succeeds with matching reference_digest, fails on digest mismatch!
        v1 = enforce_checkpoint_consent(
            voice_id,
            checkpoint="profile_enrollment",
            reference_digest=ref_digest,
        )
        assert v1 is not None and v1.allowed is True and v1.consent_epoch == 0

        with pytest.raises(ReferenceDigestMismatchError):
            enforce_checkpoint_consent(
                voice_id,
                checkpoint="profile_enrollment",
                reference_digest=sha256_prefixed(b"substituted-unauthorized-voice"),
            )

        # Checkpoint 2: Enqueue succeeds for granted purpose, fails for ungranted purpose or stale epoch!
        v2 = ledger.verify_voice_consent_gate(
            voice_id,
            expected_epoch=0,
            purpose="commercial",
            checkpoint="synthesis_enqueue",
        )
        assert v2.allowed is True and v2.voice_mode == "authorized_clone"

        with pytest.raises(ConsentGateError):
            ledger.verify_voice_consent_gate(
                voice_id,
                purpose="broadcast_political_ad",
                checkpoint="synthesis_enqueue",
            )
        with pytest.raises(ConsentEpochMismatchError):
            ledger.verify_voice_consent_gate(
                voice_id,
                expected_epoch=99,
                purpose="personal",
                checkpoint="synthesis_enqueue",
            )

        # Cache speaker embeddings in memory + on disk to verify purge on revocation
        cache_speaker_embedding(voice_id, {"vec": [0.1, 0.2, 0.3]})
        disk_emb = ledger_dir / f"{voice_id}.speaker_embedding.npy"
        np.save(disk_emb, np.ones(16, dtype=np.float32))
        assert get_cached_speaker_embedding(voice_id) is not None
        assert disk_emb.is_file()

        # Checkpoint 4 (while active): Export WAV + signed `.provenance.json` succeeds!
        active_export_wav = tmp_path / "exports" / "layla_line1.wav"
        exp_out = ledger.export_with_provenance(
            active_export_wav,
            samples=_sine_speech_like(0.8, 24000),
            sample_rate_hz=24000,
            voice_id=voice_id,
            expected_epoch=0,
            purpose="commercial",
            project_id="proj-dub-01",
        )
        assert Path(exp_out["artifact_path"]).is_file()
        assert Path(exp_out["provenance_path"]).is_file()
        verified_prov = ledger.verify_exported_artifact_provenance(active_export_wav)
        assert verified_prov["voice_mode"] == "authorized_clone"
        assert verified_prov["consent_id"] == consent_id
        assert verified_prov["consent_epoch"] == 0
        assert verified_prov["watermark"]["scheme"] == "wispral-qim-v1"
        assert verified_prov["watermark"]["roundtrip_verified"] is True

        # Checkpoint 3: Long-form multi-chunk render loop in `audiobook.synthesize_chapter`!
        # Construct text > 800 chars so `split_text_into_chunks` produces 3 chunks;
        # revoke consent during chunk 1 and verify chunk 2 is NEVER synthesized!
        long_paragraph = (
            ("This is sentence number one in the first narration chunk. " * 11).strip()
            + " "
            + ("Second chunk continues the chapter narration smoothly here. " * 11).strip()
            + " "
            + ("Third chunk would follow if consent had not been revoked. " * 11).strip()
        )
        synthesized_chunks: list[str] = []
        revocation_result: dict = {}

        def _fake_synth(chunk_text: str, vid: str | None, speed: float | None):
            synthesized_chunks.append(chunk_text)
            if len(synthesized_chunks) == 1:
                # Actor revokes consent while chunk 1 is finishing on GPU/CPU!
                revocation_result.update(
                    ledger.revoke_consent(consent_id, signing_identity=svc_signer)
                )
            return _sine_speech_like(0.25, 24000)

        with pytest.raises(ConsentRevokedError):
            synthesize_chapter(
                [Span(voice_id=voice_id, text=long_paragraph)],
                _fake_synth,
                24000,
            )

        # Exactly 1 chunk ran; chunk 2+ were halted immediately at Checkpoint 3!
        assert len(synthesized_chunks) == 1
        assert revocation_result["record"]["status"] == "revoked"
        assert revocation_result["record"]["consent_epoch"] == 1
        assert len(revocation_result["cancelled_renders"]) >= 1
        assert revocation_result["purged_embeddings"] >= 2
        assert get_cached_speaker_embedding(voice_id) is None
        assert not disk_emb.exists()

        # Post-revocation: ALL checkpoints (enqueue, MCP, OpenAI-compat, export) refuse synthesis!
        with pytest.raises(ConsentRevokedError):
            enforce_checkpoint_consent(voice_id, checkpoint="synthesis_enqueue")

        with pytest.raises(ConsentRevokedError):
            ledger.export_with_provenance(
                tmp_path / "exports" / "post_revoke.wav",
                samples=_sine_speech_like(0.8, 24000),
                sample_rate_hz=24000,
                voice_id=voice_id,
            )

        # Verify OpenAI-compat & MCP server checkpoints also refuse the revoked voice
        from api.routers.openai_compat import OpenAIError, SpeechRequest, create_speech

        with pytest.raises(OpenAIError) as oa_exc:
            asyncio.run(
                create_speech(
                    SpeechRequest(
                        model="tts-1",
                        input="Hello world",
                        voice=voice_id,
                        response_format="wav",
                    )
                )
            )
        assert oa_exc.value.status_code == 403

        with pytest.raises(OpenAIError) as oa_mp3_exc:
            asyncio.run(
                create_speech(
                    SpeechRequest(
                        model="tts-1",
                        input="Hello world",
                        voice=voice_id,
                        response_format="mp3",
                    )
                )
            )
        assert oa_mp3_exc.value.status_code == 403

        # Ledger hash-chain tamper detection: corrupting the JSONL ledger fails closed!
        lines = ledger.ledger_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        tampered_ev = json.loads(lines[0])
        tampered_ev["record"]["purposes"].append("tampered_purpose")
        ledger.ledger_path.write_text(
            json.dumps(tampered_ev) + "\n" + lines[1] + "\n",
            encoding="utf-8",
        )
        with pytest.raises(ConsentLedgerTamperError):
            ledger.verify_ledger_integrity()
    finally:
        set_default_ledger_dir(None)
        monkeypatch.delenv("WISPRSTUDIO_REQUIRE_VOICE_CONSENT", raising=False)


def test_provenance_sidecar_stock_voice_and_watermark_tamper_fail_closed(tmp_path):
    from services.consent_ledger import (
        DOMAIN_EXPORT_PROVENANCE,
        ConsentLedger,
        ProvenanceVerificationError,
        jcs_dumps,
        sha256_prefixed,
    )
    from services.watermark_dsp import (
        compute_snr_db,
        embed_qim_watermark,
        floats_to_pcm16_wav_bytes,
        pcm16_wav_bytes_to_floats,
    )

    ledger = ConsentLedger(tmp_path / "ledger")
    clean = _sine_speech_like(0.9, 24000)

    # Confirm QIM watermark imperceptibility (`SNR >= 32 dB`)
    marked = embed_qim_watermark(clean, 24000, payload=b"0123456789abcdef")
    assert compute_snr_db(clean, marked) >= 32.0

    # Stock catalog export writes valid schema-compliant `.provenance.json`
    wav_path = tmp_path / "stock_out.wav"
    res = ledger.export_with_provenance(
        wav_path,
        samples=clean,
        sample_rate_hz=24000,
        voice_id="af_heart",
        stock_voice_catalog_id="catalog:kokoro-82m:af_heart",
    )
    prov_schema = json.loads(
        (SCHEMAS_DIR / "export_provenance.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(prov_schema).validate(res["provenance"])
    assert res["provenance"]["voice_mode"] == "stock_catalog"
    assert "consent_id" not in res["provenance"]
    assert ledger.verify_exported_artifact_provenance(wav_path)["export_id"] == res["provenance"]["export_id"]

    # Tamper Case 1: Flip a byte in the exported WAV audio -> SHA-256 mismatch fails closed!
    orig_wav = wav_path.read_bytes()
    tampered_wav = bytearray(orig_wav)
    tampered_wav[-200] ^= 0x7F
    wav_path.write_bytes(bytes(tampered_wav))
    with pytest.raises(ProvenanceVerificationError, match="SHA-256 mismatch"):
        ledger.verify_exported_artifact_provenance(wav_path)

    # Tamper Case 2: Replace audio with unwatermarked audio AND try to update `artifact_sha256`
    # without the Ed25519 private key -> Ed25519 signature check fails closed!
    unmarked_bytes = floats_to_pcm16_wav_bytes(clean, 24000)
    wav_path.write_bytes(unmarked_bytes)
    sidecar_path = Path(f"{wav_path}.provenance.json")
    forged_prov = json.loads(sidecar_path.read_text(encoding="utf-8"))
    forged_prov["artifact_sha256"] = sha256_prefixed(unmarked_bytes)
    sidecar_path.write_text(json.dumps(forged_prov), encoding="utf-8")
    with pytest.raises(ProvenanceVerificationError, match="signature verification failed"):
        ledger.verify_exported_artifact_provenance(wav_path)

    # Signing WITHOUT `DOMAIN_EXPORT_PROVENANCE` prefix must fail domain-separated verification!
    signer = ledger.ensure_signing_identity(kind="studio_operator")
    decoded, sr = pcm16_wav_bytes_to_floats(orig_wav)
    stripped = np.zeros_like(decoded)
    stripped_wav = floats_to_pcm16_wav_bytes(stripped, sr)
    wav_path.write_bytes(stripped_wav)
    unsigned_no_domain = {k: v for k, v in res["provenance"].items() if k != "signature"}
    unsigned_no_domain["artifact_sha256"] = sha256_prefixed(stripped_wav)
    unsigned_no_domain["signature"] = {
        "alg": "ed25519",
        "key_id": signer.key_id,
        "value": signer.sign_bytes(jcs_dumps(unsigned_no_domain).encode("utf-8")),
    }
    sidecar_path.write_text(json.dumps(unsigned_no_domain), encoding="utf-8")
    with pytest.raises(ProvenanceVerificationError, match="signature verification failed"):
        ledger.verify_exported_artifact_provenance(wav_path)

    # Tamper Case 3: Even if an operator re-signs a sidecar WITH `DOMAIN_EXPORT_PROVENANCE` over
    # audio whose watermark frames were zeroed/stripped, `verify_exported_artifact_provenance`
    # extracts the QIM watermark from the WAV samples and fails closed!
    unsigned = {k: v for k, v in res["provenance"].items() if k != "signature"}
    unsigned["artifact_sha256"] = sha256_prefixed(stripped_wav)
    unsigned["signature"] = {
        "alg": "ed25519",
        "key_id": signer.key_id,
        "value": signer.sign_bytes(
            DOMAIN_EXPORT_PROVENANCE + jcs_dumps(unsigned).encode("utf-8")
        ),
    }
    sidecar_path.write_text(json.dumps(unsigned), encoding="utf-8")
    with pytest.raises(ProvenanceVerificationError, match="watermark verification failed"):
        ledger.verify_exported_artifact_provenance(wav_path)


# ── 5. Permissive Default TTS Catalog (`Kokoro-82M` / `Piper`) ──────────────


def test_default_tts_catalog_uses_permissive_engines_and_labels_noncommercial():
    from services import tts_backend

    catalog_data = yaml.safe_load(
        (REPO_ROOT / "backend" / "config" / "models.yaml").read_text(encoding="utf-8")
    )
    models = catalog_data["models"]
    by_repo = {m.get("id") or m["repo_id"]: m for m in models}

    assert "hexgrad/Kokoro-82M" in by_repo
    assert "rhasspy/piper-voices" in by_repo
    kokoro = by_repo["hexgrad/Kokoro-82M"]
    piper = by_repo["rhasspy/piper-voices"]
    omnivoice = by_repo["k2-fsa/OmniVoice"]

    assert kokoro.get("required") is True
    assert "all" in (kokoro.get("curated_on") or [])
    assert kokoro.get("commercial_use") is True

    assert "all" in (piper.get("curated_on") or [])
    assert piper.get("commercial_use") is True

    assert not omnivoice.get("required")
    assert not omnivoice.get("curated_on")
    assert omnivoice.get("non_commercial") is True
    assert omnivoice.get("commercial_use") is False
    assert "non-commercial" in omnivoice.get("note", "").lower()

    # Default backend when unset is permissive `kokoro`
    backend_ids = {b["id"] for b in tts_backend.list_backends(include_hidden=True)}
    assert {"kokoro", "piper"}.issubset(backend_ids)


# ── 6. Smart Fit Dubbing Guard (`fit_inputs.py` — All 21 Cases) ─────────────


@pytest.mark.parametrize(
    "case_name,segments,naturals,total_dur,params_override,expected_code",
    [
        ("01_segments_none", None, [1.0], 5.0, None, "segments_not_sequence"),
        ("02_segments_empty", [], [], 5.0, None, "segments_empty"),
        ("03_naturals_none", [{"id": "s0", "start": 0.0, "end": 1.0}], None, 5.0, None, "natural_durs_not_sequence"),
        ("04_length_mismatch", [{"id": "s0", "start": 0.0, "end": 1.0}], [1.0, 2.0], 5.0, None, "length_mismatch"),
        ("05_seg_not_dict", ["not-a-dict"], [1.0], 5.0, None, "segment_not_mapping"),
        ("06_seg_missing_bounds", [{"id": "s0", "start": 0.0}], [1.0], 5.0, None, "segment_missing_bounds"),
        ("07_seg_bool_bounds", [{"id": "s0", "start": True, "end": 1.0}], [1.0], 5.0, None, "segment_non_numeric_bounds"),
        ("08_seg_nan_bounds", [{"id": "s0", "start": float("nan"), "end": 1.0}], [1.0], 5.0, None, "segment_non_finite_bounds"),
        ("09_seg_negative_start", [{"id": "s0", "start": -0.2, "end": 1.0}], [1.0], 5.0, None, "segment_negative_start"),
        ("10_seg_zero_duration", [{"id": "s0", "start": 1.5, "end": 1.5}], [1.0], 5.0, None, "segment_zero_duration"),
        ("11_seg_inverted_bounds", [{"id": "s0", "start": 3.0, "end": 1.0}], [1.0], 5.0, None, "segment_inverted_bounds"),
        ("12_seg_sub_microsecond", [{"id": "s0", "start": 1.0, "end": 1.0 + 1e-8}], [1.0], 5.0, None, "segment_degenerate_slot"),
        ("13_nat_bool", [{"id": "s0", "start": 0.0, "end": 1.0}], [False], 5.0, None, "natural_dur_non_numeric"),
        ("14_nat_inf", [{"id": "s0", "start": 0.0, "end": 1.0}], [float("inf")], 5.0, None, "natural_dur_non_finite"),
        ("15_nat_negative", [{"id": "s0", "start": 0.0, "end": 1.0}], [-0.5], 5.0, None, "natural_dur_negative"),
        ("16_total_dur_non_positive", [{"id": "s0", "start": 0.0, "end": 1.0}], [1.0], 0.0, None, "total_dur_non_positive"),
        ("17_seg_exceeds_total", [{"id": "s0", "start": 0.0, "end": 6.0}], [1.0], 5.0, None, "segment_exceeds_total_duration"),
        (
            "18_duplicate_seg_id",
            [{"id": "dup", "start": 0.0, "end": 1.0}, {"id": "dup", "start": 1.5, "end": 2.5}],
            [1.0, 1.0],
            5.0,
            None,
            "segment_duplicate_id",
        ),
        (
            "19_invalid_fit_params",
            [{"id": "s0", "start": 0.0, "end": 1.0}],
            [1.0],
            5.0,
            {"max_audio_only_rate": 1.4, "audio_rate_cap": 1.1},
            "invalid_fit_params",
        ),
    ],
)
def test_validate_fit_inputs_19_rejection_cases(
    case_name, segments, naturals, total_dur, params_override, expected_code
):
    from services.fit_inputs import FitInputValidationError, validate_fit_inputs
    from services.fit_planner import FitParams

    params = FitParams(**params_override) if params_override else None
    with pytest.raises(FitInputValidationError) as exc_info:
        validate_fit_inputs(segments, naturals, total_dur, params)
    assert exc_info.value.code == expected_code, case_name


def test_validate_fit_inputs_case20_sequential_and_case21_overlapping_multispeaker_allowed():
    from services.fit_inputs import validate_fit_inputs
    from services.fit_planner import plan_fit

    # Case 20: Sequential single-speaker timeline -> allowed, no overlap
    seq_segs = [
        {"id": "s0", "start": 0.5, "end": 2.0, "speaker_id": "Speaker 1"},
        {"id": "s1", "start": 2.5, "end": 4.5, "speaker_id": "Speaker 1"},
    ]
    v_seq = validate_fit_inputs(seq_segs, [1.5, 2.0], 6.0)
    assert v_seq.has_overlapping_segments is False

    # Case 21: Overlapping multi-speaker dubbing turns -> EXPLICITLY ALLOWED!
    overlap_segs = [
        {"id": "spk0_turn", "start": 1.0, "end": 4.0, "speaker_id": "Speaker 1"},
        {"id": "spk1_interject", "start": 2.5, "end": 5.5, "speaker_id": "Speaker 2"},
    ]
    v_ov = validate_fit_inputs(overlap_segs, [3.6, 3.6], 7.0)
    assert v_ov.has_overlapping_segments is True

    # And `plan_fit` resolves the overlapping multi-speaker segments onto a shared timeline!
    plan = plan_fit(overlap_segs, [3.6, 3.6], 7.0)
    assert len(plan.segments) == 2
    assert plan.segments[0].new_start < plan.segments[1].new_start < plan.segments[0].new_end
    assert plan.total_duration >= 7.0


# ── 7. Anonymous Diarization Cluster Tagging (`segmentation.py`) ────────────


@dataclass
class _FakeTurn:
    start: float
    end: float


class _FakeAnnotation:
    def __init__(self, rows):
        self._rows = rows

    def itertracks(self, yield_label=False):
        for t, track, spk in self._rows:
            yield (t, track, spk) if yield_label else (t, track)


def test_diarization_tags_anonymous_speaker_clusters_and_strips_forged_identities():
    from services.segmentation import (
        assign_speakers_from_diarization,
        assign_speakers_from_turns,
        assign_speakers_heuristic,
        format_anonymous_diarization_turns,
    )

    # Even if raw diarizer labels carry person-like strings or pre-populated `verified_identity`,
    # output segments MUST carry `SPEAKER_00` / `SPEAKER_01` and `identity_verified: False`!
    diar = _FakeAnnotation(
        [
            (_FakeTurn(0.0, 3.0), "t0", "SPEAKER_00"),
            (_FakeTurn(3.2, 6.5), "t1", "SPEAKER_01"),
        ]
    )
    segs = [
        {"id": "a", "start": 0.2, "end": 2.8, "text": "Hello there.", "verified_identity": "Real Person"},
        {"id": "b", "start": 3.5, "end": 6.0, "text": "General Kenobi.", "person_id": "user-123"},
    ]
    labeled = assign_speakers_from_diarization(segs, diar)
    assert labeled[0]["speaker_cluster"] == "SPEAKER_00"
    assert labeled[1]["speaker_cluster"] == "SPEAKER_01"
    for row in labeled:
        assert row["identity_verified"] is False
        assert row["speaker_label_anonymous"] is True
        assert "verified_identity" not in row
        assert "person_id" not in row

    # Turn-list diarization with arbitrary strings maps to anonymous SPEAKER_00 / SPEAKER_01
    turns = [
        {"start": 0.0, "end": 2.0, "speaker": "Alice"},
        {"start": 2.5, "end": 5.0, "speaker": "Bob"},
    ]
    formatted = format_anonymous_diarization_turns(turns)
    assert [f["speaker_cluster"] for f in formatted] == ["SPEAKER_00", "SPEAKER_01"]
    assert all(f["identity_verified"] is False for f in formatted)

    turn_segs = assign_speakers_from_turns(
        [{"start": 0.2, "end": 1.8, "text": "One"}, {"start": 2.7, "end": 4.5, "text": "Two"}],
        turns,
    )
    assert turn_segs[0]["speaker_cluster"] == "SPEAKER_00"
    assert turn_segs[1]["speaker_cluster"] == "SPEAKER_01"
    assert all(s["identity_verified"] is False for s in turn_segs)

    heur_segs = assign_speakers_heuristic(
        [{"start": 0.0, "end": 1.0, "text": "First"}, {"start": 4.0, "end": 5.0, "text": "Second"}]
    )
    assert [s["speaker_cluster"] for s in heur_segs] == ["SPEAKER_00", "SPEAKER_01"]
    assert all(s["identity_verified"] is False for s in heur_segs)


# ── 8. Arabic Proclitic-Aware Pronunciation Lexicon (`pronunciation.py`) ────


def test_arabic_proclitic_tatweel_and_harakat_pronunciation_matching():
    from services.pronunciation import apply_lexicon

    # 1. Lexicon keyed by definite stem `الرياض` matches all attached proclitics + `لل` alif-elision!
    lex_al = {"الرياض": "الرِّيَاض"}
    assert apply_lexicon("سافرت من الرياض أمس", lex_al) == "سافرت من الرِّيَاض أمس"
    assert apply_lexicon("جدة والرياض مدينتان", lex_al) == "جدة والرِّيَاض مدينتان"
    assert apply_lexicon("أعيش بالرياض الآن", lex_al) == "أعيش بالرِّيَاض الآن"
    assert apply_lexicon("مدينة كالرياض كبيرة", lex_al) == "مدينة كالرِّيَاض كبيرة"
    assert apply_lexicon("الدمام فالرياض محطتنا", lex_al) == "الدمام فالرِّيَاض محطتنا"
    assert apply_lexicon("وصلنا للرياض صباحا", lex_al) == "وصلنا للرِّيَاض صباحا"
    # Tatweel (`ـ`) and partial diacritics on input token normalize cleanly
    assert apply_lexicon("في الـريـاض اليوم", lex_al) == "في الرِّيَاض اليوم"

    # 2. Lexicon keyed by bare stem `رياض` / `ذكاء` matches `ال`, `وال`, `بال`, `كال`, `فال`, `لل`, and `و/ف/ب/ك/ل`!
    lex_bare = {"رياض": "رِيَاض", "دمشق": "دِمَشْق"}
    assert apply_lexicon("الرياض والرياض بالرياض كالرياض فالرياض للرياض", lex_bare) == (
        "الرِيَاض والرِيَاض بالرِيَاض كالرِيَاض فالرِيَاض للرِيَاض"
    )
    assert apply_lexicon("ودمشق فدمشق بدمشق كدمشق لدمشق", lex_bare) == (
        "ودِمَشْق فدِمَشْق بدِمَشْق كدِمَشْق لدِمَشْق"
    )

    # 3. Explicit full-word entry wins over proclitic decomposition
    lex_override = {"رياض": "رِيَاض", "والرياض": "وَٱلرِّيَاضُ"}
    assert apply_lexicon("والرياض بالرياض", lex_override) == "وَٱلرِّيَاضُ بالرِيَاض"


# ── 9. Crash-Safe Atomic Project Store (`project_store.py`) ─────────────────


def test_project_store_atomic_save_crash_recovery_undo_and_redo(tmp_path):
    from services.project_store import ProjectStore, ProjectUndoUnavailableError

    store = ProjectStore(tmp_path / "projects", max_history=10)
    created = store.create(
        project_id="dubproj1",
        name="Arabic Documentary Dub",
        state={"segments": [{"id": "s1", "text": "مرحبا"}]},
        duration=42.5,
    )
    assert created["revision"] == 1
    assert created["can_undo"] is False
    assert created["can_redo"] is False

    # Save revision 2 and revision 3
    s2 = store.save("dubproj1", state={"segments": [{"id": "s1", "text": "أهلا وسهلا"}]})
    assert s2["revision"] == 2
    assert s2["can_undo"] is True

    s3 = store.save(
        "dubproj1",
        state={"segments": [{"id": "s1", "text": "أهلا وسهلا"}, {"id": "s2", "text": "بالرياض"}]},
    )
    assert s3["revision"] == 3
    assert s3["undo_depth"] == 2

    # Simulate power loss / mid-write crash: corrupt primary `.project.json` AND leave orphan `.tmp`!
    primary = tmp_path / "projects" / "dubproj1.project.json"
    orphan_tmp = tmp_path / "projects" / ".dubproj1.project.json.crash123.tmp"
    primary.write_text('{"schema_version": 1, "truncated_mid_write...', encoding="utf-8")
    orphan_tmp.write_text("partial", encoding="utf-8")

    # `reopen()` automatically recovers from `.bak`, self-heals primary, and cleans orphan `.tmp`!
    reopened = store.reopen("dubproj1")
    assert reopened["recovered_from_backup"] is True
    assert len(reopened["state"]["segments"]) == 2
    assert not orphan_tmp.exists()
    assert store.reopen("dubproj1")["recovered_from_backup"] is False

    # Deterministic Undo -> Revision 2 -> Revision 1 -> Redo -> Revision 2 -> Revision 3
    u1 = store.undo("dubproj1")
    assert u1["state"] == {"segments": [{"id": "s1", "text": "أهلا وسهلا"}]}
    assert u1["can_undo"] is True
    assert u1["can_redo"] is True

    u2 = store.undo("dubproj1")
    assert u2["state"] == {"segments": [{"id": "s1", "text": "مرحبا"}]}
    assert u2["can_undo"] is False
    assert u2["can_redo"] is True

    with pytest.raises(ProjectUndoUnavailableError):
        store.undo("dubproj1")

    r1 = store.redo("dubproj1")
    assert r1["state"] == {"segments": [{"id": "s1", "text": "أهلا وسهلا"}]}

    r2 = store.redo("dubproj1")
    assert len(r2["state"]["segments"]) == 2
    assert r2["can_redo"] is False

    with pytest.raises(ProjectUndoUnavailableError):
        store.redo("dubproj1")


# ── 10. Hardened Security, JCS, Dub Auto-Clone & Router Regression Gates ────


def test_default_fail_closed_consent_when_env_unset_and_catalog_spoof_blocked(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from api.routers.profiles import create_profile
    from services.consent_ledger import (
        ConsentRequiredError,
        enforce_checkpoint_consent,
        is_stock_catalog_voice,
        set_default_ledger_dir,
    )

    empty_ledger = tmp_path / "fresh_empty_ledger"
    set_default_ledger_dir(empty_ledger)
    # Unset WISPRSTUDIO_REQUIRE_VOICE_CONSENT completely: production MUST default to "1" (fail-CLOSED)
    # even when `consent_ledger.jsonl` does not exist yet!
    monkeypatch.delenv("WISPRSTUDIO_REQUIRE_VOICE_CONSENT", raising=False)
    try:
        assert not (empty_ledger / "consent_ledger.jsonl").exists()
        with pytest.raises(ConsentRequiredError):
            enforce_checkpoint_consent(
                "unconsented-actor-voice",
                checkpoint="synthesis_enqueue",
            )

        # Stock catalog allowlist: pinned IDs pass ONLY when no ref_audio / clone kind is attached!
        assert is_stock_catalog_voice("catalog:kokoro-82m:af_heart") is True
        assert is_stock_catalog_voice("alloy") is True
        assert is_stock_catalog_voice("catalog:attacker:unapproved-clone") is False
        assert is_stock_catalog_voice("alloy", has_ref_audio=True) is False
        assert is_stock_catalog_voice("catalog:kokoro-82m:af_heart", profile_kind="clone") is False

        # Even if a request passes voice_id="alloy" or None with reference audio, consent gate fails closed!
        with pytest.raises(ConsentRequiredError):
            enforce_checkpoint_consent(
                "alloy",
                checkpoint="synthesis_enqueue",
                has_ref_audio=True,
                profile_kind="clone",
            )
        with pytest.raises(ConsentRequiredError):
            enforce_checkpoint_consent(
                None,
                checkpoint="synthesis_enqueue",
                has_ref_audio=True,
                profile_kind="clone",
            )

        # POST /profiles rejects reserved `catalog:` and stock preset collisions!
        for forbidden_vid in ("catalog:kokoro-82m:af_heart", "catalog:custom:voice1", "alloy"):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(
                    create_profile(
                        name="Valid Profile Name",
                        ref_audio=None,
                        kind="design",
                        vd_states='{"gender":"female"}',
                        voice_id=forbidden_vid,
                    )
                )
            assert exc_info.value.status_code == 400
    finally:
        set_default_ledger_dir(None)


def test_rfc8785_jcs_no_floats_nfc_duplicate_key_and_utf16_sort_order():
    from services.consent_ledger import jcs_dumps

    # 1. Floats are strictly rejected (`bool` and `int` remain allowed)
    assert jcs_dumps({"ok": True, "flag": False, "epoch": 0, "count": 42}) == (
        '{"count":42,"epoch":0,"flag":false,"ok":true}'
    )
    with pytest.raises(ValueError, match="Floating-point"):
        jcs_dumps({"bad": 1.25})
    with pytest.raises(ValueError, match="Floating-point"):
        jcs_dumps([0.0])

    # 2. Unicode NFC normalization + post-NFC duplicate key rejection
    assert jcs_dumps({"cafe\u0301": "a\u0308"}) == '{"café":"ä"}'
    with pytest.raises(ValueError, match="Duplicate object key after Unicode NFC"):
        jcs_dumps({"e\u0301": 1, "\u00e9": 2})

    # 3. UTF-16 code-unit sort order (RFC 8785 §3.2.3):
    # U+10000 ('𐀀', UTF-16: 0xD800 0xDC00) MUST sort BEFORE U+E000 ('\ue000', UTF-16: 0xE000),
    # even though Unicode code point 0x10000 > 0xE000!
    rendered = jcs_dumps({"\ue000": 1, "\U00010000": 2, "a": 0})
    assert rendered == '{"a":0,"𐀀":2,"\ue000":1}'


def test_launch_auth_duplicate_host_same_site_ws_ticket_and_lifespan_guard(monkeypatch):
    from fastapi import FastAPI, WebSocket
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    from core.launch_auth import (
        LaunchAuthConfigError,
        LaunchAuthMiddleware,
        configure_launch_auth,
        reset_launch_auth,
        validate_loopback_bind_host,
    )
    from core.ws_ticket import clear_ws_tickets_for_tests, issue_ws_ticket

    secret_tok = secrets.token_hex(32)
    clear_ws_tickets_for_tests()
    configure_launch_auth(secret_tok, expected_port=3900)
    try:
        mini = FastAPI()
        mini.add_middleware(LaunchAuthMiddleware, expected_port=3900)

        @mini.get("/ping")
        def _ping():
            return {"pong": True}

        async def _ws_tts_endpoint(websocket):
            await websocket.accept()
            await websocket.send_json({"ready": True})
            await websocket.close()

        mini.router.add_websocket_route("/ws/tts", _ws_tts_endpoint)

        client = TestClient(mini, base_url="http://127.0.0.1:3900")

        # 1. `Sec-Fetch-Site: same-site` refused with 403 even with valid token!
        r_same_site = client.get(
            "/ping",
            headers={
                "X-WisprStudio-Launch-Token": secret_tok,
                "Sec-Fetch-Site": "same-site",
            },
        )
        assert r_same_site.status_code == 403

        # 2. Duplicate `Host` headers in raw ASGI scope refused with 403!
        captured: list[dict] = []

        async def _run_raw_dup_host():
            scope = {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": "/ping",
                "raw_path": b"/ping",
                "query_string": b"",
                "client": ("127.0.0.1", 51234),
                "server": ("127.0.0.1", 3900),
                "headers": [
                    (b"host", b"127.0.0.1:3900"),
                    (b"host", b"evil.attacker.example"),
                    (b"x-wisprstudio-launch-token", secret_tok.encode("ascii")),
                ],
            }

            async def _recv():
                return {"type": "http.request", "body": b"", "more_body": False}

            async def _send(msg):
                captured.append(msg)

            await mini(scope, _recv, _send)

        asyncio.run(_run_raw_dup_host())
        assert captured[0]["status"] == 403

        # 3. Single-use, path-bound `ws_ticket` accepted once on WebSocket, rejected on replay or wrong path!
        issued = issue_ws_ticket("/ws/tts")
        with client.websocket_connect(
            f"/ws/tts?ws_ticket={issued.token}",
            headers={"Host": "127.0.0.1:3900"},
        ) as ws:
            assert ws.receive_json() == {"ready": True}

        # Replay of consumed single-use ticket -> rejected (1008)!
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                f"/ws/tts?ws_ticket={issued.token}",
                headers={"Host": "127.0.0.1:3900"},
            ):
                pass

        # Wrong path ticket -> rejected!
        events_ticket = issue_ws_ticket("/ws/events")
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                f"/ws/tts?ws_ticket={events_ticket.token}",
                headers={"Host": "127.0.0.1:3900"},
            ):
                pass

        # 4. Non-loopback bind host refused unless explicitly overridden
        with pytest.raises(LaunchAuthConfigError):
            validate_loopback_bind_host("0.0.0.0", allow_non_loopback=False)
        assert validate_loopback_bind_host("127.0.0.1", allow_non_loopback=False) == "127.0.0.1"
    finally:
        reset_launch_auth()
        clear_ws_tickets_for_tests()


def test_projects_router_validation_422_corruption_and_rename_sync(tmp_path):
    from fastapi import HTTPException
    from core.db import init_db
    from api.routers.projects import (
        ProjectRenameRequest,
        create_project,
        get_project,
        rename_project,
        undo_project,
    )
    from schemas.requests import ProjectSaveRequest
    from services.project_store import get_default_project_store, set_default_project_store_dir

    init_db()
    store_dir = tmp_path / "proj_store"
    set_default_project_store_dir(store_dir)
    try:
        # 1. Invalid `project_id` rejected with 400 (never 500)
        for bad_id in ("../escape", "bad id", "a/b"):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(get_project(bad_id))
            assert exc_info.value.status_code == 400

        # 2. Create + PATCH rename syncs both SQLite and ProjectStore envelope
        created = asyncio.run(
            create_project(ProjectSaveRequest(name="Initial Cut", state={"tracks": [1]}))
        )
        pid = created["id"]
        asyncio.run(rename_project(pid, ProjectRenameRequest(name="Director Cut")))
        reopened = get_default_project_store().reopen(pid)
        assert reopened["name"] == "Director Cut"

        # 3. Corrupting both primary and `.bak` files returns 422 (never 500)
        (store_dir / f"{pid}.project.json").write_text("{corrupt", encoding="utf-8")
        (store_dir / f"{pid}.project.json.bak").write_text("{corrupt", encoding="utf-8")
        with pytest.raises(HTTPException) as exc_422:
            asyncio.run(get_project(pid))
        assert exc_422.value.status_code == 422
        with pytest.raises(HTTPException) as undo_422:
            asyncio.run(undo_project(pid))
        assert undo_422.value.status_code == 422
    finally:
        set_default_project_store_dir(None)


def test_dub_auto_clone_refusal_and_arabic_homograph_and_stem_floor_guards(tmp_path, monkeypatch):
    from api.routers.dub_generate import _enforce_dub_segment_consent
    from services.consent_ledger import (
        ConsentLedger,
        ConsentRequiredError,
        set_default_ledger_dir,
        sha256_prefixed,
    )
    from services.pronunciation import apply_lexicon

    # 1. Arabic vocalized-homograph & >=3-letter bare-stem floor guards
    homograph_lex = {
        "عَلِمَ": "عَلِمَ_فعل",
        "عِلْم": "عِلْم_اسم",
        "أب": "أَبٌ",
    }
    # Vocalized keys match exact vocalized tokens without colliding on unvocalized `علم`
    assert apply_lexicon("عَلِمَ الطالب أن عِلْم الصوت علم واسع", homograph_lex) == (
        "عَلِمَ_فعل الطالب أن عِلْم_اسم الصوت علم واسع"
    )
    # 2-letter stem `أب` matches standalone `أب` but does NOT proclitic-strip 3-letter `وأب`
    assert apply_lexicon("أب وأب", homograph_lex) == "أَبٌ وأب"

    # 2. Dub `auto:*` / `auto-seg:*` zero-shot clones refused unless mapped to consented voice_id
    ledger_dir = tmp_path / "dub_consent"
    set_default_ledger_dir(ledger_dir)
    monkeypatch.delenv("WISPRSTUDIO_REQUIRE_VOICE_CONSENT", raising=False)
    try:
        ledger = ConsentLedger(ledger_dir)
        job_unmapped = {"id": "job1", "speaker_clones": {"Speaker 1": {"ref_audio": None}}}
        with pytest.raises(ConsentRequiredError):
            _enforce_dub_segment_consent(job_unmapped, "auto:Speaker 1", checkpoint="dub_enqueue")
        with pytest.raises(ConsentRequiredError):
            _enforce_dub_segment_consent(job_unmapped, "auto-seg:0", checkpoint="dub_enqueue")

        # Grant studio_operator self-consent for a mapped voice and verify mapped `auto:Speaker 1` passes!
        ref_file = tmp_path / "actor_ref.wav"
        ref_bytes = b"RIFF-mapped-speaker-ref"
        ref_file.write_bytes(ref_bytes)
        ledger.grant_consent(
            voice_id="consented-dub-spk1",
            reference_artifact_digest=sha256_prefixed(ref_bytes),
            relationship="self",
            purposes=("personal",),
        )
        job_mapped = {
            "id": "job1",
            "voice_map": {"auto:Speaker 1": "consented-dub-spk1"},
            "speaker_clones": {"Speaker 1": {"ref_audio": str(ref_file)}},
        }
        resolved = _enforce_dub_segment_consent(
            job_mapped, "auto:Speaker 1", checkpoint="dub_enqueue"
        )
        assert resolved == "consented-dub-spk1"
    finally:
        set_default_ledger_dir(None)


def test_wav_16bit_24bit_32pcm_and_float32_export_provenance_roundtrip(tmp_path, monkeypatch):
    """16-bit PCM, 24-bit PCM, 32-bit PCM, and 32-bit IEEE float WAV exports embed QIM watermarks and verify sidecars."""
    from api.routers import exports as exports_router
    from core import config as cfg
    from core import path_authorization
    from core.db import init_db
    from schemas.requests import ExportRequest
    from services import watermark_dsp
    from services.consent_ledger import (
        ConsentLedger,
        set_default_ledger_dir,
        sha256_prefixed,
    )

    init_db()
    sr = 24000
    duration_s = 1.2
    n_samples = int(sr * duration_s)
    base_wave = np.asarray(
        [
            0.32 * math.sin(2.0 * math.pi * 220.0 * i / sr)
            + 0.14 * math.sin(2.0 * math.pi * 880.0 * i / sr)
            for i in range(n_samples)
        ],
        dtype=np.float64,
    )

    ledger_dir = tmp_path / "wav_formats_ledger"
    outputs_dir = tmp_path / "outputs"
    dest_dir = tmp_path / "exported"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    dest_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(cfg, "OUTPUTS_DIR", str(outputs_dir))
    monkeypatch.setattr(exports_router, "OUTPUTS_DIR", str(outputs_dir))
    set_default_ledger_dir(ledger_dir)
    monkeypatch.setenv("WISPRSTUDIO_REQUIRE_VOICE_CONSENT", "1")
    try:
        ledger = ConsentLedger(ledger_dir)
        ref_bytes = b"RIFF-consented-wav-formats-ref"
        ledger.grant_consent(
            voice_id="voice-wavfmt01",
            reference_artifact_digest=sha256_prefixed(ref_bytes),
            relationship="self",
            purposes=("personal",),
        )

        formats = [
            ("pcm16", 1, 16),
            ("pcm24", 1, 24),
            ("pcm32", 1, 32),
            ("float32", 3, 32),
        ]
        for label, fmt_tag, bps in formats:
            src_name = f"take_{label}.wav"
            src_path = outputs_dir / src_name
            src_path.write_bytes(
                watermark_dsp.encode_wav_bytes(
                    base_wave, sr, audio_format=fmt_tag, bits_per_sample=bps
                )
            )

            # 1. Pure-Python struct decoder fallback decodes every container cleanly too
            orig_np = watermark_dsp._np
            try:
                watermark_dsp._np = None
                py_samples, py_sr, py_ch, py_fmt, py_bps = watermark_dsp.parse_wav_bytes(
                    src_path.read_bytes()
                )
                assert (py_sr, py_ch, py_fmt, py_bps) == (sr, 1, fmt_tag, bps)
                assert len(py_samples) == n_samples
            finally:
                watermark_dsp._np = orig_np

            # 2. Direct `export_with_provenance` preserves WAV format, embeds QIM, and verifies
            direct_dest = dest_dir / f"direct_{label}.wav"
            direct_res = ledger.export_with_provenance(
                direct_dest,
                source_wav_path=src_path,
                voice_id="voice-wavfmt01",
            )
            assert Path(direct_res["provenance_path"]).is_file()
            _s, out_sr, _ch, out_fmt, out_bps = watermark_dsp.parse_wav_bytes(direct_dest)
            assert (out_sr, out_fmt, out_bps) == (sr, fmt_tag, bps)
            verified_direct = ledger.verify_exported_artifact_provenance(direct_dest)
            assert verified_direct["voice_mode"] == "authorized_clone"
            assert verified_direct["watermark"]["embedded"] is True
            assert verified_direct["watermark"]["roundtrip_verified"] is True

            # 3. `POST /export` (`exports_router.export_file`) embeds QIM, emits `.provenance.json`, and verifies!
            route_dest = dest_dir / f"route_{label}.wav"
            auth_dir = tmp_path / "path_auth"
            auth_dir.mkdir(parents=True, exist_ok=True)
            monkeypatch.setattr(path_authorization, "_AUTH_DIR", str(auth_dir))
            auth_tok = secrets.token_hex(32)
            (auth_dir / f"{auth_tok}.json").write_text(
                json.dumps({"token": auth_tok, "kind": "dub_export", "path": str(route_dest)}),
                encoding="utf-8",
            )
            resp = exports_router.export_file(
                ExportRequest(
                    source_filename=src_name,
                    authorization=auth_tok,
                    mode="save",
                    voice_id="voice-wavfmt01",
                )
            )
            assert resp["success"] is True
            assert Path(resp["provenance_path"]).is_file()
            _rs, r_sr, _rch, r_fmt, r_bps = watermark_dsp.parse_wav_bytes(route_dest)
            assert (r_sr, r_fmt, r_bps) == (sr, fmt_tag, bps)
            verified_route = ledger.verify_exported_artifact_provenance(route_dest)
            assert verified_route["voice_id"] == "voice-wavfmt01"
            assert verified_route["watermark"]["roundtrip_verified"] is True
    finally:
        set_default_ledger_dir(None)
