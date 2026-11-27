"""Pure-DSP offline audio watermarking (`wispral-qim-v1`).

Implements a deterministic, zero-network, zero-external-weights Quantization
Index Modulation (QIM) watermarker over orthonormal mid-frequency Type-II DCT
block projections. Works with `numpy` when available and falls back seamlessly
to pure-Python stdlib (`math`, `array`, `wave`, `struct`, `hashlib`). Never
imports `torch` at module import time.

Frame layout (176 bits total, embedded at 4 bits per ~4 ms block = 0.176 s/frame):
  - 32-bit sync header:  0x57535052 ("WSPR")
  - 128-bit payload:     16 bytes (e.g. export/consent digest prefix)
  - 16-bit integrity:    CRC-16-CCITT (poly=0x1021, init=0xFFFF) over payload
"""

from __future__ import annotations

import array
import hashlib
import io
import math
import struct
import wave
from pathlib import Path
from typing import Any, Sequence

try:
    import numpy as _np
except ImportError:  # pragma: no cover - pure-Python stdlib fallback
    _np = None  # type: ignore[assignment]

SCHEME = "wispral-qim-v1"
SYNC_HEADER_U32 = 0x57535052  # ASCII "WSPR"
SYNC_BITS = 32
PAYLOAD_BYTES = 16
PAYLOAD_BITS = PAYLOAD_BYTES * 8  # 128 bits
CRC_BITS = 16
FRAME_BITS = SYNC_BITS + PAYLOAD_BITS + CRC_BITS  # 176 bits

DEFAULT_KEY = b"wispral-qim-v1-default-key"
DEFAULT_PAYLOAD_BYTES = hashlib.sha256(
    b"wisprstudio:wispral-qim-v1:default"
).digest()[:PAYLOAD_BYTES]

# Four mutually orthonormal mid-band Type-II DCT bins (~1000..1375 Hz across all
# supported sample rates when block size tracks ~4 ms).
_CARRIER_BINS: tuple[int, int, int, int] = (8, 9, 10, 11)
_BITS_PER_BLOCK = len(_CARRIER_BINS)
_BLOCKS_PER_FRAME = FRAME_BITS // _BITS_PER_BLOCK  # 44 blocks (~176 ms)

# Reference step size at B=96 (24 kHz). Scaled by sqrt(B / 96) so per-sample
# watermark MSE = delta^2 / (3 * B) = ~2.17e-8 (-76.6 dBFS) is invariant across
# sample rates, yielding ~50-70 dB SNR on speech/tones (>=32 dB down to -44 dBFS)
# and >40 sigma decision margin above 16-bit PCM quantization noise.
_REF_BLOCK_SIZE = 96
_REF_DELTA = 0.0025

_BASIS_CACHE: dict[int, Any] = {}
_DITHER_CACHE: dict[bytes, tuple[float, ...]] = {}


def crc16_ccitt(data: bytes) -> int:
    """Compute deterministic CRC-16-CCITT (poly=0x1021, init=0xFFFF)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def payload_digest_sha256(payload: bytes) -> str:
    """Return `sha256:<64hex>` digest of the 128-bit watermark payload."""
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def normalize_payload(payload: bytes | str | Sequence[int] | None) -> bytes:
    """Coerce caller payload into an exact 16-byte (128-bit) buffer."""
    if payload is None:
        return DEFAULT_PAYLOAD_BYTES
    if isinstance(payload, bytes):
        if len(payload) == PAYLOAD_BYTES:
            return payload
        return hashlib.sha256(payload).digest()[:PAYLOAD_BYTES]
    if isinstance(payload, str):
        text = payload.strip()
        if len(text) == PAYLOAD_BYTES * 2:
            try:
                return bytes.fromhex(text)
            except ValueError:
                pass
        return hashlib.sha256(text.encode("utf-8")).digest()[:PAYLOAD_BYTES]
    bits = [int(bool(b)) for b in payload]
    if len(bits) == PAYLOAD_BITS:
        out = bytearray(PAYLOAD_BYTES)
        for idx, bit in enumerate(bits):
            if bit:
                out[idx >> 3] |= 1 << (7 - (idx & 7))
        return bytes(out)
    packed = bytes(int(bool(b)) for b in bits)
    return hashlib.sha256(packed).digest()[:PAYLOAD_BYTES]


def _int_to_bits(value: int, width: int) -> list[int]:
    return [(value >> (width - 1 - i)) & 1 for i in range(width)]


def _bytes_to_bits(data: bytes) -> list[int]:
    bits: list[int] = []
    for byte in data:
        for shift in range(7, -1, -1):
            bits.append((byte >> shift) & 1)
    return bits


def _bits_to_bytes(bits: Sequence[int]) -> bytes:
    out = bytearray((len(bits) + 7) // 8)
    for idx, bit in enumerate(bits):
        if bit:
            out[idx >> 3] |= 1 << (7 - (idx & 7))
    return bytes(out)


def _bits_to_uint(bits: Sequence[int]) -> int:
    val = 0
    for b in bits:
        val = (val << 1) | (1 if b else 0)
    return val


def build_frame_bits(payload: bytes) -> list[int]:
    """Assemble the 176-bit frame: 32-bit sync + 128-bit payload + 16-bit CRC."""
    if len(payload) != PAYLOAD_BYTES:
        raise ValueError(f"Expected {PAYLOAD_BYTES}-byte payload, got {len(payload)}")
    sync = _int_to_bits(SYNC_HEADER_U32, SYNC_BITS)
    body = _bytes_to_bits(payload)
    crc = _int_to_bits(crc16_ccitt(payload), CRC_BITS)
    return sync + body + crc


def block_size_for_rate(sample_rate: int) -> int:
    """Return an even ~4 ms block length (>= 32 samples) so carrier bins sit in ~1.0-1.4 kHz."""
    if sample_rate <= 0:
        raise ValueError(f"sample_rate must be positive, got {sample_rate}")
    half = max(16, int(round(sample_rate * 0.002)))
    return half * 2


def step_size_for_block(block_size: int) -> float:
    """QIM lattice step size scaled for constant per-sample MSE across sample rates."""
    return _REF_DELTA * math.sqrt(block_size / _REF_BLOCK_SIZE)


def _dither_table(key: bytes) -> tuple[float, ...]:
    """Deterministic pseudorandom dither in (-0.5, 0.5) per frame bit position."""
    cached = _DITHER_CACHE.get(key)
    if cached is not None:
        return cached
    values: list[float] = []
    counter = 0
    while len(values) < FRAME_BITS:
        digest = hashlib.sha256(key + struct.pack(">I", counter)).digest()
        counter += 1
        for offset in range(0, len(digest), 4):
            if len(values) >= FRAME_BITS:
                break
            u32 = struct.unpack(">I", digest[offset : offset + 4])[0]
            values.append((u32 / 4294967296.0) - 0.5)
    table = tuple(values)
    _DITHER_CACHE[key] = table
    return table


def _orthonormal_basis_py(block_size: int) -> tuple[tuple[float, ...], ...]:
    scale = math.sqrt(2.0 / block_size)
    denom = 2.0 * block_size
    rows: list[tuple[float, ...]] = []
    for k in _CARRIER_BINS:
        row = tuple(
            scale * math.cos(math.pi * (2 * n + 1) * k / denom)
            for n in range(block_size)
        )
        rows.append(row)
    return tuple(rows)


def _get_basis(block_size: int, use_numpy: bool):
    cache_key = block_size if use_numpy else -block_size
    cached = _BASIS_CACHE.get(cache_key)
    if cached is not None:
        return cached
    py_rows = _orthonormal_basis_py(block_size)
    if use_numpy and _np is not None:
        arr = _np.asarray(py_rows, dtype=_np.float64)  # shape (4, B)
        _BASIS_CACHE[cache_key] = arr
        return arr
    _BASIS_CACHE[cache_key] = py_rows
    return py_rows


def _is_torch_tensor(obj: Any) -> bool:
    cls = type(obj)
    return cls.__module__.startswith("torch") and hasattr(obj, "detach") and hasattr(obj, "shape")


def _embed_1d_py(
    mono: Sequence[float],
    sample_rate: int,
    frame_bits: list[int],
    key: bytes,
) -> list[float]:
    bsz = block_size_for_rate(sample_rate)
    n_samples = len(mono)
    n_blocks = n_samples // bsz
    if n_blocks == 0:
        return list(mono)

    delta = step_size_for_block(bsz)
    dithers = _dither_table(key)
    basis = _get_basis(bsz, use_numpy=False)

    peak = max((abs(float(x)) for x in mono), default=0.0)
    max_perturbation = 2.0 * delta * math.sqrt(2.0 / bsz)
    gain = 1.0
    if 0.0 < peak <= 1.0 and peak + max_perturbation > 0.9995:
        gain = (0.9995 - max_perturbation) / peak

    out = [float(x) * gain for x in mono]
    for blk in range(n_blocks):
        base = blk * bsz
        bit_base = (blk * _BITS_PER_BLOCK) % FRAME_BITS
        deltas_c = [0.0] * _BITS_PER_BLOCK
        for c_idx in range(_BITS_PER_BLOCK):
            row = basis[c_idx]
            proj = 0.0
            for i in range(bsz):
                proj += out[base + i] * row[i]
            bit_pos = (bit_base + c_idx) % FRAME_BITS
            bit_val = frame_bits[bit_pos]
            offset = dithers[bit_pos] * delta + (0.5 * delta if bit_val else 0.0)
            quantized = round((proj - offset) / delta) * delta + offset
            deltas_c[c_idx] = quantized - proj
        for i in range(bsz):
            acc = 0.0
            for c_idx in range(_BITS_PER_BLOCK):
                acc += deltas_c[c_idx] * basis[c_idx][i]
            out[base + i] += acc
    return out


def _embed_1d_np(
    mono: Any,
    sample_rate: int,
    frame_bits: list[int],
    key: bytes,
) -> Any:
    assert _np is not None
    bsz = block_size_for_rate(sample_rate)
    x = _np.asarray(mono, dtype=_np.float64)
    n_samples = x.shape[0]
    n_blocks = n_samples // bsz
    if n_blocks == 0:
        return x.copy()

    delta = step_size_for_block(bsz)
    dithers = _np.asarray(_dither_table(key), dtype=_np.float64)
    bits_arr = _np.asarray(frame_bits, dtype=_np.float64)
    basis = _get_basis(bsz, use_numpy=True)  # (4, B)

    peak = float(_np.max(_np.abs(x))) if n_samples else 0.0
    max_perturbation = 2.0 * delta * math.sqrt(2.0 / bsz)
    gain = 1.0
    if 0.0 < peak <= 1.0 and peak + max_perturbation > 0.9995:
        gain = (0.9995 - max_perturbation) / peak

    out = x * gain
    usable = n_blocks * bsz
    blocks = out[:usable].reshape(n_blocks, bsz)  # (N_blk, B)
    projs = blocks @ basis.T  # (N_blk, 4)

    bit_indices = (
        (_np.arange(n_blocks)[:, None] * _BITS_PER_BLOCK) + _np.arange(_BITS_PER_BLOCK)[None, :]
    ) % FRAME_BITS
    offsets = dithers[bit_indices] * delta + bits_arr[bit_indices] * (0.5 * delta)
    quantized = _np.round((projs - offsets) / delta) * delta + offsets
    diff = quantized - projs  # (N_blk, 4)
    updates = diff @ basis  # (N_blk, B)

    result = out.copy()
    result[:usable] = (blocks + updates).reshape(usable)
    return result


def embed_qim_watermark(
    samples: Any,
    sample_rate: int,
    payload: bytes | str | Sequence[int] | None = None,
    *,
    key: bytes = DEFAULT_KEY,
    force_pure_python: bool = False,
) -> Any:
    """Embed `wispral-qim-v1` watermark deterministically into `samples`.

    Preserves the exact container type and shape (`torch.Tensor`, `numpy.ndarray`,
    `array.array`, or `list[float]`). For multi-channel audio, applies the exact
    additive watermark residual derived from channel 0 across channels so stereo
    phase and downmix compatibility are preserved.
    """
    payload_bytes = normalize_payload(payload)
    frame_bits = build_frame_bits(payload_bytes)
    use_np = (_np is not None) and not force_pure_python

    if _is_torch_tensor(samples):
        import torch  # local import only when caller supplies a torch.Tensor

        orig_dtype = samples.dtype
        orig_device = samples.device
        orig_shape = tuple(samples.shape)
        if samples.numel() == 0:
            return samples
        arr = samples.detach().to(device="cpu", dtype=torch.float64).numpy()
        flat = arr.reshape(-1, orig_shape[-1])
        ch0 = flat[0]
        marked0 = _embed_1d_np(ch0, sample_rate, frame_bits, key) if use_np else _np.asarray(
            _embed_1d_py(ch0.tolist(), sample_rate, frame_bits, key), dtype=_np.float64
        )
        residual = marked0 - ch0
        out_flat = flat.copy()
        out_flat[0] = marked0
        if out_flat.shape[0] > 1:
            # Apply identical headroom + QIM residual to secondary channels
            peak = float(_np.max(_np.abs(ch0))) if ch0.size else 0.0
            bsz = block_size_for_rate(sample_rate)
            delta = step_size_for_block(bsz)
            max_pert = 2.0 * delta * math.sqrt(2.0 / bsz)
            gain = (
                (0.9995 - max_pert) / peak
                if (0.0 < peak <= 1.0 and peak + max_pert > 0.9995)
                else 1.0
            )
            ch0_residual_only = marked0 - (ch0 * gain)
            out_flat[1:] = flat[1:] * gain + ch0_residual_only[None, :]
        out_tensor = torch.from_numpy(out_flat.reshape(orig_shape)).to(
            device=orig_device, dtype=orig_dtype
        )
        return out_tensor

    if _np is not None and isinstance(samples, _np.ndarray):
        orig_dtype = samples.dtype
        orig_shape = samples.shape
        if samples.size == 0:
            return samples.copy()
        if samples.ndim == 1:
            marked = (
                _embed_1d_np(samples, sample_rate, frame_bits, key)
                if use_np
                else _np.asarray(
                    _embed_1d_py(samples.tolist(), sample_rate, frame_bits, key),
                    dtype=_np.float64,
                )
            )
            return marked.astype(orig_dtype, copy=False)
        flat = samples.astype(_np.float64, copy=True).reshape(-1, orig_shape[-1])
        ch0 = flat[0]
        marked0 = (
            _embed_1d_np(ch0, sample_rate, frame_bits, key)
            if use_np
            else _np.asarray(
                _embed_1d_py(ch0.tolist(), sample_rate, frame_bits, key), dtype=_np.float64
            )
        )
        peak = float(_np.max(_np.abs(ch0))) if ch0.size else 0.0
        bsz = block_size_for_rate(sample_rate)
        delta = step_size_for_block(bsz)
        max_pert = 2.0 * delta * math.sqrt(2.0 / bsz)
        gain = (
            (0.9995 - max_pert) / peak
            if (0.0 < peak <= 1.0 and peak + max_pert > 0.9995)
            else 1.0
        )
        residual_only = marked0 - (ch0 * gain)
        flat = flat * gain + residual_only[None, :]
        return flat.reshape(orig_shape).astype(orig_dtype, copy=False)

    if isinstance(samples, array.array):
        marked_list = _embed_1d_py(samples, sample_rate, frame_bits, key)
        return array.array(samples.typecode, marked_list)

    marked_py = _embed_1d_py(list(samples), sample_rate, frame_bits, key)
    return marked_py


def _extract_projections(
    samples: Any,
    sample_rate: int,
    *,
    force_pure_python: bool = False,
) -> tuple[list[list[float]], int, float]:
    """Return `(projections_per_block, block_size, delta)` from channel 0."""
    bsz = block_size_for_rate(sample_rate)
    delta = step_size_for_block(bsz)
    use_np = (_np is not None) and not force_pure_python

    if _is_torch_tensor(samples):
        arr = samples.detach().cpu().numpy()
        mono_np = arr.reshape(-1, arr.shape[-1])[0].astype("float64", copy=False) if arr.size else arr.reshape(-1)
        if use_np:
            n_blocks = int(mono_np.shape[0]) // bsz
            if n_blocks == 0:
                return [], bsz, delta
            basis = _get_basis(bsz, use_numpy=True)
            blocks = mono_np[: n_blocks * bsz].reshape(n_blocks, bsz)
            projs = (blocks @ basis.T).tolist()
            return projs, bsz, delta
        mono_seq: Sequence[float] = mono_np.tolist()
    elif _np is not None and isinstance(samples, _np.ndarray):
        if samples.size == 0:
            return [], bsz, delta
        mono_np = (
            samples.astype(_np.float64, copy=False)
            if samples.ndim == 1
            else samples.reshape(-1, samples.shape[-1])[0].astype(_np.float64, copy=False)
        )
        if use_np:
            n_blocks = int(mono_np.shape[0]) // bsz
            if n_blocks == 0:
                return [], bsz, delta
            basis = _get_basis(bsz, use_numpy=True)
            blocks = mono_np[: n_blocks * bsz].reshape(n_blocks, bsz)
            projs = (blocks @ basis.T).tolist()
            return projs, bsz, delta
        mono_seq = mono_np.tolist()
    else:
        mono_seq = list(samples)

    n_blocks = len(mono_seq) // bsz
    if n_blocks == 0:
        return [], bsz, delta
    basis_py = _get_basis(bsz, use_numpy=False)
    projs_py: list[list[float]] = []
    for blk in range(n_blocks):
        base = blk * bsz
        row_vals: list[float] = []
        for c_idx in range(_BITS_PER_BLOCK):
            row = basis_py[c_idx]
            proj = 0.0
            for i in range(bsz):
                proj += float(mono_seq[base + i]) * row[i]
            row_vals.append(proj)
        projs_py.append(row_vals)
    return projs_py, bsz, delta


def extract_and_verify_watermark(
    samples: Any,
    sample_rate: int,
    *,
    expected_payload: bytes | str | Sequence[int] | None = None,
    key: bytes = DEFAULT_KEY,
    strict_frames: bool = True,
    force_pure_python: bool = False,
) -> dict[str, Any]:
    """Deterministically extract and cryptographically/CRC verify `wispral-qim-v1`.

    Fail-closed guarantees:
      1. Requires at least one full 176-bit frame (44 blocks, ~176 ms).
      2. Soft-decision combines coset distances across repeated frames, verifies
         all 32 sync header bits AND exact CRC-16-CCITT over the 128-bit payload.
      3. Under `strict_frames=True` (default), verifies individual complete
         frames as well so spliced, zeroed, scaled, or partially overwritten
         audio fails closed (`tampered=True`, `verified=False`).
    """
    empty_result = {
        "verified": False,
        "is_watermarked": False,
        "scheme": SCHEME,
        "confidence": 0.0,
        "payload_bytes": b"",
        "payload_hex": "",
        "payload_bits": "",
        "payload_digest": "",
        "crc16_valid": False,
        "sync_bits_matched": 0,
        "frame_count": 0,
        "valid_frames": 0,
        "tampered": False,
    }

    if sample_rate <= 0:
        return {**empty_result, "error": "invalid_sample_rate"}

    projs, _bsz, delta = _extract_projections(
        samples, sample_rate, force_pure_python=force_pure_python
    )
    n_blocks = len(projs)
    if n_blocks < _BLOCKS_PER_FRAME:
        return {**empty_result, "error": "audio_too_short"}

    dithers = _dither_table(key)
    quarter_delta = 0.25 * delta
    sync_expected = _int_to_bits(SYNC_HEADER_U32, SYNC_BITS)

    # Soft metric per bit: positive => bit 1 closer; negative => bit 0 closer.
    soft_scores = [0.0] * FRAME_BITS
    norm_residuals = [0.0] * FRAME_BITS
    counts = [0] * FRAME_BITS

    n_full_frames = n_blocks // _BLOCKS_PER_FRAME
    frame_payloads: list[bytes] = []
    valid_frames = 0

    for frame_idx in range(n_full_frames):
        frame_bits: list[int] = []
        frame_res_sum = 0.0
        for blk_in_frame in range(_BLOCKS_PER_FRAME):
            blk = frame_idx * _BLOCKS_PER_FRAME + blk_in_frame
            row = projs[blk]
            for c_idx in range(_BITS_PER_BLOCK):
                bit_pos = blk_in_frame * _BITS_PER_BLOCK + c_idx
                c_val = row[c_idx]
                off0 = dithers[bit_pos] * delta
                off1 = off0 + 0.5 * delta
                d0 = abs(c_val - (round((c_val - off0) / delta) * delta + off0))
                d1 = abs(c_val - (round((c_val - off1) / delta) * delta + off1))
                score = (d0 - d1) / quarter_delta  # +1 for ideal bit 1, -1 for ideal bit 0
                soft_scores[bit_pos] += score
                min_d = d1 if d1 < d0 else d0
                norm_res = min_d / quarter_delta  # 0.0 on lattice, ~0.5 random
                norm_residuals[bit_pos] += norm_res
                counts[bit_pos] += 1
                frame_bits.append(1 if d1 < d0 else 0)
                frame_res_sum += norm_res

        f_sync = sum(
            1 for a, b in zip(frame_bits[:SYNC_BITS], sync_expected) if a == b
        )
        f_payload = _bits_to_bytes(frame_bits[SYNC_BITS : SYNC_BITS + PAYLOAD_BITS])
        f_crc = _bits_to_uint(frame_bits[SYNC_BITS + PAYLOAD_BITS :])
        f_mean_res = frame_res_sum / FRAME_BITS
        if f_sync >= 30 and crc16_ccitt(f_payload) == f_crc and f_mean_res < 0.45:
            valid_frames += 1
            frame_payloads.append(f_payload)

    # Include trailing partial frame blocks into combined soft decision as well
    for blk in range(n_full_frames * _BLOCKS_PER_FRAME, n_blocks):
        row = projs[blk]
        bit_base = (blk * _BITS_PER_BLOCK) % FRAME_BITS
        for c_idx in range(_BITS_PER_BLOCK):
            bit_pos = (bit_base + c_idx) % FRAME_BITS
            c_val = row[c_idx]
            off0 = dithers[bit_pos] * delta
            off1 = off0 + 0.5 * delta
            d0 = abs(c_val - (round((c_val - off0) / delta) * delta + off0))
            d1 = abs(c_val - (round((c_val - off1) / delta) * delta + off1))
            soft_scores[bit_pos] += (d0 - d1) / quarter_delta
            norm_residuals[bit_pos] += (d1 if d1 < d0 else d0) / quarter_delta
            counts[bit_pos] += 1

    combined_bits = [1 if soft_scores[i] > 0.0 else 0 for i in range(FRAME_BITS)]
    sync_matched = sum(
        1 for a, b in zip(combined_bits[:SYNC_BITS], sync_expected) if a == b
    )
    payload_bytes = _bits_to_bytes(combined_bits[SYNC_BITS : SYNC_BITS + PAYLOAD_BITS])
    extracted_crc = _bits_to_uint(combined_bits[SYNC_BITS + PAYLOAD_BITS :])
    crc_valid = crc16_ccitt(payload_bytes) == extracted_crc

    mean_norm_res = sum(norm_residuals[i] / max(1, counts[i]) for i in range(FRAME_BITS)) / FRAME_BITS
    lattice_conf = max(0.0, min(1.0, 1.0 - mean_norm_res))
    sync_ratio = sync_matched / SYNC_BITS

    distinct_payloads = set(frame_payloads)
    frame_ratio = valid_frames / max(1, n_full_frames)
    tampered = False
    if strict_frames:
        if len(distinct_payloads) > 1:
            tampered = True
        elif valid_frames > 0 and frame_ratio < 0.85:
            tampered = True
        elif sync_matched == SYNC_BITS and crc_valid and valid_frames == 0:
            tampered = True

    verified = (
        sync_matched == SYNC_BITS
        and crc_valid
        and mean_norm_res < 0.45
        and valid_frames >= 1
        and not tampered
    )

    if verified and expected_payload is not None:
        wanted = normalize_payload(expected_payload)
        if payload_bytes != wanted:
            verified = False
            tampered = True

    confidence = round(lattice_conf * sync_ratio, 4) if verified else round(max(0.0, sync_ratio - 0.5), 4)
    if not verified:
        return {
            **empty_result,
            "confidence": confidence,
            "crc16_valid": crc_valid,
            "sync_bits_matched": sync_matched,
            "frame_count": n_full_frames,
            "valid_frames": valid_frames,
            "tampered": tampered,
        }

    payload_bits_str = "".join(
        str(b) for b in combined_bits[SYNC_BITS : SYNC_BITS + PAYLOAD_BITS]
    )
    return {
        "verified": True,
        "is_watermarked": True,
        "scheme": SCHEME,
        "confidence": max(0.51, confidence),
        "payload_bytes": payload_bytes,
        "payload_hex": payload_bytes.hex(),
        "payload_bits": payload_bits_str,
        "payload_digest": payload_digest_sha256(payload_bytes),
        "crc16_valid": True,
        "sync_bits_matched": sync_matched,
        "frame_count": n_full_frames,
        "valid_frames": valid_frames,
        "tampered": False,
    }


def compute_snr_db(reference: Any, watermarked: Any) -> float:
    """Compute Signal-to-Noise Ratio (dB) of `watermarked` relative to `reference`."""
    if _is_torch_tensor(reference):
        ref_list = reference.detach().cpu().flatten().tolist()
        wm_list = watermarked.detach().cpu().flatten().tolist()
    elif _np is not None and isinstance(reference, _np.ndarray):
        ref_arr = reference.astype(_np.float64, copy=False).ravel()
        wm_arr = _np.asarray(watermarked, dtype=_np.float64).ravel()
        sig_power = float(_np.mean(ref_arr * ref_arr))
        noise_power = float(_np.mean((wm_arr - ref_arr) ** 2))
        if noise_power <= 0.0:
            return float("inf")
        if sig_power <= 0.0:
            return -float("inf")
        return 10.0 * math.log10(sig_power / noise_power)
    else:
        ref_list = [float(x) for x in reference]
        wm_list = [float(x) for x in watermarked]

    if not ref_list:
        return float("inf")
    sig_power = sum(x * x for x in ref_list) / len(ref_list)
    noise_power = sum((y - x) ** 2 for x, y in zip(ref_list, wm_list)) / len(ref_list)
    if noise_power <= 0.0:
        return float("inf")
    if sig_power <= 0.0:
        return -float("inf")
    return 10.0 * math.log10(sig_power / noise_power)


def write_pcm16_wav(path: str | Path, samples: Sequence[float] | Any, sample_rate: int) -> None:
    """Write mono or multi-channel float [-1, 1] samples to a 16-bit PCM WAV file using stdlib `wave`."""
    if _is_torch_tensor(samples):
        arr = samples.detach().cpu().numpy()
    elif _np is not None and isinstance(samples, _np.ndarray):
        arr = samples
    else:
        arr = None

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(p), "wb") as wf:
        if arr is not None:
            if arr.ndim == 1:
                channels = 1
                interleaved = arr
            else:
                flat = arr.reshape(-1, arr.shape[-1])
                channels = int(flat.shape[0])
                interleaved = flat.T.reshape(-1)
            clipped = _np.clip(_np.round(interleaved * 32767.0), -32768, 32767).astype("<i2")
            wf.setnchannels(channels)
            wf.setsampwidth(2)
            wf.setframerate(int(sample_rate))
            wf.writeframes(clipped.tobytes())
        else:
            pcm = array.array(
                "h",
                (max(-32768, min(32767, int(round(float(x) * 32767.0)))) for x in samples),
            )
            if pcm.itemsize != 2:  # pragma: no cover
                raise RuntimeError("Unexpected array('h') itemsize")
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(int(sample_rate))
            wf.writeframes(pcm.tobytes())


def read_pcm16_wav(path_or_bytes: str | Path | bytes) -> tuple[Any, int, int]:
    """Read a 16-bit PCM WAV file or bytes into float64 samples `[-1, 1]`, `(samples, sr, channels)`."""
    src: Any = io.BytesIO(path_or_bytes) if isinstance(path_or_bytes, bytes) else str(path_or_bytes)
    with wave.open(src, "rb") as wf:
        channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        sr = wf.getframerate()
        nframes = wf.getnframes()
        raw = wf.readframes(nframes)

    if sampwidth != 2:
        raise ValueError(f"Only 16-bit PCM WAV supported by stdlib reader, got sampwidth={sampwidth}")

    if _np is not None:
        ints = _np.frombuffer(raw, dtype="<i2").astype(_np.float64) / 32767.0
        if channels > 1:
            return ints.reshape(-1, channels).T, sr, channels
        return ints, sr, 1

    pcm = array.array("h")
    pcm.frombytes(raw)
    floats = [x / 32767.0 for x in pcm]
    if channels > 1:
        floats = floats[0::channels]
    return floats, sr, channels
