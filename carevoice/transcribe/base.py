"""Provider-independent transcription contract."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

AudioFormat = Literal["ogg", "mp3", "m4a", "wav"]


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    language: str


class Transcriber(Protocol):
    async def transcribe(
        self,
        payload: bytes,
        audio_format: AudioFormat,
        glossary_terms: Sequence[str] = (),
    ) -> TranscriptionResult: ...
