"""Offline pure-DSP + optional visible audio watermarking for WisprStudio.

Replaces the legacy AudioSeal `torch.hub` runtime network fetch with the
deterministic, zero-network, zero-external-weights `wispral-qim-v1` QIM
watermarker in `services.watermark_dsp`.

Module import never requires `torch` or network access.
"""

from __future__ import annotations

import contextlib
import logging
import math
import threading
import time
from typing import Any, Optional

from core.prefs import resolve
from core.render_trace import timed as _render_timed
from services.watermark_dsp import (
    DEFAULT_PAYLOAD_BYTES,
    SCHEME,
    _BLOCKS_PER_FRAME,
    block_size_for_rate,
    embed_qim_watermark,
    extract_and_verify_watermark,
)

logger = logging.getLogger("omnivoice.watermark")


class WatermarkError(RuntimeError):
    """Raised when mandatory offline QIM audio watermarking fails."""

# Legacy test-seam attributes kept inert for unit tests that inspect lifecycle
# or inject custom test doubles; never populated from `audioseal` or `torch.hub`.
_generator = None
_detector = None
_audioseal_available: Optional[bool] = True
_last_used = 0.0
_generator_lock = threading.Lock()
_detector_lock = threading.Lock()
_prefetched_unused = False
_generator_failed_at: Optional[float] = None
_GENERATOR_RETRY_SECONDS = 600.0

OMNI_MESSAGE = [0, 1, 0, 0, 1, 1, 1, 1, 0, 1, 0, 0, 1, 1, 0, 1]
_CHUNK_SECONDS = 30
_HEADROOM_PASSES = 3
_AUDIOSEAL_SAMPLE_RATE = 16000

_eager_lock = threading.Lock()
_eager_state: dict = {"depth": 0, "saved": None}


@contextlib.contextmanager
def _eager_audioseal():
    """Compatibility no-op context manager (pure-DSP QIM never invokes torch.compile)."""
    yield


def _iter_chunks(audio: Any, sample_rate: int):
    """Yield <= ~_CHUNK_SECONDS slices aligned to exact 44-block QIM frame boundaries; fold sub-second tail."""
    total = audio.shape[-1] if hasattr(audio, "shape") else len(audio)
    if total == 0:
        return
    sr = max(1, int(sample_rate))
    frame_samples = max(1, _BLOCKS_PER_FRAME * block_size_for_rate(sr))
    raw_step = max(frame_samples, _CHUNK_SECONDS * sr)
    step = max(frame_samples, (raw_step // frame_samples) * frame_samples)
    starts = list(range(0, total, step))
    if len(starts) > 1 and total - starts[-1] < sr:
        starts.pop()
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else total
        yield audio[..., start:end] if hasattr(audio, "shape") else audio[start:end]


def _check_available() -> bool:
    """Pure-DSP `wispral-qim-v1` is built in and always available offline."""
    if _audioseal_available is False:
        return False
    return True


def _get_generator(mark_prefetched: bool = False):
    global _last_used, _prefetched_unused
    with _generator_lock:
        _last_used = time.monotonic()
        if not mark_prefetched:
            _prefetched_unused = False
        return _generator


def _get_detector():
    global _last_used
    with _detector_lock:
        _last_used = time.monotonic()
        return _detector


def prefetch_generator(*, allow_download: bool = False) -> None:
    """No-op: `wispral-qim-v1` needs zero model weights and zero downloads."""
    _ = allow_download
    return None


def release_idle_models(idle_seconds: float, *, now: Optional[float] = None) -> bool:
    """Release any injected test models after `idle_seconds`."""
    global _generator, _detector, _prefetched_unused
    with _generator_lock, _detector_lock:
        if _generator is None and _detector is None:
            return False
        stamp = time.monotonic() if now is None else float(now)
        if stamp - _last_used < idle_seconds:
            return False
        if _prefetched_unused:
            _prefetched_unused = False
            return False
        _generator = None
        _detector = None
    return True


def is_enabled() -> bool:
    """Check if invisible watermarking is enabled in user preferences."""
    return resolve("watermark.invisible", default=True) is not False


def will_mark() -> bool:
    """True when `mark_synthetic` will embed an invisible watermark."""
    return is_enabled() and _check_available()


def is_visible_audio_enabled() -> bool:
    return resolve("watermark.visible_audio", default=False) is True


def is_visible_video_enabled() -> bool:
    return resolve("watermark.visible_video", default=True) is not False


def mark_synthetic(
    waveform: Any,
    sample_rate: int,
    *,
    context: str,
    force: bool = False,
    watermark_required: bool = False,
    payload: bytes | None = None,
) -> Any:
    """Provenance chokepoint for all synthetic audio produced by WisprStudio."""
    must_force = bool(force or watermark_required)
    marked = embed_watermark(
        waveform,
        sample_rate,
        payload=payload,
        force=must_force,
        watermark_required=watermark_required,
    )
    if marked is not waveform:
        logger.debug("synthetic audio provenance-marked (%s, scheme=%s)", context, SCHEME)
    return marked


@_render_timed("watermark")
async def mark_synthetic_async(
    waveform: Any,
    sample_rate: int,
    *,
    context: str,
    force: bool = False,
    watermark_required: bool = False,
    payload: bytes | None = None,
    timeout: float | None = None,
) -> Any:
    """Async provenance chokepoint on the bounded watermark worker pool (fail-closed)."""
    import asyncio
    import functools

    from services.model_manager import (
        GpuJobTimeoutError,
        GpuPoolBusyError,
        get_watermark_pool,
        run_on_gpu_pool_guarded,
    )

    try:
        pool = get_watermark_pool()
    except RuntimeError as exc:
        raise WatermarkError("Watermark worker pool is unavailable during audio marking") from exc

    job = functools.partial(
        mark_synthetic,
        waveform,
        sample_rate,
        context=context,
        force=bool(force or watermark_required),
        watermark_required=watermark_required,
        payload=payload,
    )
    try:
        if timeout is not None:
            return await run_on_gpu_pool_guarded(
                job, what="Audio watermark", timeout=timeout, executor=pool
            )
        return await asyncio.get_running_loop().run_in_executor(pool, job)
    except (GpuJobTimeoutError, GpuPoolBusyError) as exc:
        raise WatermarkError(f"Audio watermarking timed out or pool saturated ({context})") from exc


def embed_watermark(
    waveform: Any,
    sample_rate: int,
    message: Optional[list[int]] = None,
    *,
    payload: bytes | None = None,
    force: bool = False,
    watermark_required: bool = False,
) -> Any:
    """Embed imperceptible `wispral-qim-v1` watermark into `waveform` offline (fail-closed)."""
    must_mark = bool(force or watermark_required)
    if not must_mark and not is_enabled():
        return waveform
    if not _check_available():
        if must_mark:
            raise WatermarkError("Offline QIM watermarker is required for cloned voices, but unavailable")
        return waveform

    try:
        inj_gen = _get_generator()
        if inj_gen is not None:
            import torch

            msg = torch.tensor(message or OMNI_MESSAGE, dtype=torch.int32).unsqueeze(0)
            original_shape = waveform.shape
            audio = (
                waveform.unsqueeze(0)
                if waveform.dim() == 2
                else waveform.unsqueeze(0).unsqueeze(0)
                if waveform.dim() == 1
                else waveform
            )

            def _run_injected(host):
                return torch.cat(
                    [inj_gen(seg, sample_rate=sample_rate, message=msg) for seg in _iter_chunks(host, sample_rate)],
                    dim=-1,
                )

            watermarked = _run_injected(audio)
            host_peak = float(audio.abs().max()) if audio.numel() else 0.0
            gain = 1.0
            for _ in range(_HEADROOM_PASSES if 0.0 < host_peak <= 1.0 else 0):
                excess = float(watermarked.abs().max()) - 1.0
                scaled_peak = host_peak * gain
                if not excess > 0.0 or excess >= scaled_peak:
                    break
                gain *= (scaled_peak - excess) / scaled_peak
                watermarked = _run_injected(audio * gain)
            if len(original_shape) == 2:
                watermarked = watermarked.squeeze(0)
            elif len(original_shape) == 1:
                watermarked = watermarked.squeeze(0).squeeze(0)
            return watermarked

        eff_payload = payload if payload is not None else (message if message is not None else DEFAULT_PAYLOAD_BYTES)
        if hasattr(waveform, "shape") and waveform.__class__.__module__.startswith("torch"):
            import torch

            with torch.no_grad():
                chunks = [
                    embed_qim_watermark(seg, sample_rate, eff_payload)
                    for seg in _iter_chunks(waveform, sample_rate)
                ]
                return torch.cat(chunks, dim=-1) if chunks else waveform

        if hasattr(waveform, "shape"):
            import numpy as np

            chunks = [
                embed_qim_watermark(seg, sample_rate, eff_payload)
                for seg in _iter_chunks(waveform, sample_rate)
            ]
            return np.concatenate(chunks, axis=-1) if chunks else waveform

        return embed_qim_watermark(waveform, sample_rate, eff_payload)
    except WatermarkError:
        raise
    except Exception as exc:
        raise WatermarkError(f"Offline QIM watermark embedding failed: {exc}") from exc


def detect_watermark(
    waveform: Any,
    sample_rate: int,
) -> dict[str, Any]:
    """Detect whether `waveform` contains a valid `wispral-qim-v1` watermark."""
    if not _check_available():
        return {
            "is_watermarked": False,
            "confidence": 0.0,
            "scheme": SCHEME,
            "message_bits": "",
            "payload_hex": "",
            "payload_digest": "",
            "is_omnivoice": False,
            "error": "watermark_disabled",
        }

    try:
        inj_det = _get_detector()
        if inj_det is not None:
            audio = (
                waveform.unsqueeze(0)
                if waveform.dim() == 2
                else waveform.unsqueeze(0).unsqueeze(0)
                if waveform.dim() == 1
                else waveform
            )
            best_conf, decoded_msg = -1.0, None
            for seg in _iter_chunks(audio, sample_rate):
                res = inj_det.detect_watermark(seg, sample_rate=sample_rate, message_threshold=0.5)
                seg_conf = float(res[0]) if isinstance(res, tuple) else 0.0
                if seg_conf > best_conf:
                    best_conf = seg_conf
                    decoded_msg = res[1] if isinstance(res, tuple) and len(res) > 1 else None
            conf = max(best_conf, 0.0)
            msg_bits = ""
            is_omni = False
            if decoded_msg is not None:
                bits = decoded_msg.squeeze().tolist()
                if isinstance(bits, list):
                    msg_bits = "".join(str(int(b > 0.5)) for b in bits)
                    is_omni = [int(b > 0.5) for b in bits] == OMNI_MESSAGE
            return {
                "is_watermarked": conf > 0.5,
                "confidence": round(conf, 4),
                "scheme": SCHEME,
                "message_bits": msg_bits,
                "is_omnivoice": is_omni,
                "source": "WisprStudio" if is_omni else "unknown",
            }

        best_res: Optional[dict[str, Any]] = None
        for seg in _iter_chunks(waveform, sample_rate):
            res = extract_and_verify_watermark(seg, sample_rate)
            if best_res is None or (res["verified"] and not best_res["verified"]) or (
                res["verified"] == best_res["verified"] and res["confidence"] > best_res["confidence"]
            ):
                best_res = res

        if best_res is None:
            best_res = extract_and_verify_watermark(waveform, sample_rate)

        verified = bool(best_res["verified"])
        return {
            "is_watermarked": verified,
            "confidence": best_res["confidence"],
            "scheme": SCHEME,
            "message_bits": best_res["payload_bits"],
            "payload_hex": best_res["payload_hex"],
            "payload_digest": best_res["payload_digest"],
            "is_omnivoice": verified,
            "source": "WisprStudio" if verified else "unknown",
        }
    except Exception as exc:
        logger.warning("Watermark detection failed: %s", exc, exc_info=True)
        return {
            "is_watermarked": False,
            "confidence": 0.0,
            "scheme": SCHEME,
            "message_bits": "",
            "payload_hex": "",
            "payload_digest": "",
            "is_omnivoice": False,
            "error": str(exc),
        }


def generate_brand_tone(sample_rate: int = 24000, duration_s: float = 0.4):
    """Generate a short ascending three-note WisprStudio audio chime."""
    import torch

    notes_hz = [523.25, 659.25, 783.99]
    note_dur = duration_s / len(notes_hz)
    samples_per_note = int(note_dur * sample_rate)
    total_samples = samples_per_note * len(notes_hz)

    tone = torch.zeros(1, total_samples)
    t = torch.linspace(0, note_dur, samples_per_note)

    for idx, freq in enumerate(notes_hz):
        envelope = torch.exp(-t * 6.0) * 0.15
        wave = torch.sin(2 * math.pi * freq * t) * envelope
        start = idx * samples_per_note
        tone[0, start : start + samples_per_note] = wave

    fade_len = int(total_samples * 0.2)
    if fade_len > 0:
        tone[0, -fade_len:] *= torch.linspace(1.0, 0.0, fade_len)

    return tone


def apply_audio_brand(waveform: Any, sample_rate: int):
    """Prepend the WisprStudio brand tone to a waveform when enabled."""
    if not is_visible_audio_enabled():
        return waveform
    import torch

    brand = generate_brand_tone(sample_rate=sample_rate)
    gap = torch.zeros(1, int(0.1 * sample_rate))
    return torch.cat([brand, gap, waveform], dim=-1)


def get_ffmpeg_overlay_args(logo_path: str, duration_s: float = 5.0) -> list[str]:
    if not is_visible_video_enabled():
        return []
    _ = logo_path
    filter_str = (
        f"[1:v]scale=-1:64,format=rgba,"
        f"fade=t=out:st={duration_s - 1}:d=1:alpha=1[logo];"
        f"[0:v][logo]overlay=W-w-20:H-h-20:enable='lte(t,{duration_s})'"
    )
    return ["-filter_complex", filter_str]
