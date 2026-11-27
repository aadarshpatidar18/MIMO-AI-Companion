"""Local speech recognition through faster-whisper (CTranslate2)."""
from __future__ import annotations

import io
import os
import tempfile
import time
from pathlib import Path
from typing import Optional

import wave
from typing import Union

from .base import AudioInput, Segment, Transcript, VoiceUnavailable

TARGET_RATE = 16000


def _numpy():
    """Imported on use, not at module load: the backend must start without numpy installed."""
    try:
        import numpy
    except Exception as error:  # pragma: no cover - only on a machine with no numpy at all
        raise VoiceUnavailable(
            "Decoding audio needs numpy, which is not installed. Run `pip install numpy`."
        ) from error
    return numpy


def read_wav(data: Union[bytes, str]) -> tuple["np.ndarray", int]:
    """Decode a PCM WAV to mono float32 in [-1, 1], plus its sample rate.

    Deliberately not faster-whisper's own decoder: that path goes through PyAV, whose API drifts
    independently (`av.open(metadata_errors=...)` was removed), and every recording this project
    receives is a WAV the browser or the app produced. A stdlib decoder here is one less way for
    voice to break under a dependency upgrade.
    """
    np = _numpy()
    try:
        source = io.BytesIO(data) if isinstance(data, bytes) else str(data)
        with wave.open(source, "rb") as handle:
            channels = handle.getnchannels()
            width = handle.getsampwidth()
            rate = handle.getframerate()
            frames = handle.readframes(handle.getnframes())
    except (wave.Error, OSError, EOFError) as error:
        raise VoiceUnavailable(
            "That audio is not a readable WAV file. Record as 16-bit PCM WAV and retry."
        ) from error
    if width == 2:
        samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 1:
        samples = (np.frombuffer(frames, dtype="<u1").astype(np.float32) - 128.0) / 128.0
    elif width == 4:
        samples = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise VoiceUnavailable(f"Unsupported WAV sample width: {width * 8} bit.")
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    if rate != TARGET_RATE and samples.size:
        samples = resample(samples, rate, TARGET_RATE)
    return samples.astype(np.float32), TARGET_RATE


def resample(samples: "np.ndarray", rate: int, target: int) -> "np.ndarray":
    """Linear resampling — adequate for speech headed into a mel filterbank, and dependency-free."""
    if rate == target:
        return samples
    np = _numpy()
    duration = samples.size / float(rate)
    count = max(int(round(duration * target)), 1)
    source_positions = np.linspace(0.0, duration, num=samples.size, endpoint=False)
    target_positions = np.linspace(0.0, duration, num=count, endpoint=False)
    return np.interp(target_positions, source_positions, samples).astype(np.float32)


class WhisperSTT:
    """faster-whisper, loaded lazily and once per process.

    Model choice is a memory trade, measured rather than guessed (see docs/VOICE.md):
    `small.en` int8 is roughly 0.5 GB resident and stays faster than real time on a 4-core CPU;
    `large-v3` needs several gigabytes and a GPU to be usable interactively. The default is the
    small model for that reason, not because it is the most accurate.
    """

    name = "faster-whisper"

    def __init__(self, model: str = "small.en", compute_type: str = "int8",
                 device: str = "auto", model_dir: Optional[str] = None,
                 beam_size: int = 1) -> None:
        self.model_name = model
        self.compute_type = compute_type
        self.requested_device = device
        self.model_dir = model_dir
        self.beam_size = beam_size
        self._model = None
        self._resolved: Optional[tuple[str, str]] = None
        self._load_ms: Optional[float] = None

    # ------------------------------------------------------------------ setup
    @staticmethod
    def package_installed() -> bool:
        try:
            import faster_whisper  # noqa: F401
        except Exception:
            return False
        return True

    def is_available(self) -> bool:
        return self.package_installed()

    def _resolve_device(self) -> tuple[str, str]:
        if self._resolved is not None:
            return self._resolved
        device = self.requested_device
        compute = self.compute_type
        if device == "auto":
            device = "cpu"
            compute = "int8" if compute in ("float16", "default") else compute
            try:                       # a GPU is used only if CTranslate2 says it can
                import ctranslate2
                if ctranslate2.get_cuda_device_count() > 0:
                    device, compute = "cuda", "float16"
            except Exception:
                device, compute = "cpu", "int8"
        self._resolved = (device, compute)
        return self._resolved

    def _load(self):
        if self._model is not None:
            return self._model
        if not self.package_installed():
            raise VoiceUnavailable(
                "Local speech recognition is not installed. Run "
                "`pip install faster-whisper` (it pulls CTranslate2), then retry."
            )
        from faster_whisper import WhisperModel

        device, compute = self._resolve_device()
        download_root = None
        if self.model_dir:
            Path(self.model_dir).expanduser().mkdir(parents=True, exist_ok=True)
            download_root = str(Path(self.model_dir).expanduser())
        started = time.perf_counter()
        try:
            self._model = WhisperModel(
                self.model_name,
                device=device,
                compute_type=compute,
                download_root=download_root,
                num_workers=1,
            )
        except Exception as error:      # a missing model, a broken install, no disk
            raise VoiceUnavailable(
                f"Whisper model '{self.model_name}' could not be loaded ({error}). "
                "Either install it (`pip install faster-whisper`, the model downloads on first "
                "use) or choose a smaller one in voice settings."
            ) from error
        self._load_ms = (time.perf_counter() - started) * 1000
        return self._model

    @property
    def load_ms(self) -> Optional[float]:
        return self._load_ms

    # -------------------------------------------------------------- inference
    def transcribe(self, audio: AudioInput, language: Optional[str] = None,
                   vad: bool = True) -> Transcript:
        model = self._load()
        if not isinstance(audio, bytes) and not Path(audio).exists():
            raise VoiceUnavailable(f"No audio file at {audio}.")
        samples, _ = read_wav(audio)
        if samples.size == 0:
            raise VoiceUnavailable("The recording was empty.")
        started = time.perf_counter()
        segments, info = model.transcribe(
            samples,
            language=language or None,
            vad_filter=vad,
            beam_size=self.beam_size,
            condition_on_previous_text=False,   # a stuck prompt is worse than lost context
        )
        collected = []
        for segment in segments:
            text = (segment.text or "").strip()
            if text:
                collected.append(Segment(round(segment.start, 2), round(segment.end, 2), text))
        elapsed_ms = (time.perf_counter() - started) * 1000
        text = " ".join(s.text for s in collected).strip()
        return Transcript(
            text=text,
            language=getattr(info, "language", language),
            duration_s=float(getattr(info, "duration", 0.0) or 0.0),
            segments=tuple(collected),
            engine=f"faster-whisper/{self.model_name}",
            inference_ms=round(elapsed_ms, 1),
        )
