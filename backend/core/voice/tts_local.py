"""Local speech synthesis through Kokoro-82M, exported to ONNX."""
from __future__ import annotations

import io
import threading
import time
import wave
from pathlib import Path
from typing import Iterable, Optional

from .base import AudioChunk, VoiceUnavailable, split_sentences

KOKORO_MODEL = "kokoro-v1.0.onnx"
KOKORO_VOICES = "voices-v1.0.bin"


def _to_wav(samples, sample_rate: int) -> bytes:
    """Float samples in [-1, 1] to a 16-bit mono WAV the browser can play without a codec."""
    import numpy as np

    array = np.asarray(samples, dtype="float32")
    if array.ndim > 1:
        array = array.reshape(-1)
    clipped = np.clip(array, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())
    return buffer.getvalue()


class KokoroTTS:
    """Kokoro, loaded lazily; synthesises sentence by sentence so speech starts early.

    Interruption is real, not decorative: [cancel] trips a token that the streaming generator
    checks between chunks, so a barge-in stops the very next sentence instead of finishing the
    paragraph.
    """

    name = "kokoro-onnx"

    def __init__(self, model_dir: str, voice: str = "af_heart", speed: float = 1.0,
                 language: str = "en-us") -> None:
        self.model_dir = Path(model_dir).expanduser()
        self.voice = voice
        self.speed = speed
        self.language = language
        self._engine = None
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._load_ms: Optional[float] = None

    # ------------------------------------------------------------------ setup
    @staticmethod
    def package_installed() -> bool:
        try:
            import kokoro_onnx  # noqa: F401
        except Exception:
            return False
        return True

    def model_path(self) -> Path:
        return self.model_dir / KOKORO_MODEL

    def voices_path(self) -> Path:
        return self.model_dir / KOKORO_VOICES

    def files_present(self) -> bool:
        return self.model_path().exists() and self.voices_path().exists()

    def is_available(self) -> bool:
        return self.package_installed() and self.files_present()

    def _load(self):
        if self._engine is not None:
            return self._engine
        if not self.package_installed():
            raise VoiceUnavailable(
                "Local text to speech is not installed. Run `pip install kokoro-onnx`."
            )
        if not self.files_present():
            raise VoiceUnavailable(
                "Kokoro model files are missing. Put "
                f"{KOKORO_MODEL} and {KOKORO_VOICES} in {self.model_dir} "
                "(download: https://github.com/thewh1teagle/kokoro-onnx/releases)."
            )
        from kokoro_onnx import Kokoro

        started = time.perf_counter()
        try:
            self._engine = Kokoro(str(self.model_path()), str(self.voices_path()))
        except Exception as error:
            raise VoiceUnavailable(f"Kokoro could not start: {error}") from error
        self._load_ms = (time.perf_counter() - started) * 1000
        return self._engine

    @property
    def load_ms(self) -> Optional[float]:
        return self._load_ms

    # -------------------------------------------------------------- synthesis
    def cancel(self) -> None:
        self._cancel.set()

    def reset(self) -> None:
        self._cancel.clear()

    def synthesize(self, text: str, speed: Optional[float] = None) -> AudioChunk:
        """One WAV for the whole reply — what a non-streaming client (the browser) wants."""
        engine = self._load()
        samples, rate = self._create(engine, text, speed)
        return AudioChunk(audio=_to_wav(samples, rate), sample_rate=rate)

    def stream(self, text: str, speed: Optional[float] = None) -> Iterable[AudioChunk]:
        engine = self._load()
        for sentence in split_sentences(text):
            if self._cancel.is_set():
                break
            samples, rate = self._create(engine, sentence, speed)
            yield AudioChunk(audio=_to_wav(samples, rate), sample_rate=rate)

    def _create(self, engine, text: str, speed: Optional[float]):
        with self._lock:
            try:
                samples, rate = engine.create(
                    text,
                    voice=self.voice,
                    speed=self.speed if speed is None else speed,
                    lang=self.language,
                )
            except RuntimeError as error:
                # kokoro-onnx raises RuntimeError from its phonemiser for an unsupported language
                # or voice; that is a settings problem, so it gets a settings answer.
                raise VoiceUnavailable(
                    f"Kokoro could not speak this: {error}. "
                    f"Check tts_voice ('{self.voice}') and language ('{self.language}')."
                ) from error
        return samples, int(rate)
