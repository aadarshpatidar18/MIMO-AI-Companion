"""Local-first voice: faster-whisper for speech in, Kokoro for speech out.

Importing this package must never fail on a machine without the model libraries — engines load
lazily and refuse per request with an actionable message. See docs/VOICE.md.
"""
from .base import (AudioChunk, NullSTT, NullTTS, Segment, Transcript, VoiceUnavailable,
                   split_sentences)
from .config import VoiceSettings, load_settings, save_settings
from .manager import VoiceManager, VoiceStatus
from .routes import router

__all__ = [
    "AudioChunk", "NullSTT", "NullTTS", "Segment", "Transcript", "VoiceUnavailable",
    "VoiceManager", "VoiceStatus", "VoiceSettings", "load_settings", "save_settings",
    "split_sentences", "router",
]
