"""Local pt-BR transcription adapter backed by faster-whisper."""

import asyncio
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from typing import Protocol, cast

from carevoice.transcribe.base import AudioFormat, TranscriptionResult


class WhisperSegment(Protocol):
    text: str


class WhisperInfo(Protocol):
    language: str


class WhisperModel(Protocol):
    def transcribe(
        self,
        audio: str,
        *,
        language: str,
        initial_prompt: str | None = None,
    ) -> tuple[Iterable[WhisperSegment], WhisperInfo]: ...


class WhisperModelFactory(Protocol):
    def __call__(
        self,
        model_size: str,
        *,
        device: str,
        compute_type: str,
    ) -> WhisperModel: ...


@dataclass(frozen=True)
class _TranscriptionOptions:
    model_size: str
    device: str
    compute_type: str


class FasterWhisperTranscriber:
    """Runs CPU-friendly local transcription off the event loop."""

    def __init__(
        self,
        model_size: str = "medium",
        *,
        device: str = "cpu",
        compute_type: str = "int8",
        model_factory: WhisperModelFactory | None = None,
    ) -> None:
        if not model_size.strip():
            raise ValueError("Whisper model size cannot be empty")
        if not device.strip() or not compute_type.strip():
            raise ValueError("Whisper device and compute type cannot be empty")
        self._options = _TranscriptionOptions(model_size, device, compute_type)
        self._model_factory = model_factory
        self._model: WhisperModel | None = None
        self._model_lock = Lock()
        self._inference_lock = Lock()

    async def transcribe(
        self,
        payload: bytes,
        audio_format: AudioFormat,
        glossary_terms: Sequence[str] = (),
    ) -> TranscriptionResult:
        if not payload:
            raise ValueError("Audio payload cannot be empty")
        if audio_format not in {"ogg", "mp3", "m4a", "wav"}:
            raise ValueError("Unsupported audio format")
        return await asyncio.to_thread(
            self._transcribe_sync,
            payload,
            audio_format,
            glossary_terms,
        )

    def _transcribe_sync(
        self,
        payload: bytes,
        audio_format: AudioFormat,
        glossary_terms: Sequence[str],
    ) -> TranscriptionResult:
        with TemporaryDirectory(prefix="carevoice-audio-") as directory:
            audio_path = Path(directory) / f"input.{audio_format}"
            audio_path.write_bytes(payload)
            with self._inference_lock:
                segments, info = self._get_model().transcribe(
                    str(audio_path),
                    language="pt",
                    initial_prompt=_glossary_prompt(glossary_terms),
                )
                text = "".join(segment.text for segment in segments).strip()
            return TranscriptionResult(text=text, language=info.language)

    def _get_model(self) -> WhisperModel:
        if self._model is not None:
            return self._model
        with self._model_lock:
            if self._model is None:
                factory = self._model_factory or _load_model_factory()
                self._model = factory(
                    self._options.model_size,
                    device=self._options.device,
                    compute_type=self._options.compute_type,
                )
        return self._model


def _load_model_factory() -> WhisperModelFactory:
    try:
        module = import_module("faster_whisper")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Install the local transcription extra with `pip install -e \".[audio]\"`"
        ) from exc
    return cast(WhisperModelFactory, module.WhisperModel)


def _glossary_prompt(terms: Sequence[str]) -> str | None:
    normalized = [term.strip()[:80] for term in terms if term.strip()][:20]
    if not normalized:
        return None
    return "Vocabulário clínico: " + ", ".join(normalized)
