"""Voice settings: one small JSON file, validated, with cloud off unless asked for."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

STT_PROVIDERS = ("local", "cloud", "off")
TTS_PROVIDERS = ("local", "off")

DEFAULT_CONFIG_PATH = "~/.mimo/voice.json"
DEFAULT_MODEL_DIR = "~/.mimo/models"


def config_path() -> Path:
    return Path(os.environ.get("MIMO_VOICE_CONFIG", DEFAULT_CONFIG_PATH)).expanduser()


class VoiceSettings(BaseModel):
    """What the voice engine is allowed to do.

    Every default is local and every default is *quiet*: cloud processing is opt-in twice — the
    provider must be `cloud` **and** `allow_cloud` must be true — because a microphone is the most
    private sensor on a personal machine.
    """

    enabled: bool = True
    stt_provider: Literal["local", "cloud", "off"] = "local"
    stt_model: str = "small.en"
    stt_compute_type: str = "int8"
    stt_device: str = "auto"
    stt_beam_size: int = Field(default=1, ge=1, le=5)
    language: Optional[str] = "en"
    tts_provider: Literal["local", "off"] = "local"
    tts_voice: str = "af_heart"
    tts_speed: float = Field(default=1.0, ge=0.5, le=2.0)
    allow_cloud: bool = False
    max_utterance_s: int = Field(default=60, ge=1, le=300)
    model_dir: str = DEFAULT_MODEL_DIR

    @field_validator("stt_compute_type")
    @classmethod
    def _compute_type(cls, value: str) -> str:
        allowed = {"int8", "int8_float16", "float16", "float32", "default"}
        if value not in allowed:
            raise ValueError(f"compute_type must be one of {sorted(allowed)}")
        return value

    @field_validator("stt_device")
    @classmethod
    def _device(cls, value: str) -> str:
        allowed = {"auto", "cpu", "cuda"}
        if value not in allowed:
            raise ValueError(f"device must be one of {sorted(allowed)}")
        return value

    @field_validator("tts_voice")
    @classmethod
    def _voice(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("tts_voice cannot be empty")
        return value.strip()

    @field_validator("allow_cloud")
    @classmethod
    def _cloud_needs_a_provider(cls, value: bool) -> bool:
        return value

    def models_dir(self) -> Path:
        return Path(self.model_dir).expanduser()

    def cloud_permitted(self) -> bool:
        """A cloud provider is only usable when it was chosen *and* explicitly allowed."""
        return self.allow_cloud and self.stt_provider == "cloud"


def load_settings(path: Optional[Path] = None) -> VoiceSettings:
    target = path or config_path()
    if not target.exists():
        return VoiceSettings()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"{target} is not readable JSON: {error}") from error
    return VoiceSettings.model_validate(raw)


def save_settings(settings: VoiceSettings, path: Optional[Path] = None) -> Path:
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(settings.model_dump(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return target
