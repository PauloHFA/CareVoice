import asyncio
from dataclasses import dataclass
from pathlib import Path

import pytest

from carevoice.transcribe.local_whisper import FasterWhisperTranscriber


@dataclass(frozen=True)
class _Info:
    language: str


@dataclass(frozen=True)
class _Segment:
    text: str


class _Model:
    def __init__(self) -> None:
        self.payload: bytes | None = None
        self.prompt: str | None = None
        self.language: str | None = None
        self.path: Path | None = None

    def transcribe(
        self,
        audio: str,
        *,
        language: str,
        initial_prompt: str | None = None,
    ) -> tuple[list[_Segment], _Info]:
        self.path = Path(audio)
        self.payload = self.path.read_bytes()
        self.prompt = initial_prompt
        self.language = language
        return [_Segment(" relato fiel "), _Segment("em português. ")], _Info("pt")


def test_local_transcriber_uses_glossary_and_cleans_temporary_audio() -> None:
    model = _Model()
    model_instances: list[_Model] = []

    def factory(
        model_size: str,
        *,
        device: str,
        compute_type: str,
    ) -> _Model:
        assert model_size == "small"
        assert device == "cpu"
        assert compute_type == "int8"
        model_instances.append(model)
        return model

    transcriber = FasterWhisperTranscriber("small", model_factory=factory)
    result = asyncio.run(
        transcriber.transcribe(
            b"fictitious audio",
            "ogg",
            ["pareamento", " tolerância "],
        )
    )

    assert result.text == "relato fiel em português."
    assert result.language == "pt"
    assert model.payload == b"fictitious audio"
    assert model.prompt == "Vocabulário clínico: pareamento, tolerância"
    assert model.language == "pt"
    assert model.path is not None
    assert not model.path.exists()
    assert len(model_instances) == 1


def test_local_transcriber_reuses_loaded_model() -> None:
    model = _Model()
    calls = 0

    def factory(
        model_size: str,
        *,
        device: str,
        compute_type: str,
    ) -> _Model:
        nonlocal calls
        assert model_size == "medium"
        assert device == "cpu"
        assert compute_type == "int8"
        calls += 1
        return model

    transcriber = FasterWhisperTranscriber(model_factory=factory)
    asyncio.run(transcriber.transcribe(b"first", "wav"))
    asyncio.run(transcriber.transcribe(b"second", "wav"))

    assert calls == 1
    assert model.prompt is None


def test_local_transcriber_rejects_empty_audio() -> None:
    def factory(model_size: str, *, device: str, compute_type: str) -> _Model:
        del model_size, device, compute_type
        return _Model()

    transcriber = FasterWhisperTranscriber(model_factory=factory)

    with pytest.raises(ValueError, match="cannot be empty"):
        asyncio.run(transcriber.transcribe(b"", "mp3"))


def test_local_transcriber_rejects_unsupported_format() -> None:
    def factory(model_size: str, *, device: str, compute_type: str) -> _Model:
        del model_size, device, compute_type
        return _Model()

    transcriber = FasterWhisperTranscriber(model_factory=factory)

    with pytest.raises(ValueError, match="Unsupported audio format"):
        asyncio.run(transcriber.transcribe(b"audio", "flac"))  # type: ignore[arg-type]
