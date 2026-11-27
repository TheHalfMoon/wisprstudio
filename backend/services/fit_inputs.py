"""Deterministic input validation guard for Smart Fit dubbing (`fit_planner`).

Validates segment timelines, natural TTS durations, total media duration, and
`FitParams` bounds before planning. Explicitly permits overlapping multi-speaker
dubbing segments (resolved onto a shared piecewise timeline by `plan_fit`),
while rejecting NaN/Inf, negative timestamps, zero/inverted/sub-microsecond
slots, out-of-range media bounds, duplicate/blank segment IDs, and invalid
tempo/stretch parameters.

Pure Python stdlib — zero `torch` or I/O dependencies.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from services.fit_planner import FitParams

MIN_SEGMENT_SLOT_S = 1e-6
TOTAL_DURATION_TOLERANCE_S = 1e-3


class FitInputValidationError(ValueError):
    """Deterministic validation error raised for malformed Smart Fit inputs."""

    def __init__(self, message: str, *, code: str, index: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.index = index


@dataclass(frozen=True)
class ValidatedFitInputs:
    """Normalized, validated inputs ready for `fit_planner.plan_fit`."""

    segments: list[dict[str, Any]]
    natural_durs_s: list[float]
    total_dur_s: float
    params: "FitParams"
    has_overlapping_segments: bool = False


def _is_real_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_fit_params(params: Any) -> "FitParams":
    from services.fit_planner import FitParams

    if params is None:
        return FitParams()
    if not isinstance(params, FitParams):
        raise FitInputValidationError(
            f"params must be a FitParams instance or None, got {type(params).__name__}",
            code="invalid_fit_params",
        )
    if not isinstance(params.allow_video_retime, bool):
        raise FitInputValidationError(
            "params.allow_video_retime must be a bool",
            code="invalid_fit_params",
        )
    numeric_fields = (
        ("min_audio_rate", params.min_audio_rate),
        ("max_audio_only_rate", params.max_audio_only_rate),
        ("audio_rate_cap", params.audio_rate_cap),
        ("video_slow_cap", params.video_slow_cap),
        ("gap_guard_s", params.gap_guard_s),
    )
    for field_name, val in numeric_fields:
        if not _is_real_number(val) or not math.isfinite(float(val)):
            raise FitInputValidationError(
                f"params.{field_name} must be a finite float, got {val!r}",
                code="invalid_fit_params",
            )

    if float(params.min_audio_rate) <= 0.0 or float(params.min_audio_rate) > 1.0:
        raise FitInputValidationError(
            f"params.min_audio_rate must be in (0.0, 1.0], got {params.min_audio_rate!r}",
            code="invalid_fit_params",
        )
    if float(params.max_audio_only_rate) < 1.0:
        raise FitInputValidationError(
            f"params.max_audio_only_rate must be >= 1.0, got {params.max_audio_only_rate!r}",
            code="invalid_fit_params",
        )
    if float(params.audio_rate_cap) < float(params.max_audio_only_rate):
        raise FitInputValidationError(
            f"params.audio_rate_cap ({params.audio_rate_cap}) must be >= max_audio_only_rate ({params.max_audio_only_rate})",
            code="invalid_fit_params",
        )
    if float(params.video_slow_cap) < 1.0:
        raise FitInputValidationError(
            f"params.video_slow_cap must be >= 1.0, got {params.video_slow_cap!r}",
            code="invalid_fit_params",
        )
    if float(params.gap_guard_s) < 0.0:
        raise FitInputValidationError(
            f"params.gap_guard_s must be >= 0.0, got {params.gap_guard_s!r}",
            code="invalid_fit_params",
        )
    return params


def validate_fit_inputs(
    segments: Any,
    natural_durs_s: Any,
    total_dur_s: Any,
    params: "FitParams | None" = None,
    *,
    allow_empty: bool = False,
    allow_zero_total_dur: bool = False,
) -> ValidatedFitInputs:
    """Validate Smart Fit inputs across all 21 deterministic guard conditions.

    Overlapping multi-speaker dubbing segments (`seg_b["start"] < seg_a["end"]`)
    are explicitly permitted and flagged via `has_overlapping_segments=True`.
    """
    if segments is None or not isinstance(segments, (list, tuple)):
        raise FitInputValidationError(
            "segments must be a list or tuple of segment dicts",
            code="segments_not_sequence",
        )
    if natural_durs_s is None or not isinstance(natural_durs_s, (list, tuple)):
        raise FitInputValidationError(
            "natural_durs_s must be a list or tuple of finite non-negative durations",
            code="natural_durs_not_sequence",
        )
    if len(segments) != len(natural_durs_s):
        raise FitInputValidationError(
            f"segments ({len(segments)}) and natural_durs_s ({len(natural_durs_s)}) must be parallel",
            code="length_mismatch",
        )
    if len(segments) == 0 and not allow_empty:
        raise FitInputValidationError(
            "segments must contain at least one dubbing segment",
            code="segments_empty",
        )

    if not _is_real_number(total_dur_s):
        raise FitInputValidationError(
            f"total_dur_s must be a finite number, got {total_dur_s!r}",
            code="total_dur_non_numeric",
        )
    total_f = float(total_dur_s)
    if not math.isfinite(total_f):
        raise FitInputValidationError(
            f"total_dur_s must be finite, got {total_dur_s!r}",
            code="total_dur_non_finite",
        )
    if allow_zero_total_dur:
        if total_f < 0.0:
            raise FitInputValidationError(
                f"total_dur_s must be >= 0.0, got {total_f}",
                code="total_dur_negative",
            )
    elif total_f <= 0.0:
        raise FitInputValidationError(
            f"total_dur_s must be > 0.0, got {total_f}",
            code="total_dur_non_positive",
        )

    checked_params = _validate_fit_params(params)

    normalized_segments: list[dict[str, Any]] = []
    normalized_naturals: list[float] = []
    seen_ids: set[str] = set()
    max_end_seen = float("-inf")
    has_overlap = False

    for idx, (seg, nat_raw) in enumerate(zip(segments, natural_durs_s)):
        if not isinstance(seg, dict):
            raise FitInputValidationError(
                f"segment[{idx}] must be a dict, got {type(seg).__name__}",
                code="segment_not_mapping",
                index=idx,
            )
        if "start" not in seg or "end" not in seg:
            raise FitInputValidationError(
                f"segment[{idx}] must contain 'start' and 'end' keys",
                code="segment_missing_bounds",
                index=idx,
            )
        raw_start = seg["start"]
        raw_end = seg["end"]
        if not _is_real_number(raw_start) or not _is_real_number(raw_end):
            raise FitInputValidationError(
                f"segment[{idx}] start/end must be numeric, got ({raw_start!r}, {raw_end!r})",
                code="segment_non_numeric_bounds",
                index=idx,
            )
        start = float(raw_start)
        end = float(raw_end)
        if not math.isfinite(start) or not math.isfinite(end):
            raise FitInputValidationError(
                f"segment[{idx}] start/end must be finite, got ({start}, {end})",
                code="segment_non_finite_bounds",
                index=idx,
            )
        if start < 0.0:
            raise FitInputValidationError(
                f"segment[{idx}] start must be >= 0.0, got {start}",
                code="segment_negative_start",
                index=idx,
            )
        if start == end:
            raise FitInputValidationError(
                f"segment[{idx}] has zero duration (start == end == {start})",
                code="segment_zero_duration",
                index=idx,
            )
        if start > end:
            raise FitInputValidationError(
                f"segment[{idx}] has inverted bounds (start={start} > end={end})",
                code="segment_inverted_bounds",
                index=idx,
            )
        if (end - start) < MIN_SEGMENT_SLOT_S:
            raise FitInputValidationError(
                f"segment[{idx}] duration ({end - start:.3e}s) is below {MIN_SEGMENT_SLOT_S:.1e}s minimum",
                code="segment_degenerate_slot",
                index=idx,
            )
        if total_f > 0.0 and end > total_f + TOTAL_DURATION_TOLERANCE_S:
            raise FitInputValidationError(
                f"segment[{idx}] end ({end}) exceeds total_dur_s ({total_f})",
                code="segment_exceeds_total_duration",
                index=idx,
            )

        if "id" in seg and seg["id"] is not None:
            seg_id = str(seg["id"]).strip()
            if not seg_id:
                raise FitInputValidationError(
                    f"segment[{idx}] id must not be empty when provided",
                    code="segment_empty_id",
                    index=idx,
                )
            if seg_id in seen_ids:
                raise FitInputValidationError(
                    f"segment[{idx}] has duplicate id {seg_id!r}",
                    code="segment_duplicate_id",
                    index=idx,
                )
            seen_ids.add(seg_id)
        else:
            seg_id = f"seg_{idx}"

        if not _is_real_number(nat_raw):
            raise FitInputValidationError(
                f"natural_durs_s[{idx}] must be numeric, got {nat_raw!r}",
                code="natural_dur_non_numeric",
                index=idx,
            )
        nat = float(nat_raw)
        if not math.isfinite(nat):
            raise FitInputValidationError(
                f"natural_durs_s[{idx}] must be finite, got {nat}",
                code="natural_dur_non_finite",
                index=idx,
            )
        if nat < 0.0:
            raise FitInputValidationError(
                f"natural_durs_s[{idx}] must be >= 0.0, got {nat}",
                code="natural_dur_negative",
                index=idx,
            )

        # Overlapping multi-speaker dubbing segments are explicitly allowed!
        if start < max_end_seen - 1e-9:
            has_overlap = True
        if end > max_end_seen:
            max_end_seen = end

        norm_seg = dict(seg)
        norm_seg["id"] = seg_id
        norm_seg["start"] = start
        norm_seg["end"] = end
        normalized_segments.append(norm_seg)
        normalized_naturals.append(nat)

    return ValidatedFitInputs(
        segments=normalized_segments,
        natural_durs_s=normalized_naturals,
        total_dur_s=total_f,
        params=checked_params,
        has_overlapping_segments=has_overlap,
    )
