"""Validation for supported audio uploads."""

import math
from dataclasses import dataclass
from pathlib import PurePath


class AudioValidationError(ValueError):
    """Raised when an audio upload exceeds limits or uses an unsupported format."""


@dataclass(frozen=True)
class ValidatedAudio:
    payload: bytes
    format: str
    duration_seconds: float


_MIME_TYPES: dict[str, frozenset[str]] = {
    ".ogg": frozenset({"audio/ogg", "audio/opus", "application/ogg"}),
    ".mp3": frozenset({"audio/mpeg", "audio/mp3"}),
    ".m4a": frozenset({"audio/mp4", "audio/x-m4a"}),
    ".wav": frozenset({"audio/wav", "audio/x-wav", "audio/wave"}),
}


def validate_audio_upload(
    filename: str,
    payload: bytes,
    duration_seconds: float,
    *,
    max_bytes: int = 20 * 1024 * 1024,
    max_duration_seconds: int = 300,
    content_type: str | None = None,
) -> ValidatedAudio:
    """Validate metadata and size before persisting or scheduling an audio upload."""
    suffix = PurePath(filename).suffix.casefold()
    if suffix not in _MIME_TYPES:
        raise AudioValidationError("Unsupported audio format")
    if content_type is not None and content_type.casefold() not in _MIME_TYPES[suffix]:
        raise AudioValidationError("Audio media type does not match its file extension")
    if not payload:
        raise AudioValidationError("Audio file is empty")
    if len(payload) > max_bytes:
        raise AudioValidationError(f"Audio exceeds the {max_bytes}-byte limit")
    if not math.isfinite(duration_seconds) or duration_seconds <= 0:
        raise AudioValidationError("Audio duration must be a positive finite number")
    if duration_seconds > max_duration_seconds:
        raise AudioValidationError(
            f"Audio exceeds the {max_duration_seconds}-second duration limit"
        )
    return ValidatedAudio(payload=payload, format=suffix[1:], duration_seconds=duration_seconds)
