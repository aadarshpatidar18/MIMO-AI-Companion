"""The voice interfaces every engine implements, and the null engines used when none can run.

Nothing here imports a model library. That is deliberate: `import backend.core.voice` must work on
a machine with no voice packages installed, so the backend never fails to start because a
capability is missing — it fails on the *request* for that capability, with a message that says how
to install it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional, Protocol, Union

AudioInput = Union[bytes, str]


class VoiceUnavailable(RuntimeError):
    """Raised when the requested voice capability cannot run here. The message is for the user."""


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Transcript:
    text: str
    language: Optional[str] = None
    duration_s: float = 0.0
    segments: tuple[Segment, ...] = ()
    engine: str = ""
    inference_ms: float = 0.0

    @property
    def real_time_factor(self) -> Optional[float]:
        """Inference time divided by audio time: below 1.0 means faster than real time."""
        if self.duration_s <= 0 or self.inference_ms <= 0:
            return None
        return round((self.inference_ms / 1000.0) / self.duration_s, 3)


@dataclass(frozen=True)
class AudioChunk:
    audio: bytes
    sample_rate: int
    format: str = "wav"

    def __len__(self) -> int:
        return len(self.audio)


class STTEngine(Protocol):
    name: str

    def is_available(self) -> bool: ...

    def transcribe(self, audio: AudioInput, language: Optional[str] = None,
                   vad: bool = True) -> Transcript: ...


class TTSEngine(Protocol):
    name: str

    def is_available(self) -> bool: ...

    def synthesize(self, text: str, speed: float = 1.0) -> AudioChunk: ...

    def stream(self, text: str, speed: float = 1.0) -> Iterable[AudioChunk]: ...


class NullSTT:
    """Refuses, but explains itself. Used when faster-whisper is not installed."""

    name = "unavailable"

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def is_available(self) -> bool:
        return False

    def transcribe(self, audio: AudioInput, language: Optional[str] = None,
                   vad: bool = True) -> Transcript:
        raise VoiceUnavailable(self.reason)


class NullTTS:
    name = "unavailable"

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def is_available(self) -> bool:
        return False

    def synthesize(self, text: str, speed: float = 1.0) -> AudioChunk:
        raise VoiceUnavailable(self.reason)

    def stream(self, text: str, speed: float = 1.0) -> Iterable[AudioChunk]:
        raise VoiceUnavailable(self.reason)


def split_sentences(text: str, max_chars: int = 240) -> list[str]:
    """Split into speakable chunks at sentence ends, then at commas, then hard-wrap.

    Kokoro synthesises per chunk; short chunks mean the first sound starts sooner and a barge-in
    only throws away a fraction of a second of generated audio.
    """
    clean = " ".join(text.split())
    if not clean:
        return []
    pieces: list[str] = []
    buffer = ""
    for character in clean:
        buffer += character
        if character in ".!?…" and len(buffer) > 1:
            pieces.append(buffer.strip())
            buffer = ""
        elif len(buffer) >= max_chars:
            cut = max(buffer.rfind(", "), buffer.rfind("; "), buffer.rfind(": "))
            if cut > max_chars // 2:
                pieces.append(buffer[: cut + 1].strip())
                buffer = buffer[cut + 1:]
            else:
                pieces.append(buffer.strip())
                buffer = ""
    if buffer.strip():
        pieces.append(buffer.strip())
    return [piece for piece in pieces if piece]
