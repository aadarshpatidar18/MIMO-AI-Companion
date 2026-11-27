"""The opt-in cloud path.

There is no vendor hard-wired here on purpose: the product decision was "local by default", and a
cloud fallback is only acceptable if the user turned it on *and* supplied a key. Any implementation
registers itself; without one, requesting cloud voice raises a [VoiceUnavailable] that says why.
"""
from __future__ import annotations

import os
from typing import Callable, Iterable, Optional

from .base import AudioChunk, AudioInput, Transcript, VoiceUnavailable

# A provider is a pair of callables, so this module needs no SDK dependency of its own.
STTHandler = Callable[[bytes, Optional[str]], dict]
TTSHandler = Callable[[str, float], bytes]

_handlers: dict[str, tuple[Optional[STTHandler], Optional[TTSHandler]]] = {}


def register(name: str, stt: Optional[STTHandler], tts: Optional[TTSHandler]) -> None:
    _handlers[name] = (stt, tts)


def clear() -> None:
    _handlers.clear()


class CloudSTT:
    name = "cloud"

    def __init__(self, provider: str = "default", api_key_env: str = "MIMO_CLOUD_STT_KEY",
                 allow_cloud: bool = False) -> None:
        self.provider = provider
        self.api_key_env = api_key_env
        self.allow_cloud = allow_cloud

    def is_available(self) -> bool:
        return bool(os.environ.get(self.api_key_env)) and _handlers.get(self.provider, (None, None))[0]

    def _guard(self) -> STTHandler:
        if not self.allow_cloud:
            raise VoiceUnavailable(
                "Cloud speech recognition is off. Turn on 'allow_cloud' in voice settings only if "
                "you accept that audio leaves this machine."
            )
        if not os.environ.get(self.api_key_env):
            raise VoiceUnavailable(
                f"Cloud speech recognition has no key. Set {self.api_key_env} in .env."
            )
        handler = _handlers.get(self.provider, (None, None))[0]
        if handler is None:
            raise VoiceUnavailable(
                f"No cloud speech provider '{self.provider}' is registered in this build."
            )
        return handler

    def transcribe(self, audio: AudioInput, language: Optional[str] = None,
                   vad: bool = True) -> Transcript:
        handler = self._guard()
        if not isinstance(audio, bytes):
            with open(audio, "rb") as handle:
                audio = handle.read()
        result = handler(audio, language)
        return Transcript(
            text=(result.get("text") or "").strip(),
            language=result.get("language") or language,
            duration_s=float(result.get("duration") or 0.0),
            engine=f"cloud/{self.provider}",
            inference_ms=float(result.get("inference_ms") or 0.0),
        )


class CloudTTS:
    name = "cloud"

    def __init__(self, provider: str = "default", api_key_env: str = "MIMO_CLOUD_TTS_KEY",
                 allow_cloud: bool = False) -> None:
        self.provider = provider
        self.api_key_env = api_key_env
        self.allow_cloud = allow_cloud

    def is_available(self) -> bool:
        return bool(os.environ.get(self.api_key_env)) and _handlers.get(self.provider, (None, None))[1]

    def _guard(self) -> TTSHandler:
        if not self.allow_cloud:
            raise VoiceUnavailable(
                "Cloud speech is off. Turn on 'allow_cloud' only if you accept that MIMO's answer "
                "text leaves this machine."
            )
        if not os.environ.get(self.api_key_env):
            raise VoiceUnavailable(f"Cloud speech has no key. Set {self.api_key_env} in .env.")
        handler = _handlers.get(self.provider, (None, None))[1]
        if handler is None:
            raise VoiceUnavailable(f"No cloud speech provider '{self.provider}' is registered.")
        return handler

    def synthesize(self, text: str, speed: float = 1.0) -> AudioChunk:
        handler = self._guard()
        audio = handler(text, speed)
        return AudioChunk(audio=audio, sample_rate=24000)

    def stream(self, text: str, speed: float = 1.0) -> Iterable[AudioChunk]:
        raise VoiceUnavailable("Streaming is local-only; use synthesize().")
