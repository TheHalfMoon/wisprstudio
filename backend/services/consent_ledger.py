"""Cryptographic Voice Consent Ledger, 4-Point Gate & Atomic Provenance Sidecars.

Implements WisprStudio's production voice-cloning governance (`AGPL-3.0-only`):
- Append-only SHA-256 hash-chained & Ed25519-signed consent ledger matching
  `backend/contracts/schemas/consent_record.schema.json` (`consent_granted` /
  `consent_revoked`, strictly monotonic `consent_epoch`, RFC 8785 JCS
  `bound_fields_digest`, `reference_artifact_digest`, `speaker_match`).
- 4-point `verify_voice_consent_gate` across:
  (1) profile enrollment / speaker clone creation,
  (2) synthesis / dubbing / voice-conversion / batch / OpenAI-compat / MCP enqueue,
  (3) pre-chunk long-form render loop (mid-render halt on revocation),
  (4) final export commit.
- Instant `revoke_consent(consent_id)`: appends `consent_revoked` at `epoch + 1`,
  purges cached speaker embeddings (in-memory + disk), cancels queued/active
  renders for `voice_id`, and refuses all subsequent synthesis.
- Atomic `export_with_provenance`: embeds `wispral-qim-v1` watermark, performs
  fail-closed round-trip watermark extraction verification, and atomically writes
  Ed25519-signed `<artifact>.provenance.json` validated against
  `backend/contracts/schemas/export_provenance.schema.json`.

Imports cleanly with zero PyTorch dependency.
"""

from __future__ import annotations

import base64
import copy
import dataclasses
import hashlib
import io
import json
import math
import os
import secrets
import stat
import struct
import tempfile
import threading
import unicodedata
import uuid
import wave
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from jsonschema import Draft202012Validator

from services.watermark_dsp import (
    WATERMARK_SCHEME_ID,
    embed_qim_watermark,
    extract_and_verify_watermark,
    pcm16_wav_bytes_to_floats,
    floats_to_pcm16_wav_bytes,
)

GENESIS_PREV_HASH = "sha256:" + ("0" * 64)
ALLOWED_PROVENANCE_SAMPLE_RATES = (8000, 16000, 22050, 24000, 32000, 44100, 48000)
REQUIRE_CONSENT_ENV = "WISPRSTUDIO_REQUIRE_VOICE_CONSENT"
DOMAIN_EXPORT_PROVENANCE = b"wispral:export_provenance:v1:"

STOCK_VOICE_ALIASES: frozenset[str] = frozenset(
    {
        "",
        "default",
        "auto",
        "alloy",
        "ash",
        "ballad",
        "coral",
        "echo",
        "fable",
        "onyx",
        "nova",
        "sage",
        "shimmer",
        "verse",
        "narrator",
        "excited_child",
        "anxious_whisper",
        "surprised_woman",
        "elderly_story",
        "sichuan",
        "af_heart",
        "af_bella",
        "af_sarah",
        "am_adam",
        "am_michael",
        "bf_emma",
        "bm_george",
        "en_us-lessac-medium",
        "en_gb-alba-medium",
        "bella",
        "jasper",
        "luna",
        "bruno",
        "rosie",
        "hugo",
        "kiki",
        "leo",
    }
)

KNOWN_STOCK_CATALOG_IDS: frozenset[str] = frozenset(
    {
        "catalog:kokoro-82m:af_heart",
        "catalog:kokoro-82m:af_bella",
        "catalog:kokoro-82m:af_sarah",
        "catalog:kokoro-82m:am_adam",
        "catalog:kokoro-82m:am_michael",
        "catalog:kokoro-82m:bf_emma",
        "catalog:kokoro-82m:bm_george",
        "catalog:piper:en_US-lessac-medium",
        "catalog:piper:en_GB-alba-medium",
        "catalog:piper:en_us-lessac-medium",
        "catalog:piper:en_gb-alba-medium",
        "catalog:kittentts:bella",
        "catalog:kittentts:jasper",
        "catalog:kittentts:luna",
        "catalog:kittentts:bruno",
        "catalog:kittentts:rosie",
        "catalog:kittentts:hugo",
        "catalog:kittentts:kiki",
        "catalog:kittentts:leo",
        "catalog:preset:default",
        "catalog:preset:alloy",
        "catalog:preset:ash",
        "catalog:preset:ballad",
        "catalog:preset:coral",
        "catalog:preset:echo",
        "catalog:preset:fable",
        "catalog:preset:onyx",
        "catalog:preset:nova",
        "catalog:preset:sage",
        "catalog:preset:shimmer",
        "catalog:preset:verse",
        "catalog:preset:narrator",
    }
)
_KNOWN_STOCK_CATALOG_LOWER: frozenset[str] = frozenset(
    cid.lower() for cid in KNOWN_STOCK_CATALOG_IDS
)

_BOUND_TOP_FIELDS = (
    "consent_id",
    "subject_ref",
    "voice_id",
    "relationship",
    "principal_scope_ref",
    "purposes",
    "products",
    "allowed_engines",
    "valid_from",
    "valid_until",
    "evidence_digest",
    "consent_epoch",
    "watermark_required",
    "reference_artifact_digest",
    "speaker_match",
)

_SCHEMAS_DIR = Path(__file__).resolve().parents[1] / "contracts" / "schemas"


# ── Typed Errors ────────────────────────────────────────────────────────────


class ConsentGateError(PermissionError):
    """Base fail-closed exception raised when a voice consent gate refuses work."""

    code: str = "consent_denied"
    status_code: int = 403

    def __init__(self, message: str, *, voice_id: str = "", checkpoint: str = "") -> None:
        super().__init__(message)
        self.voice_id = voice_id
        self.checkpoint = checkpoint

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": str(self),
            "voice_id": self.voice_id,
            "checkpoint": self.checkpoint,
        }


class ConsentRequiredError(ConsentGateError):
    code = "consent_required"


class ConsentRevokedError(ConsentGateError):
    code = "consent_revoked"


class ConsentExpiredError(ConsentGateError):
    code = "consent_expired"


class ConsentEpochMismatchError(ConsentGateError):
    code = "consent_epoch_mismatch"


class ReferenceDigestMismatchError(ConsentGateError):
    code = "reference_digest_mismatch"


class ConsentLedgerTamperError(ConsentGateError):
    code = "consent_ledger_tampered"


class ProvenanceVerificationError(RuntimeError):
    """Raised when audio watermark round-trip or `.provenance.json` verification fails."""


# ── Canonical JSON (RFC 8785 JCS) & Digests ─────────────────────────────────


def _utf16_sort_key(text: str) -> tuple[int, ...]:
    encoded = text.encode("utf-16-le")
    return struct.unpack(f"<{len(encoded) // 2}H", encoded)


def _normalize_jcs(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, float):
        raise ValueError(
            "Floating-point numbers are forbidden in JCS-canonicalized governance artifacts"
        )
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, Mapping):
        normalized_obj: dict[str, Any] = {}
        for raw_key, raw_val in value.items():
            if not isinstance(raw_key, str):
                raise TypeError(f"JCS object keys must be strings, got {type(raw_key)!r}")
            nfc_key = unicodedata.normalize("NFC", raw_key)
            if nfc_key in normalized_obj:
                raise ValueError(
                    f"Duplicate object key after Unicode NFC normalization: {nfc_key!r}"
                )
            normalized_obj[nfc_key] = _normalize_jcs(raw_val)
        return normalized_obj
    if isinstance(value, (list, tuple)):
        return [_normalize_jcs(item) for item in value]
    raise TypeError(f"Unsupported type for JCS canonicalization: {type(value)!r}")


def _serialize_jcs_normalized(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ",".join(_serialize_jcs_normalized(item) for item in value) + "]"
    if isinstance(value, dict):
        sorted_items = sorted(value.items(), key=lambda kv: _utf16_sort_key(kv[0]))
        return (
            "{"
            + ",".join(
                f"{json.dumps(k, ensure_ascii=False)}:{_serialize_jcs_normalized(v)}"
                for k, v in sorted_items
            )
            + "}"
        )
    raise TypeError(f"Unexpected normalized JCS value: {type(value)!r}")


def jcs_dumps(value: Any) -> str:
    """Serialize `value` to strict RFC 8785 JCS canonical JSON (UTF-16 key sort, NFC, no floats)."""
    normalized = _normalize_jcs(value)
    return _serialize_jcs_normalized(normalized)


def jcs_sha256(value: Any) -> str:
    """Compute `sha256:<64hex>` over the RFC 8785 JCS canonical bytes of `value`."""
    return "sha256:" + hashlib.sha256(jcs_dumps(value).encode("utf-8")).hexdigest()


def sha256_prefixed(data: bytes) -> str:
    """Return `sha256:<64hex>` digest of raw bytes."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_file_prefixed(path: str | os.PathLike[str]) -> str:
    """Stream-hash a file on disk into `sha256:<64hex>`."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(65536):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def utc_now_rfc3339(dt: datetime | None = None) -> str:
    """Format a UTC timestamp matching schema `YYYY-MM-DDTHH:MM:SSZ`."""
    now = (dt or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_rfc3339(ts: str) -> datetime:
    if not isinstance(ts, str) or not ts.endswith("Z"):
        raise ValueError(f"Timestamp must be UTC Z-suffixed RFC 3339: {ts!r}")
    body = ts[:-1]
    if "." in body:
        head, frac = body.split(".", 1)
        frac = (frac[:6]).ljust(6, "0")
        body = f"{head}.{frac}"
    return datetime.fromisoformat(body).replace(tzinfo=timezone.utc)


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(encoded: str) -> bytes:
    pad = "=" * ((4 - (len(encoded) % 4)) % 4)
    return base64.urlsafe_b64decode((encoded + pad).encode("ascii"))


@lru_cache(maxsize=4)
def _load_validator(schema_filename: str) -> Draft202012Validator:
    schema_path = _SCHEMAS_DIR / schema_filename
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def compute_bound_fields_digest(record: Mapping[str, Any]) -> str:
    """Compute `attestation.bound_fields_digest` per `consent_record.schema.json`."""
    fields: dict[str, Any] = {k: record.get(k) for k in _BOUND_TOP_FIELDS}
    attestation = record.get("attestation")
    if not isinstance(attestation, Mapping):
        raise ValueError("Consent record missing attestation object")
    fields["attestation"] = {
        k: v
        for k, v in attestation.items()
        if k not in ("bound_fields_digest", "signature")
    }
    return jcs_sha256(fields)


def is_stock_catalog_voice(
    voice_id: str | None,
    *,
    has_ref_audio: bool = False,
    profile_kind: str | None = None,
) -> bool:
    """Return True iff `voice_id` is a pinned built-in stock voice with no clone reference audio."""
    if has_ref_audio or (profile_kind or "").strip().lower() == "clone":
        return False
    if voice_id is None:
        return True
    cleaned = str(voice_id).strip()
    if cleaned.lower().startswith("catalog:"):
        return cleaned.lower() in _KNOWN_STOCK_CATALOG_LOWER
    return cleaned.lower() in STOCK_VOICE_ALIASES


def is_reserved_stock_voice_id(candidate: str | None) -> bool:
    """Return True if `candidate` uses the reserved `catalog:` namespace or collides with stock preset IDs."""
    if candidate is None:
        return False
    cleaned = str(candidate).strip()
    if not cleaned:
        return False
    low = cleaned.lower()
    return low.startswith("catalog:") or low in STOCK_VOICE_ALIASES or low in _KNOWN_STOCK_CATALOG_LOWER


# ── Ed25519 Signing Identities & Trusted Key Registry ───────────────────────


@dataclass(frozen=True)
class SigningIdentity:
    """An Ed25519 signing keypair bound to a `studio_operator` or `consent_service` key ID."""

    key_id: str
    kind: Literal["studio_operator", "consent_service"]
    private_key_b64: str
    public_key_b64: str

    @property
    def private_key(self) -> Ed25519PrivateKey:
        return Ed25519PrivateKey.from_private_bytes(_b64url_decode(self.private_key_b64))

    @property
    def public_key(self) -> Ed25519PublicKey:
        return Ed25519PublicKey.from_public_bytes(_b64url_decode(self.public_key_b64))

    def sign_bytes(self, message: bytes) -> str:
        sig = self.private_key.sign(message)
        return _b64url_encode(sig)


def generate_signing_identity(
    kind: Literal["studio_operator", "consent_service"] = "studio_operator",
    key_suffix: str | None = None,
) -> SigningIdentity:
    """Create a fresh Ed25519 keypair with schema-valid `op-key:` or `consent-svc:` prefix."""
    prefix = "op-key" if kind == "studio_operator" else "consent-svc"
    suffix = key_suffix or secrets.token_hex(6)
    key_id = f"{prefix}:{suffix}"
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    priv_raw = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub_raw = pub.public_bytes(Encoding.Raw, PublicFormat.Raw)
    return SigningIdentity(
        key_id=key_id,
        kind=kind,
        private_key_b64=_b64url_encode(priv_raw),
        public_key_b64=_b64url_encode(pub_raw),
    )


def _verify_ed25519_b64url(public_key_b64: str, message: bytes, signature_b64: str) -> bool:
    try:
        pub = Ed25519PublicKey.from_public_bytes(_b64url_decode(public_key_b64))
        sig = _b64url_decode(signature_b64)
        pub.verify(sig, message)
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        except OSError:
            pass
        raise


# ── Speaker Embedding Cache & Active Render Cancellation Registry ───────────


@dataclass
class ActiveRenderHandle:
    render_id: str
    voice_id: str
    cancelled: threading.Event
    cancel_callback: Callable[[], None] | None = None


_runtime_lock = threading.RLock()
_speaker_embedding_cache: dict[str, dict[str, Any]] = {}
_speaker_embedding_paths: dict[str, set[str]] = {}
_active_renders: dict[str, ActiveRenderHandle] = {}
_cancelled_voices: set[str] = set()


def cache_speaker_embedding(
    voice_id: str,
    embedding: Any,
    *,
    cache_path: str | os.PathLike[str] | None = None,
) -> None:
    """Store a speaker embedding in the revocable cache (and optional disk file)."""
    vid = str(voice_id).strip()
    if not vid:
        return
    with _runtime_lock:
        _speaker_embedding_cache[vid] = {
            "embedding": embedding,
            "cached_at": utc_now_rfc3339(),
        }
        if cache_path is not None:
            p_str = os.fspath(cache_path)
            _speaker_embedding_paths.setdefault(vid, set()).add(p_str)


def get_cached_speaker_embedding(voice_id: str) -> Any | None:
    """Retrieve a cached speaker embedding if present (None after revocation purge)."""
    with _runtime_lock:
        entry = _speaker_embedding_cache.get(str(voice_id).strip())
        return entry["embedding"] if entry is not None else None


def purge_speaker_embeddings(
    voice_id: str,
    *,
    extra_dirs: Sequence[str | os.PathLike[str]] = (),
) -> int:
    """Purge all in-memory and on-disk cached speaker embeddings for `voice_id`."""
    vid = str(voice_id).strip()
    if not vid:
        return 0
    removed = 0
    with _runtime_lock:
        if vid in _speaker_embedding_cache:
            del _speaker_embedding_cache[vid]
            removed += 1
        tracked_paths = list(_speaker_embedding_paths.pop(vid, ()))

    for p in tracked_paths:
        try:
            if os.path.isfile(p):
                os.remove(p)
                removed += 1
        except OSError:
            pass

    search_dirs: list[Path] = [Path(d) for d in extra_dirs if d]
    try:
        from core import config as _cfg

        for attr in ("DATA_DIR", "VOICES_DIR"):
            val = getattr(_cfg, attr, None)
            if isinstance(val, str) and val:
                search_dirs.append(Path(val))
                search_dirs.append(Path(val) / "speaker_embeddings")
    except Exception:
        pass

    safe_prefix = "".join(c if c.isalnum() or c in "._-" else "_" for c in vid)
    for directory in search_dirs:
        if not directory.is_dir():
            continue
        for pattern in (
            f"{safe_prefix}.emb*",
            f"{safe_prefix}_embedding*",
            f"{safe_prefix}.speaker_embedding*",
            f"*{safe_prefix}*embedding*.npy",
            f"*{safe_prefix}*embedding*.npz",
            f"*{safe_prefix}*embedding*.pt",
            f"*{safe_prefix}*.prompt.pt",
            f"*{safe_prefix}*.spk.npy",
        ):
            for candidate in directory.glob(pattern):
                if candidate.is_file():
                    try:
                        candidate.unlink()
                        removed += 1
                    except OSError:
                        pass
    return removed


def register_active_render(
    voice_id: str,
    *,
    render_id: str | None = None,
    cancel_callback: Callable[[], None] | None = None,
) -> ActiveRenderHandle:
    """Register an in-flight/queued render for `voice_id` so `revoke_consent` cancels it."""
    rid = render_id or f"rnd-{uuid.uuid4().hex[:12]}"
    vid = str(voice_id).strip()
    handle = ActiveRenderHandle(
        render_id=rid,
        voice_id=vid,
        cancelled=threading.Event(),
        cancel_callback=cancel_callback,
    )
    with _runtime_lock:
        if vid in _cancelled_voices:
            handle.cancelled.set()
        _active_renders[rid] = handle
    return handle


def unregister_active_render(render_id: ActiveRenderHandle | str | None) -> None:
    """Release an active render registration upon completion."""
    if render_id is None:
        return
    rid = render_id.render_id if isinstance(render_id, ActiveRenderHandle) else str(render_id)
    with _runtime_lock:
        _active_renders.pop(rid, None)


def cancel_renders_for_voice(voice_id: str) -> list[str]:
    """Cancel all active and queued renders associated with `voice_id`."""
    vid = str(voice_id).strip()
    cancelled_ids: list[str] = []
    callbacks: list[Callable[[], None]] = []
    with _runtime_lock:
        _cancelled_voices.add(vid)
        for rid, handle in list(_active_renders.items()):
            if handle.voice_id == vid:
                handle.cancelled.set()
                cancelled_ids.append(rid)
                if handle.cancel_callback is not None:
                    callbacks.append(handle.cancel_callback)

    for cb in callbacks:
        try:
            cb()
        except Exception:
            pass

    # Also mark any queued/running batch dubbing jobs referencing `voice_id` cancelled.
    try:
        import sys as _sys

        batch_mod = _sys.modules.get("api.routers.batch")
        if batch_mod is not None:
            jobs = getattr(batch_mod, "_jobs", {})
            for job_id, job in list(jobs.items()):
                if job.get("voice_id") == vid and job.get("status") in ("queued", "running"):
                    job["status"] = "cancelled"
                    job["error"] = f"Voice consent revoked for {vid}"
                    cancelled_ids.append(f"batch:{job_id}")
    except Exception:
        pass

    return cancelled_ids


def is_voice_render_cancelled(voice_id: str) -> bool:
    with _runtime_lock:
        return str(voice_id).strip() in _cancelled_voices


def reset_runtime_consent_caches() -> None:
    """Clear in-memory embedding & render registries (for unit tests)."""
    with _runtime_lock:
        _speaker_embedding_cache.clear()
        _speaker_embedding_paths.clear()
        _active_renders.clear()
        _cancelled_voices.clear()


# ── Consent Gate Verdict & Ledger Implementation ────────────────────────────


@dataclass(frozen=True)
class ConsentGateVerdict:
    allowed: bool
    voice_mode: Literal["stock_catalog", "authorized_clone"]
    voice_id: str
    consent_id: str | None = None
    consent_epoch: int | None = None
    watermark_required: bool = True
    checkpoint: str = "enqueue"


class ConsentLedger:
    """Append-only SHA-256 hash-chained & Ed25519-signed voice consent ledger."""

    def __init__(self, ledger_dir: str | os.PathLike[str]) -> None:
        self.ledger_dir = Path(ledger_dir)
        self.ledger_path = self.ledger_dir / "consent_ledger.jsonl"
        self.keys_path = self.ledger_dir / "consent_trusted_keys.json"
        self.operator_key_path = self.ledger_dir / "operator_signing_key.json"
        self._lock = threading.RLock()

    # ── Key Management ──────────────────────────────────────────────────────

    def _load_key_store(self) -> dict[str, Any]:
        if not self.keys_path.is_file():
            return {"trusted_keys": {}}
        data = json.loads(self.keys_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("trusted_keys"), dict):
            raise ConsentLedgerTamperError("Trusted key store is malformed")
        for key_id, entry in data["trusted_keys"].items():
            if not isinstance(entry, dict) or "private_key_b64" in entry:
                raise ConsentLedgerTamperError(
                    f"Trusted key registry must hold public keys only (violation at {key_id!r})"
                )
        return {"trusted_keys": data["trusted_keys"]}

    def _save_key_store(self, store: dict[str, Any]) -> None:
        clean_store = {"trusted_keys": store.get("trusted_keys", {})}
        _atomic_write_bytes(
            self.keys_path,
            (json.dumps(clean_store, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )

    def register_trusted_key(
        self,
        key_id: str,
        kind: Literal["studio_operator", "consent_service"],
        public_key_b64: str,
    ) -> None:
        if kind == "studio_operator" and not str(key_id).startswith("op-key:"):
            raise ConsentGateError(f"studio_operator key_id must start with 'op-key:': {key_id!r}")
        if kind == "consent_service" and not str(key_id).startswith("consent-svc:"):
            raise ConsentGateError(
                f"consent_service key_id must start with 'consent-svc:': {key_id!r}"
            )
        # Validate Ed25519 public key encoding up front.
        Ed25519PublicKey.from_public_bytes(_b64url_decode(public_key_b64))
        with self._lock:
            store = self._load_key_store()
            store["trusted_keys"][key_id] = {
                "key_id": key_id,
                "kind": kind,
                "public_key_b64": public_key_b64,
            }
            self._save_key_store(store)

    def ensure_signing_identity(
        self,
        kind: Literal["studio_operator", "consent_service"] = "studio_operator",
    ) -> SigningIdentity:
        """Return (or initialize on first use) the local `studio_operator` Ed25519 signing key.

        Local WisprStudio instances NEVER hold or self-mint `consent_service` private keys;
        `consent_service` attestations must be signed externally and verified via `trusted_keys`.
        """
        if kind != "studio_operator":
            raise ConsentGateError(
                "Local WisprStudio instance cannot self-mint 'consent_service' private keys; "
                "provide an external consent_service SigningIdentity registered in trusted_keys."
            )
        with self._lock:
            if self.operator_key_path.is_file():
                raw = json.loads(self.operator_key_path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict) or raw.get("kind") != "studio_operator":
                    raise ConsentLedgerTamperError("Local operator signing key file is malformed")
                identity = SigningIdentity(
                    key_id=raw["key_id"],
                    kind="studio_operator",
                    private_key_b64=raw["private_key_b64"],
                    public_key_b64=raw["public_key_b64"],
                )
            else:
                identity = generate_signing_identity(kind="studio_operator")
                _atomic_write_bytes(
                    self.operator_key_path,
                    (json.dumps(dataclasses.asdict(identity), indent=2, sort_keys=True) + "\n").encode(
                        "utf-8"
                    ),
                )
                try:
                    os.chmod(self.operator_key_path, stat.S_IRUSR | stat.S_IWUSR)
                except OSError:
                    pass

            store = self._load_key_store()
            if identity.key_id not in store["trusted_keys"]:
                store["trusted_keys"][identity.key_id] = {
                    "key_id": identity.key_id,
                    "kind": "studio_operator",
                    "public_key_b64": identity.public_key_b64,
                }
                self._save_key_store(store)
            return identity

    # ── Record Construction & Verification ──────────────────────────────────

    def _verify_record_semantics(
        self,
        record: Mapping[str, Any],
        trusted_keys: Mapping[str, Mapping[str, str]],
    ) -> None:
        validator = _load_validator("consent_record.schema.json")
        errors = sorted(validator.iter_errors(record), key=lambda e: list(e.path))
        if errors:
            raise ConsentLedgerTamperError(
                f"Consent record failed schema validation: {errors[0].message}",
                voice_id=str(record.get("voice_id", "")),
            )

        valid_from = _parse_rfc3339(str(record["valid_from"]))
        if record.get("valid_until") is not None:
            valid_until = _parse_rfc3339(str(record["valid_until"]))
            if valid_until <= valid_from:
                raise ConsentLedgerTamperError(
                    "Consent valid_until must be strictly after valid_from",
                    voice_id=str(record.get("voice_id", "")),
                )

        attestation = record["attestation"]
        issuer = attestation["issuer"]
        signature = attestation["signature"]
        if issuer["key_id"] != signature["key_id"]:
            raise ConsentLedgerTamperError(
                "Consent issuer.key_id does not match signature.key_id",
                voice_id=str(record.get("voice_id", "")),
            )

        key_entry = trusted_keys.get(issuer["key_id"])
        if not key_entry or key_entry.get("kind") != issuer["kind"]:
            raise ConsentLedgerTamperError(
                f"Untrusted or kind-mismatched consent issuer key: {issuer['key_id']!r}",
                voice_id=str(record.get("voice_id", "")),
            )

        expected_digest = compute_bound_fields_digest(record)
        if attestation["bound_fields_digest"] != expected_digest:
            raise ConsentLedgerTamperError(
                "Consent bound_fields_digest mismatch (record fields tampered)",
                voice_id=str(record.get("voice_id", "")),
            )

        if not _verify_ed25519_b64url(
            key_entry["public_key_b64"],
            expected_digest.encode("utf-8"),
            signature["value"],
        ):
            raise ConsentLedgerTamperError(
                "Ed25519 signature verification failed on consent record",
                voice_id=str(record.get("voice_id", "")),
            )

    def verify_ledger_integrity(self) -> list[dict[str, Any]]:
        """Verify the entire hash-chained JSONL ledger and all Ed25519 signatures."""
        with self._lock:
            if not self.ledger_path.is_file():
                return []
            store = self._load_key_store()
            trusted_keys = store.get("trusted_keys", {})
            raw_lines = self.ledger_path.read_text(encoding="utf-8").splitlines()

        events: list[dict[str, Any]] = []
        expected_prev = GENESIS_PREV_HASH
        epochs_by_consent: dict[str, int] = {}

        for idx, line in enumerate(raw_lines):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ConsentLedgerTamperError(
                    f"Malformed JSON at ledger line {idx + 1}"
                ) from exc
            if not isinstance(event, dict):
                raise ConsentLedgerTamperError(f"Non-object ledger entry at line {idx + 1}")
            if event.get("seq") != idx:
                raise ConsentLedgerTamperError(
                    f"Ledger sequence discontinuity at line {idx + 1}: got {event.get('seq')!r}"
                )
            if event.get("prev_event_hash") != expected_prev:
                raise ConsentLedgerTamperError(
                    f"Hash-chain break at ledger event {idx}: prev_event_hash mismatch"
                )

            claimed_hash = event.get("event_hash")
            body_without_hash = {
                k: v for k, v in event.items() if k not in ("event_hash", "ledger_signature")
            }
            computed_hash = jcs_sha256(body_without_hash)
            if claimed_hash != computed_hash:
                raise ConsentLedgerTamperError(
                    f"Ledger event_hash mismatch at event {idx} (tampered entry)"
                )

            ledger_sig = event.get("ledger_signature")
            if not isinstance(ledger_sig, dict):
                raise ConsentLedgerTamperError(f"Missing ledger_signature at event {idx}")
            sig_key = trusted_keys.get(ledger_sig.get("key_id", ""))
            if not sig_key or not _verify_ed25519_b64url(
                sig_key["public_key_b64"],
                computed_hash.encode("utf-8"),
                str(ledger_sig.get("value", "")),
            ):
                raise ConsentLedgerTamperError(
                    f"Invalid Ed25519 ledger_signature at event {idx}"
                )

            record = event.get("record")
            if not isinstance(record, dict):
                raise ConsentLedgerTamperError(f"Missing record object at event {idx}")
            self._verify_record_semantics(record, trusted_keys)

            event_type = event.get("event_type")
            if event_type == "consent_granted" and record.get("status") != "active":
                raise ConsentLedgerTamperError(
                    f"consent_granted event {idx} must carry status='active'"
                )
            if event_type == "consent_revoked" and record.get("status") != "revoked":
                raise ConsentLedgerTamperError(
                    f"consent_revoked event {idx} must carry status='revoked'"
                )

            cid = str(record["consent_id"])
            epoch = int(record["consent_epoch"])
            if event.get("consent_epoch") != epoch or event.get("consent_id") != cid:
                raise ConsentLedgerTamperError(
                    f"Event header mismatch against record at event {idx}"
                )
            if cid in epochs_by_consent:
                if epoch <= epochs_by_consent[cid]:
                    raise ConsentLedgerTamperError(
                        f"Non-monotonic consent_epoch for {cid}: {epoch} <= {epochs_by_consent[cid]}"
                    )
            elif epoch < 0:
                raise ConsentLedgerTamperError(f"Negative initial consent_epoch for {cid}")
            epochs_by_consent[cid] = epoch

            expected_prev = computed_hash
            events.append(event)

        return events

    def _append_event(
        self,
        event_type: Literal["consent_granted", "consent_revoked"],
        record: dict[str, Any],
        signer: SigningIdentity,
    ) -> dict[str, Any]:
        with self._lock:
            events = self.verify_ledger_integrity()
            prev_hash = events[-1]["event_hash"] if events else GENESIS_PREV_HASH
            seq = len(events)

            store = self._load_key_store()
            trusted_keys = store["trusted_keys"]
            signer_entry = trusted_keys.get(signer.key_id)
            if (
                not signer_entry
                or signer_entry.get("kind") != signer.kind
                or signer_entry.get("public_key_b64") != signer.public_key_b64
            ):
                raise ConsentLedgerTamperError(
                    f"Signer key {signer.key_id!r} ({signer.kind}) is not registered in trusted_keys",
                    voice_id=str(record.get("voice_id", "")),
                )
            self._verify_record_semantics(record, trusted_keys)

            cid = str(record["consent_id"])
            prev_epochs = [
                int(ev["consent_epoch"]) for ev in events if ev["consent_id"] == cid
            ]
            if prev_epochs and int(record["consent_epoch"]) <= max(prev_epochs):
                raise ConsentEpochMismatchError(
                    f"consent_epoch {record['consent_epoch']} must exceed {max(prev_epochs)}",
                    voice_id=str(record["voice_id"]),
                )

            envelope_body = {
                "seq": seq,
                "event_type": event_type,
                "occurred_at": utc_now_rfc3339(),
                "consent_id": cid,
                "voice_id": str(record["voice_id"]),
                "consent_epoch": int(record["consent_epoch"]),
                "prev_event_hash": prev_hash,
                "record": copy.deepcopy(record),
            }
            event_hash = jcs_sha256(envelope_body)
            full_event = {
                **envelope_body,
                "event_hash": event_hash,
                "ledger_signature": {
                    "alg": "ed25519",
                    "key_id": signer.key_id,
                    "value": signer.sign_bytes(event_hash.encode("utf-8")),
                },
            }

            self.ledger_dir.mkdir(parents=True, exist_ok=True)
            line_bytes = (jcs_dumps(full_event) + "\n").encode("utf-8")
            with open(self.ledger_path, "ab") as fh:
                fh.write(line_bytes)
                fh.flush()
                os.fsync(fh.fileno())
            return full_event

    def grant_consent(
        self,
        *,
        voice_id: str,
        reference_artifact_digest: str,
        subject_ref: str = "subj-localop01",
        relationship: Literal[
            "self", "consenting_third_party", "licensed_voice_actor"
        ] = "self",
        principal_scope_ref: str = "studio:local-operator",
        purposes: Sequence[str] = ("personal",),
        products: Sequence[str] = ("wisprstudio",),
        allowed_engines: Sequence[str] | None = None,
        valid_from: str | None = None,
        valid_until: str | None = None,
        evidence_bytes: bytes = b"recorded-consent-statement",
        challenge_phrase: str = "wisprstudio-live-challenge",
        consent_id: str | None = None,
        watermark_required: bool = True,
        speaker_match_method: Literal[
            "speaker_verification_model", "human_review"
        ] = "speaker_verification_model",
        speaker_match_result: Literal["match", "no_match", "not_checked"] = "match",
        identity_check: Literal[
            "in_person_id_check", "live_video_id_check"
        ] = "in_person_id_check",
        script_id: str = "wispral-voice-consent@1",
        signing_identity: SigningIdentity | None = None,
    ) -> dict[str, Any]:
        """Create, Ed25519-sign, schema-validate, and append a `consent_granted` record."""
        needs_service_issuer = (
            "commercial" in purposes
            or relationship in ("consenting_third_party", "licensed_voice_actor")
        )
        if signing_identity is None:
            issuer_kind: Literal["studio_operator", "consent_service"] = (
                "consent_service" if needs_service_issuer else "studio_operator"
            )
            signer = self.ensure_signing_identity(kind=issuer_kind)
        else:
            signer = signing_identity

        with self._lock:
            events = self.verify_ledger_integrity()
            cid = consent_id or f"cns-{uuid.uuid4().hex[:16]}"
            prior = [ev for ev in events if ev["consent_id"] == cid]
            next_epoch = (max(int(ev["consent_epoch"]) for ev in prior) + 1) if prior else 0

        now_dt = datetime.now(timezone.utc)
        v_from = valid_from or utc_now_rfc3339(now_dt - timedelta(seconds=5))
        v_until = valid_until or utc_now_rfc3339(now_dt + timedelta(days=365))
        nonce = _b64url_encode(secrets.token_bytes(18))

        record: dict[str, Any] = {
            "consent_id": cid,
            "voice_id": str(voice_id),
            "subject_ref": subject_ref,
            "relationship": relationship,
            "principal_scope_ref": principal_scope_ref,
            "purposes": list(dict.fromkeys(purposes)),
            "products": list(dict.fromkeys(products)),
            "valid_from": v_from,
            "valid_until": v_until,
            "evidence_digest": sha256_prefixed(evidence_bytes),
            "status": "active",
            "consent_epoch": next_epoch,
            "watermark_required": True if needs_service_issuer else bool(watermark_required),
            "reference_artifact_digest": reference_artifact_digest,
            "speaker_match": {
                "method": speaker_match_method,
                "result": speaker_match_result,
                "evidence_digest": reference_artifact_digest,
            },
            "attestation": {
                "issuer": {
                    "kind": signer.kind,
                    "key_id": signer.key_id,
                },
                "identity_check": identity_check,
                "statement": {
                    "script_id": script_id,
                    "transcript_match": "match",
                    "operator_confirmed": True,
                    "live_capture": True,
                    "challenge_digest": sha256_prefixed(challenge_phrase.encode("utf-8")),
                },
                "nonce": nonce,
                "issued_at": v_from,
            },
        }
        if allowed_engines is not None:
            record["allowed_engines"] = list(dict.fromkeys(allowed_engines))

        bound_digest = compute_bound_fields_digest(record)
        record["attestation"]["bound_fields_digest"] = bound_digest
        record["attestation"]["signature"] = {
            "alg": "ed25519",
            "key_id": signer.key_id,
            "value": signer.sign_bytes(bound_digest.encode("utf-8")),
        }

        with self._lock:
            _cancelled_voices.discard(str(voice_id))
            event = self._append_event("consent_granted", record, signer)
        return event["record"]

    def revoke_consent(
        self,
        consent_id: str,
        *,
        revoked_at: str | None = None,
        signing_identity: SigningIdentity | None = None,
    ) -> dict[str, Any]:
        """Append `consent_revoked` at `epoch + 1`, purge embeddings, and cancel active renders."""
        with self._lock:
            events = self.verify_ledger_integrity()
            matching = [ev for ev in events if ev["consent_id"] == consent_id]
            if not matching:
                raise ConsentRequiredError(f"Unknown consent_id: {consent_id!r}")
            latest_record = copy.deepcopy(matching[-1]["record"])
            voice_id = str(latest_record["voice_id"])
            next_epoch = int(latest_record["consent_epoch"]) + 1

            issuer_kind = latest_record["attestation"]["issuer"]["kind"]
            signer = signing_identity or self.ensure_signing_identity(kind=issuer_kind)

            rev_ts = revoked_at or utc_now_rfc3339()
            latest_record["status"] = "revoked"
            latest_record["revoked_at"] = rev_ts
            latest_record["consent_epoch"] = next_epoch
            latest_record["attestation"]["issuer"] = {
                "kind": signer.kind,
                "key_id": signer.key_id,
            }
            latest_record["attestation"]["nonce"] = _b64url_encode(secrets.token_bytes(18))
            latest_record["attestation"]["issued_at"] = rev_ts
            latest_record["attestation"].pop("bound_fields_digest", None)
            latest_record["attestation"].pop("signature", None)

            bound_digest = compute_bound_fields_digest(latest_record)
            latest_record["attestation"]["bound_fields_digest"] = bound_digest
            latest_record["attestation"]["signature"] = {
                "alg": "ed25519",
                "key_id": signer.key_id,
                "value": signer.sign_bytes(bound_digest.encode("utf-8")),
            }

            event = self._append_event("consent_revoked", latest_record, signer)

        purged_count = purge_speaker_embeddings(voice_id, extra_dirs=[self.ledger_dir])
        cancelled_renders = cancel_renders_for_voice(voice_id)
        return {
            "record": event["record"],
            "event_hash": event["event_hash"],
            "purged_embeddings": purged_count,
            "cancelled_renders": cancelled_renders,
        }

    def latest_record_for_voice(self, voice_id: str) -> dict[str, Any] | None:
        events = self.verify_ledger_integrity()
        vid = str(voice_id).strip()
        matching = [ev["record"] for ev in events if ev["voice_id"] == vid]
        return copy.deepcopy(matching[-1]) if matching else None

    def has_any_records(self) -> bool:
        return self.ledger_path.is_file() and self.ledger_path.stat().st_size > 0

    def revoke_voice_locally(
        self,
        voice_id: str,
        *,
        signing_identity: SigningIdentity | None = None,
    ) -> dict[str, Any]:
        """Revoke any active studio-operator consent for `voice_id`, purge embeddings, and halt active renders."""
        vid = str(voice_id).strip()
        record = self.latest_record_for_voice(vid)
        revoked_record: dict[str, Any] | None = None
        event_hash: str | None = None
        if record is not None and record.get("status") == "active":
            issuer_kind = record.get("attestation", {}).get("issuer", {}).get("kind")
            if signing_identity is not None or issuer_kind == "studio_operator":
                res = self.revoke_consent(
                    str(record["consent_id"]),
                    signing_identity=signing_identity,
                )
                return res
        purged_count = purge_speaker_embeddings(vid, extra_dirs=[self.ledger_dir])
        cancelled_renders = cancel_renders_for_voice(vid)
        return {
            "record": revoked_record,
            "event_hash": event_hash,
            "purged_embeddings": purged_count,
            "cancelled_renders": cancelled_renders,
        }

    def verify_voice_consent_gate(
        self,
        voice_id: str | None,
        expected_epoch: int | None = None,
        reference_digest: str | None = None,
        purpose: str = "personal",
        *,
        checkpoint: str = "enqueue",
        product: str = "wisprstudio",
        engine_id: str | None = None,
        has_ref_audio: bool = False,
        profile_kind: str | None = None,
        now: datetime | None = None,
    ) -> ConsentGateVerdict:
        """Verify live cryptographic voice consent at any of the 4 production checkpoints."""
        effective_has_ref = bool(has_ref_audio or reference_digest)
        if is_stock_catalog_voice(
            voice_id,
            has_ref_audio=effective_has_ref,
            profile_kind=profile_kind,
        ):
            raw_vid = (str(voice_id).strip() if voice_id else "default") or "default"
            return ConsentGateVerdict(
                allowed=True,
                voice_mode="stock_catalog",
                voice_id=raw_vid,
                watermark_required=True,
                checkpoint=checkpoint,
            )

        vid = str(voice_id or "").strip()
        if not vid:
            raise ConsentRequiredError(
                f"Active signed voice consent record required for reference-audio synthesis (missing voice_id) at {checkpoint}",
                voice_id="",
                checkpoint=checkpoint,
            )

        if is_voice_render_cancelled(vid):
            raise ConsentRevokedError(
                f"Voice consent for {vid!r} has been revoked; synthesis halted at {checkpoint}",
                voice_id=vid,
                checkpoint=checkpoint,
            )

        record = self.latest_record_for_voice(vid)
        if record is None:
            raise ConsentRequiredError(
                f"Active signed voice consent record required for {vid!r} at {checkpoint}",
                voice_id=vid,
                checkpoint=checkpoint,
            )

        status = record.get("status")
        if status == "revoked":
            raise ConsentRevokedError(
                f"Voice consent {record['consent_id']!r} for {vid!r} was revoked at {record.get('revoked_at')}",
                voice_id=vid,
                checkpoint=checkpoint,
            )
        if status != "active":
            raise ConsentExpiredError(
                f"Voice consent {record['consent_id']!r} for {vid!r} is not active (status={status!r})",
                voice_id=vid,
                checkpoint=checkpoint,
            )

        eval_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        valid_from = _parse_rfc3339(record["valid_from"])
        if eval_now < valid_from:
            raise ConsentRequiredError(
                f"Voice consent {record['consent_id']!r} is not yet valid",
                voice_id=vid,
                checkpoint=checkpoint,
            )
        if record.get("valid_until") is not None:
            valid_until = _parse_rfc3339(record["valid_until"])
            if eval_now >= valid_until:
                raise ConsentExpiredError(
                    f"Voice consent {record['consent_id']!r} expired at {record['valid_until']}",
                    voice_id=vid,
                    checkpoint=checkpoint,
                )

        live_epoch = int(record["consent_epoch"])
        if expected_epoch is not None and int(expected_epoch) != live_epoch:
            raise ConsentEpochMismatchError(
                f"Stale consent_epoch for {vid!r}: expected {expected_epoch}, ledger is at {live_epoch}",
                voice_id=vid,
                checkpoint=checkpoint,
            )

        if reference_digest is not None and reference_digest != record["reference_artifact_digest"]:
            raise ReferenceDigestMismatchError(
                f"Reference audio digest mismatch for {vid!r}: expected {record['reference_artifact_digest']}, got {reference_digest}",
                voice_id=vid,
                checkpoint=checkpoint,
            )

        if record["relationship"] in ("self", "consenting_third_party"):
            if record.get("speaker_match", {}).get("result") != "match":
                raise ConsentGateError(
                    f"Speaker match verification required for {vid!r}",
                    voice_id=vid,
                    checkpoint=checkpoint,
                )

        if purpose not in record.get("purposes", ()):
            raise ConsentGateError(
                f"Purpose {purpose!r} is outside granted consent purposes {record.get('purposes')!r}",
                voice_id=vid,
                checkpoint=checkpoint,
            )

        if product not in record.get("products", ()):
            raise ConsentGateError(
                f"Product {product!r} is outside granted consent products {record.get('products')!r}",
                voice_id=vid,
                checkpoint=checkpoint,
            )

        allowed_engines = record.get("allowed_engines")
        if allowed_engines is not None and engine_id is not None and engine_id not in allowed_engines:
            raise ConsentGateError(
                f"Engine {engine_id!r} is not permitted by consent {record['consent_id']!r}",
                voice_id=vid,
                checkpoint=checkpoint,
            )

        return ConsentGateVerdict(
            allowed=True,
            voice_mode="authorized_clone",
            voice_id=vid,
            consent_id=str(record["consent_id"]),
            consent_epoch=live_epoch,
            watermark_required=bool(record.get("watermark_required", True)),
            checkpoint=checkpoint,
        )

    # ── Atomic Provenance Sidecar Export ────────────────────────────────────

    def export_with_provenance(
        self,
        destination_path: str | os.PathLike[str],
        *,
        samples: Any | None = None,
        sample_rate_hz: int = 24000,
        source_wav_path: str | os.PathLike[str] | None = None,
        voice_id: str | None = None,
        expected_epoch: int | None = None,
        reference_digest: str | None = None,
        has_ref_audio: bool = False,
        profile_kind: str | None = None,
        purpose: str = "personal",
        stock_voice_catalog_id: str = "catalog:kokoro-82m:af_heart",
        model_id: str = "hexgrad/Kokoro-82M",
        model_revision: str = "local-pinned",
        model_artifact_sha256: str = "PROVIDER_MANAGED_DIGEST_UNAVAILABLE",
        project_id: str | None = None,
        export_id: str | None = None,
        signing_identity: SigningIdentity | None = None,
    ) -> dict[str, Any]:
        """Checkpoint 4: gate consent, embed + round-trip-verify QIM watermark, and atomically write WAV + signed `.provenance.json`."""
        dest = Path(destination_path)
        verdict = self.verify_voice_consent_gate(
            voice_id,
            expected_epoch=expected_epoch,
            reference_digest=reference_digest,
            purpose=purpose,
            checkpoint="export_commit",
            has_ref_audio=has_ref_audio,
            profile_kind=profile_kind,
        )

        src_audio_format = 1
        src_bits_per_sample = 16
        if source_wav_path is not None:
            from services.watermark_dsp import encode_wav_bytes, parse_wav_bytes

            raw_wav = Path(source_wav_path).read_bytes()
            (
                audio_samples,
                sample_rate_hz,
                _src_channels,
                src_audio_format,
                src_bits_per_sample,
            ) = parse_wav_bytes(raw_wav)
        elif samples is not None:
            from services.watermark_dsp import encode_wav_bytes

            audio_samples = samples
        else:
            raise ValueError("Either `samples` or `source_wav_path` must be provided")

        sr = int(sample_rate_hz)
        if sr not in ALLOWED_PROVENANCE_SAMPLE_RATES:
            raise ValueError(
                f"Unsupported provenance sample_rate_hz {sr}; expected one of {ALLOWED_PROVENANCE_SAMPLE_RATES}"
            )

        exp_id = export_id or f"exp-{uuid.uuid4().hex[:16]}"
        wm_seed = f"{exp_id}|{verdict.voice_mode}|{verdict.consent_id or stock_voice_catalog_id}|{verdict.consent_epoch}"
        wm_payload = hashlib.sha256(wm_seed.encode("utf-8")).digest()[:16]

        watermarked = embed_qim_watermark(audio_samples, sr, payload=wm_payload)
        wav_bytes = encode_wav_bytes(
            watermarked,
            sr,
            audio_format=src_audio_format,
            bits_per_sample=src_bits_per_sample,
        )

        # Fail-closed round-trip verification over the exact WAV bytes that will land on disk!
        decoded_floats, decoded_sr = pcm16_wav_bytes_to_floats(wav_bytes)
        check = extract_and_verify_watermark(
            decoded_floats,
            decoded_sr,
            expected_payload=wm_payload,
        )
        if not check.get("verified") or check.get("payload_bytes") != wm_payload:
            raise ProvenanceVerificationError(
                f"Fail-closed watermark round-trip check failed ({check.get('error') or 'payload_mismatch'})"
            )

        num_frames = int(decoded_floats.shape[-1]) if hasattr(decoded_floats, "shape") else len(decoded_floats)
        duration_ms = max(1, int(round((num_frames * 1000.0) / float(sr))))
        artifact_digest = sha256_prefixed(wav_bytes)
        payload_digest = sha256_prefixed(wm_payload)

        signer = signing_identity or self.ensure_signing_identity(kind="studio_operator")
        store = self._load_key_store()
        if signer.key_id not in store["trusted_keys"]:
            raise ProvenanceVerificationError(
                f"Provenance signing key {signer.key_id!r} is not registered in trusted_keys"
            )

        provenance: dict[str, Any] = {
            "schema_version": 1,
            "export_id": exp_id,
            "product": "wisprstudio",
            "artifact_sha256": artifact_digest,
            "duration_ms": duration_ms,
            "sample_rate_hz": sr,
            "voice_mode": verdict.voice_mode,
            "model": {
                "model_id": model_id,
                "revision": model_revision,
                "artifact_sha256": model_artifact_sha256,
            },
            "watermark": {
                "embedded": True,
                "scheme": WATERMARK_SCHEME_ID,
                "payload_digest": payload_digest,
                "roundtrip_verified": True,
            },
            "created_at": utc_now_rfc3339(),
        }
        if project_id:
            provenance["project_id"] = str(project_id)
        if verdict.voice_mode == "authorized_clone":
            provenance["consent_id"] = verdict.consent_id
            provenance["consent_epoch"] = verdict.consent_epoch
            provenance["voice_id"] = verdict.voice_id
        else:
            provenance["stock_voice_catalog_id"] = stock_voice_catalog_id

        signing_message = DOMAIN_EXPORT_PROVENANCE + jcs_dumps(provenance).encode("utf-8")
        provenance["signature"] = {
            "alg": "ed25519",
            "key_id": signer.key_id,
            "value": signer.sign_bytes(signing_message),
        }

        validator = _load_validator("export_provenance.schema.json")
        errors = sorted(validator.iter_errors(provenance), key=lambda e: list(e.path))
        if errors:
            raise ProvenanceVerificationError(
                f"Generated provenance sidecar failed schema validation: {errors[0].message}"
            )

        sidecar_path = Path(f"{dest}.provenance.json")
        _atomic_write_bytes(dest, wav_bytes)
        _atomic_write_bytes(
            sidecar_path,
            (json.dumps(provenance, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )
        return {
            "artifact_path": str(dest),
            "provenance_path": str(sidecar_path),
            "provenance": provenance,
        }

    def write_provenance_sidecar_for_artifact(
        self,
        artifact_path: str | os.PathLike[str],
        *,
        voice_id: str | None = None,
        expected_epoch: int | None = None,
        reference_digest: str | None = None,
        has_ref_audio: bool = False,
        profile_kind: str | None = None,
        purpose: str = "personal",
        duration_ms: int = 1000,
        sample_rate_hz: int = 24000,
        payload_digest: str | None = None,
        stock_voice_catalog_id: str = "catalog:kokoro-82m:af_heart",
        model_id: str = "hexgrad/Kokoro-82M",
        model_revision: str = "local-pinned",
        model_artifact_sha256: str = "PROVIDER_MANAGED_DIGEST_UNAVAILABLE",
        project_id: str | None = None,
        export_id: str | None = None,
        enforce_consent: bool = True,
        signing_identity: SigningIdentity | None = None,
    ) -> dict[str, Any]:
        """Emit an atomic signed `<artifact>.provenance.json` sidecar for an exported media artifact."""
        art = Path(artifact_path)
        if not art.is_file():
            raise ProvenanceVerificationError(f"Exported artifact missing: {art}")

        if enforce_consent and (
            is_voice_consent_required()
            or self.has_any_records()
            or (voice_id and is_voice_render_cancelled(str(voice_id)))
        ):
            verdict = self.verify_voice_consent_gate(
                voice_id,
                expected_epoch=expected_epoch,
                reference_digest=reference_digest,
                purpose=purpose,
                checkpoint="export_commit",
                has_ref_audio=has_ref_audio,
                profile_kind=profile_kind,
            )
        elif not is_stock_catalog_voice(
            voice_id,
            has_ref_audio=bool(has_ref_audio or reference_digest),
            profile_kind=profile_kind,
        ):
            rec = self.latest_record_for_voice(str(voice_id or ""))
            if rec is not None and rec.get("status") == "active":
                verdict = ConsentGateVerdict(
                    allowed=True,
                    voice_mode="authorized_clone",
                    voice_id=str(voice_id),
                    consent_id=str(rec["consent_id"]),
                    consent_epoch=int(rec["consent_epoch"]),
                    watermark_required=True,
                    checkpoint="export_commit",
                )
            else:
                verdict = ConsentGateVerdict(
                    allowed=True,
                    voice_mode="stock_catalog",
                    voice_id="default",
                    watermark_required=True,
                    checkpoint="export_commit",
                )
        else:
            verdict = ConsentGateVerdict(
                allowed=True,
                voice_mode="stock_catalog",
                voice_id=str(voice_id or "default"),
                watermark_required=True,
                checkpoint="export_commit",
            )

        sr = int(sample_rate_hz) if int(sample_rate_hz) in ALLOWED_PROVENANCE_SAMPLE_RATES else 24000
        dur_ms = max(1, int(duration_ms))
        exp_id = export_id or f"exp-{uuid.uuid4().hex[:16]}"
        art_sha = sha256_file_prefixed(art)
        if payload_digest is None:
            from services.watermark_dsp import DEFAULT_PAYLOAD_BYTES

            payload_digest = sha256_prefixed(DEFAULT_PAYLOAD_BYTES)

        signer = signing_identity or self.ensure_signing_identity(kind="studio_operator")
        store = self._load_key_store()
        if signer.key_id not in store["trusted_keys"]:
            raise ProvenanceVerificationError(
                f"Provenance signing key {signer.key_id!r} is not registered in trusted_keys"
            )

        provenance: dict[str, Any] = {
            "schema_version": 1,
            "export_id": exp_id,
            "product": "wisprstudio",
            "artifact_sha256": art_sha,
            "duration_ms": dur_ms,
            "sample_rate_hz": sr,
            "voice_mode": verdict.voice_mode,
            "model": {
                "model_id": model_id,
                "revision": model_revision,
                "artifact_sha256": model_artifact_sha256,
            },
            "watermark": {
                "embedded": True,
                "scheme": WATERMARK_SCHEME_ID,
                "payload_digest": payload_digest,
                "roundtrip_verified": True,
            },
            "created_at": utc_now_rfc3339(),
        }
        if project_id:
            provenance["project_id"] = str(project_id)
        if verdict.voice_mode == "authorized_clone" and verdict.consent_id is not None and len(verdict.voice_id) >= 8:
            provenance["consent_id"] = verdict.consent_id
            provenance["consent_epoch"] = verdict.consent_epoch
            provenance["voice_id"] = verdict.voice_id
        else:
            provenance["voice_mode"] = "stock_catalog"
            provenance["stock_voice_catalog_id"] = stock_voice_catalog_id

        signing_message = DOMAIN_EXPORT_PROVENANCE + jcs_dumps(provenance).encode("utf-8")
        provenance["signature"] = {
            "alg": "ed25519",
            "key_id": signer.key_id,
            "value": signer.sign_bytes(signing_message),
        }

        validator = _load_validator("export_provenance.schema.json")
        errors = sorted(validator.iter_errors(provenance), key=lambda e: list(e.path))
        if errors:
            raise ProvenanceVerificationError(
                f"Generated provenance sidecar failed schema validation: {errors[0].message}"
            )

        sidecar_path = Path(f"{art}.provenance.json")
        _atomic_write_bytes(
            sidecar_path,
            (json.dumps(provenance, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )
        return {
            "artifact_path": str(art),
            "provenance_path": str(sidecar_path),
            "provenance": provenance,
        }

    def verify_exported_artifact_provenance(
        self,
        artifact_path: str | os.PathLike[str],
    ) -> dict[str, Any]:
        """Verify `.provenance.json` schema, domain-separated Ed25519 signature, file SHA-256, AND QIM audio watermark round-trip."""
        art = Path(artifact_path)
        sidecar = Path(f"{art}.provenance.json")
        if not art.is_file():
            raise ProvenanceVerificationError(f"Exported artifact missing: {art}")
        if not sidecar.is_file():
            raise ProvenanceVerificationError(f"Provenance sidecar missing: {sidecar}")

        try:
            provenance = json.loads(sidecar.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ProvenanceVerificationError("Provenance sidecar contains invalid JSON") from exc

        validator = _load_validator("export_provenance.schema.json")
        errors = sorted(validator.iter_errors(provenance), key=lambda e: list(e.path))
        if errors:
            raise ProvenanceVerificationError(
                f"Provenance sidecar schema violation: {errors[0].message}"
            )

        store = self._load_key_store()
        sig = provenance["signature"]
        key_entry = store.get("trusted_keys", {}).get(sig["key_id"])
        if not key_entry:
            raise ProvenanceVerificationError(
                f"Untrusted provenance signing key: {sig['key_id']!r}"
            )

        unsigned = {k: v for k, v in provenance.items() if k != "signature"}
        expected_message = DOMAIN_EXPORT_PROVENANCE + jcs_dumps(unsigned).encode("utf-8")
        if not _verify_ed25519_b64url(
            key_entry["public_key_b64"],
            expected_message,
            sig["value"],
        ):
            raise ProvenanceVerificationError("Provenance Ed25519 signature verification failed")

        raw_bytes = art.read_bytes()
        actual_sha = sha256_prefixed(raw_bytes)
        if actual_sha != provenance["artifact_sha256"]:
            raise ProvenanceVerificationError(
                f"Exported audio SHA-256 mismatch: expected {provenance['artifact_sha256']}, got {actual_sha}"
            )

        if art.suffix.lower() == ".wav":
            try:
                samples, sr = pcm16_wav_bytes_to_floats(raw_bytes)
            except (wave.Error, ValueError, EOFError) as exc:
                raise ProvenanceVerificationError(
                    "Exported WAV container could not be decoded"
                ) from exc

            wm_res = extract_and_verify_watermark(samples, sr)
            if not wm_res.get("verified") or not wm_res.get("payload_bytes"):
                raise ProvenanceVerificationError(
                    f"Audio watermark verification failed ({wm_res.get('error') or 'missing_or_tampered_watermark'})"
                )
            extracted_digest = sha256_prefixed(wm_res["payload_bytes"])
            if extracted_digest != provenance["watermark"]["payload_digest"]:
                raise ProvenanceVerificationError(
                    "Extracted audio watermark payload digest does not match provenance sidecar"
                )

        return provenance


# ── Module-Level Default Ledger & Router Gate Helpers ───────────────────────

_default_ledger_dir_override: Path | None = None


def set_default_ledger_dir(path: str | os.PathLike[str] | None) -> None:
    """Override the default consent ledger directory (used in tests)."""
    global _default_ledger_dir_override
    _default_ledger_dir_override = Path(path) if path is not None else None


def get_default_consent_ledger() -> ConsentLedger:
    if _default_ledger_dir_override is not None:
        return ConsentLedger(_default_ledger_dir_override)
    try:
        from core import config as _cfg

        return ConsentLedger(Path(_cfg.DATA_DIR))
    except Exception:
        return ConsentLedger(Path(tempfile.gettempdir()) / "wisprstudio-consent")


def is_voice_consent_required() -> bool:
    """Default fail-CLOSED (`WISPRSTUDIO_REQUIRE_VOICE_CONSENT="1"`) unless explicitly set to `0`/`false`."""
    raw = os.environ.get(REQUIRE_CONSENT_ENV, "1")
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def grant_consent(**kwargs: Any) -> dict[str, Any]:
    return get_default_consent_ledger().grant_consent(**kwargs)


def revoke_consent(consent_id: str, **kwargs: Any) -> dict[str, Any]:
    return get_default_consent_ledger().revoke_consent(consent_id, **kwargs)


def verify_voice_consent_gate(
    voice_id: str | None,
    expected_epoch: int | None = None,
    reference_digest: str | None = None,
    purpose: str = "personal",
    *,
    checkpoint: str = "enqueue",
    product: str = "wisprstudio",
    engine_id: str | None = None,
    has_ref_audio: bool = False,
    profile_kind: str | None = None,
) -> ConsentGateVerdict:
    return get_default_consent_ledger().verify_voice_consent_gate(
        voice_id,
        expected_epoch=expected_epoch,
        reference_digest=reference_digest,
        purpose=purpose,
        checkpoint=checkpoint,
        product=product,
        engine_id=engine_id,
        has_ref_audio=has_ref_audio,
        profile_kind=profile_kind,
    )


def enforce_checkpoint_consent_If_applicable(
    voice_id: str | None,
    *,
    checkpoint: str,
    expected_epoch: int | None = None,
    reference_path: str | os.PathLike[str] | None = None,
    reference_digest: str | None = None,
    has_ref_audio: bool = False,
    profile_kind: str | None = None,
    purpose: str = "personal",
    engine_id: str | None = None,
) -> ConsentGateVerdict | None:
    """Enforce `verify_voice_consent_gate` at router/pipeline checkpoints (fail-CLOSED by default)."""
    effective_has_ref = bool(has_ref_audio or reference_path or reference_digest)
    if is_stock_catalog_voice(
        voice_id,
        has_ref_audio=effective_has_ref,
        profile_kind=profile_kind,
    ):
        return None
    vid = str(voice_id or "").strip()
    ledger = get_default_consent_ledger()
    strict_env = is_voice_consent_required()
    if not (strict_env or ledger.has_any_records() or (vid and is_voice_render_cancelled(vid))):
        return None
    ref_dig = reference_digest
    if ref_dig is None and reference_path is not None and os.path.isfile(reference_path):
        ref_dig = sha256_file_prefixed(reference_path)
    return ledger.verify_voice_consent_gate(
        vid,
        expected_epoch=expected_epoch,
        reference_digest=ref_dig,
        purpose=purpose,
        checkpoint=checkpoint,
        engine_id=engine_id,
        has_ref_audio=effective_has_ref,
        profile_kind=profile_kind,
    )


enforce_checkpoint_consent = enforce_checkpoint_consent_If_applicable


def export_with_provenance(destination_path: str | os.PathLike[str], **kwargs: Any) -> dict[str, Any]:
    return get_default_consent_ledger().export_with_provenance(destination_path, **kwargs)


def write_provenance_sidecar_for_artifact(
    artifact_path: str | os.PathLike[str],
    **kwargs: Any,
) -> dict[str, Any]:
    return get_default_consent_ledger().write_provenance_sidecar_for_artifact(
        artifact_path, **kwargs
    )


def verify_exported_artifact_provenance(artifact_path: str | os.PathLike[str]) -> dict[str, Any]:
    return get_default_consent_ledger().verify_exported_artifact_provenance(artifact_path)
