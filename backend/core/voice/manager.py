"""Resolution, status and benchmarking for the voice engines."""
from __future__ import annotations

import gc
import time
from dataclasses import asdict, dataclass
from typing import Optional

from .base import (AudioChunk, AudioInput, NullSTT, NullTTS, STTEngine, TTSEngine, Transcript,
                   VoiceUnavailable)
from .config import VoiceSettings
from .stt_local import WhisperSTT
from .tts_local import KOKORO_MODEL, KOKORO_VOICES, KokoroTTS


@dataclass
class VoiceStatus:
    enabled: bool
    stt_provider: str
    stt_engine: str
    stt_available: bool
    stt_detail: str
    tts_provider: str
    tts_engine: str
    tts_available: bool
    tts_detail: str
    allow_cloud: bool
    model_dir: str

    def as_dict(self) -> dict:
        return asdict(self)


class VoiceManager:
    """Owns the two engines and answers "can I actually do this?" without lying.

    Engines are built once and reused: loading a Whisper model costs seconds and hundreds of
    megabytes, and a request handler that re-built it would make every phrase feel broken.
    """

    def __init__(self, settings: VoiceSettings) -> None:
        self.settings = settings
        self._stt: Optional[STTEngine] = None
        self._tts: Optional[TTSEngine] = None
        self._tts_engine_obj: Optional[KokoroTTS] = None

    # ------------------------------------------------------------- resolution
    def configure(self, settings: VoiceSettings) -> None:
        self.settings = settings
        self._stt = None
        self._tts = None
        self._tts_engine_obj = None
        gc.collect()

    def stt(self) -> STTEngine:
        if self._stt is None:
            self._stt = self._build_stt()
        return self._stt

    def tts(self) -> TTSEngine:
        if self._tts is None:
            self._tts, self._tts_engine_obj = self._build_tts()
        return self._tts

    def _build_stt(self) -> STTEngine:
        settings = self.settings
        if not settings.enabled or settings.stt_provider == "off":
            return NullSTT("Speech recognition is switched off in voice settings.")
        if settings.stt_provider == "cloud":
            if not settings.allow_cloud:
                return NullSTT(
                    "Cloud speech recognition was selected but 'allow_cloud' is false, so MIMO "
                    "will not send audio anywhere."
                )
            from .cloud import CloudSTT
            return CloudSTT(allow_cloud=settings.allow_cloud)
        engine = WhisperSTT(
            model=settings.stt_model,
            compute_type=settings.stt_compute_type,
            device=settings.stt_device,
            model_dir=str(settings.models_dir()),
            beam_size=settings.stt_beam_size,
        )
        if not engine.is_available():
            return NullSTT(
                "faster-whisper is not installed. Run `pip install faster-whisper` "
                "(the model downloads on first use)."
            )
        return engine

    def _build_tts(self) -> tuple[TTSEngine, Optional[KokoroTTS]]:
        settings = self.settings
        if not settings.enabled or settings.tts_provider == "off":
            return NullTTS("Speech output is switched off in voice settings."), None
        engine = KokoroTTS(
            model_dir=str(settings.models_dir()),
            voice=settings.tts_voice,
            speed=settings.tts_speed,
            language=_kokoro_language(settings.language),
        )
        if not engine.package_installed():
            return NullTTS("kokoro-onnx is not installed. Run `pip install kokoro-onnx`."), None
        if not engine.files_present():
            return NullTTS(
                f"Kokoro model files are missing from {settings.models_dir()}: "
                f"{KOKORO_MODEL} and {KOKORO_VOICES}."
            ), None
        return engine, engine

    # ------------------------------------------------------------------ verbs
    def transcribe(self, audio: AudioInput, language: Optional[str] = None,
                   vad: bool = True) -> Transcript:
        engine = self.stt()
        if isinstance(engine, NullSTT):
            raise VoiceUnavailable(engine.reason)
        return engine.transcribe(audio, language=language or self.settings.language, vad=vad)

    def speak(self, text: str, speed: Optional[float] = None) -> AudioChunk:
        if not text.strip():
            raise VoiceUnavailable("There is nothing to say.")
        engine = self.tts()
        if isinstance(engine, NullTTS):
            raise VoiceUnavailable(engine.reason)
        return engine.synthesize(text, speed=speed if speed is not None else self.settings.tts_speed)

    def stream_speech(self, text: str, speed: Optional[float] = None):
        engine = self.tts()
        if isinstance(engine, NullTTS):
            raise VoiceUnavailable(engine.reason)
        return engine.stream(text, speed=speed if speed is not None else self.settings.tts_speed)

    def cancel_speech(self) -> bool:
        """Stops the next chunk. Returns False when nothing was being synthesised."""
        if self._tts_engine_obj is None:
            return False
        self._tts_engine_obj.cancel()
        self._tts_engine_obj.reset()
        return True

    # ----------------------------------------------------------------- status
    def status(self) -> VoiceStatus:
        settings = self.settings
        stt_engine = self._build_stt()
        tts_engine, _ = self._build_tts()
        return VoiceStatus(
            enabled=settings.enabled,
            stt_provider=settings.stt_provider,
            stt_engine=getattr(stt_engine, "name", "?"),
            stt_available=stt_engine.is_available(),
            stt_detail=getattr(stt_engine, "reason", "Ready." if stt_engine.is_available()
                               else "Unavailable."),
            tts_provider=settings.tts_provider,
            tts_engine=getattr(tts_engine, "name", "?"),
            tts_available=tts_engine.is_available(),
            tts_detail=getattr(tts_engine, "reason", "Ready." if tts_engine.is_available()
                               else "Unavailable."),
            allow_cloud=settings.allow_cloud,
            model_dir=str(settings.models_dir()),
        )

    # ------------------------------------------------------------- benchmark
    def bench(self, audio_path: Optional[str] = None, text: Optional[str] = None) -> dict:
        """Measured, never estimated. Raises [VoiceUnavailable] when a model is not installed."""
        import os

        result: dict = {"environment": _environment()}
        if audio_path:
            engine = self.stt()
            if isinstance(engine, NullSTT):
                raise VoiceUnavailable(engine.reason)
            before = _rss_mb()
            started = time.perf_counter()
            transcript = engine.transcribe(audio_path)
            total_ms = (time.perf_counter() - started) * 1000
            result["stt"] = {
                "engine": transcript.engine,
                "audio_s": transcript.duration_s,
                "load_plus_inference_ms": round(total_ms, 1),
                "inference_ms": transcript.inference_ms,
                "real_time_factor": transcript.real_time_factor,
                "rss_delta_mb": round(_rss_mb() - before, 1),
                "text": transcript.text[:200],
            }
        if text:
            engine = self.tts()
            if isinstance(engine, NullTTS):
                raise VoiceUnavailable(engine.reason)
            before = _rss_mb()
            first_ms = None
            started = time.perf_counter()
            bytes_total = 0
            for chunk in self.stream_speech(text):
                if first_ms is None:
                    first_ms = (time.perf_counter() - started) * 1000
                bytes_total += len(chunk.audio)
            total_ms = (time.perf_counter() - started) * 1000
            result["tts"] = {
                "engine": getattr(engine, "name", "kokoro-onnx"),
                "text_chars": len(text),
                "first_chunk_ms": round(first_ms or total_ms, 1),
                "total_ms": round(total_ms, 1),
                "audio_bytes": bytes_total,
                "rss_delta_mb": round(_rss_mb() - before, 1),
                "sample_rate": 24000,
            }
        return result


KOKORO_LANGUAGES = {
    "en": "en-us", "en-us": "en-us", "en-gb": "en-gb",
    "es": "es", "fr": "fr-fr", "hi": "hi", "it": "it", "ja": "ja",
    "pt": "pt-br", "pt-br": "pt-br", "zh": "cmn",
}


def _kokoro_language(language: Optional[str]) -> str:
    """Kokoro's phonemiser wants its own language codes, and `en` is not one of them.

    A bare two-letter code is mapped to the model's own tag; anything else is passed through and
    will be refused by the engine with a message naming the language, rather than a traceback.
    """
    if not language:
        return "en-us"
    code = language.replace("_", "-").lower()
    return KOKORO_LANGUAGES.get(code, code)


def _rss_mb() -> float:
    try:
        import psutil
        return psutil.Process().memory_info().rss / (1024 * 1024)
    except Exception:
        try:
            with open("/proc/self/status", encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1]) / 1024.0
        except OSError:
            pass
        return 0.0


def _environment() -> dict:
    import platform
    import sys

    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": __import__("os").cpu_count(),
    }


def get_settings() -> VoiceSettings:
    from .config import load_settings
    return load_settings()
