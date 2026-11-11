import math

import pytest

from carevoice.audio.limits import AudioValidationError, validate_audio_upload


@pytest.mark.parametrize(
    ("filename", "content_type", "audio_format"),
    [
        ("voice.ogg", "audio/ogg", "ogg"),
        ("voice.mp3", "audio/mpeg", "mp3"),
        ("voice.m4a", "audio/mp4", "m4a"),
        ("voice.wav", "audio/wav", "wav"),
    ],
)
def test_accepts_supported_audio_formats(
    filename: str,
    content_type: str,
    audio_format: str,
) -> None:
    audio = validate_audio_upload(
        filename,
        b"audio bytes",
        60,
        content_type=content_type,
    )

    assert audio.format == audio_format
    assert audio.payload == b"audio bytes"
    assert audio.duration_seconds == 60


@pytest.mark.parametrize(
    ("filename", "payload", "duration", "content_type", "message"),
    [
        ("voice.txt", b"audio", 10, None, "Unsupported audio format"),
        ("voice.ogg", b"audio", 10, "audio/mpeg", "does not match"),
        ("voice.mp3", b"", 10, None, "empty"),
        ("voice.wav", b"audio", 10, None, "exceeds the 4-byte"),
        ("voice.m4a", b"aud", 301, None, "300-second"),
        ("voice.mp3", b"aud", math.nan, None, "positive finite"),
        ("voice.mp3", b"aud", 0, None, "positive finite"),
    ],
)
def test_rejects_invalid_audio_uploads(
    filename: str,
    payload: bytes,
    duration: float,
    content_type: str | None,
    message: str,
) -> None:
    with pytest.raises(AudioValidationError, match=message):
        validate_audio_upload(
            filename,
            payload,
            duration,
            max_bytes=4,
            content_type=content_type,
        )
