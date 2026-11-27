"""Voice engine behaviour that can be proven with no model installed.

The interesting cases are the ones where a capability is *missing*: the engine must refuse with a
message that tells the user what to install, never a traceback and never a silent empty answer.
"""
import io
import json
import os
import wave

import pytest

from backend.core.voice import (AudioChunk, NullSTT, NullTTS, Transcript, VoiceManager,
                                VoiceSettings, VoiceUnavailable, load_settings, save_settings,
                                split_sentences)
from backend.core.voice import config as voice_config
from backend.core.voice.tts_local import KOKORO_MODEL, KOKORO_VOICES, KokoroTTS
from backend.core.voice.stt_local import WhisperSTT


# --------------------------------------------------------------------- settings
def test_defaults_are_local_and_cloud_is_off():
    settings = VoiceSettings()
    assert settings.stt_provider == "local"
    assert settings.tts_provider == "local"
    assert settings.allow_cloud is False
    assert settings.cloud_permitted() is False


def test_cloud_needs_both_the_provider_and_the_switch():
    assert VoiceSettings(stt_provider="cloud").cloud_permitted() is False
    assert VoiceSettings(stt_provider="cloud", allow_cloud=True).cloud_permitted() is True
    assert VoiceSettings(stt_provider="local", allow_cloud=True).cloud_permitted() is False


@pytest.mark.parametrize("field,value", [
    ("stt_compute_type", "float64"),
    ("stt_device", "tpu"),
    ("tts_speed", 3.0),
    ("max_utterance_s", 0),
    ("tts_voice", "   "),
    ("stt_provider", "telepathy"),
])
def test_invalid_settings_are_refused(field, value):
    with pytest.raises(ValueError):
        VoiceSettings(**{field: value})


def test_settings_round_trip(tmp_path):
    path = tmp_path / "voice.json"
    original = VoiceSettings(stt_model="base.en", tts_voice="af_bella", tts_speed=1.2,
                             allow_cloud=True, language="en")
    save_settings(original, path)
    assert json.loads(path.read_text())["stt_model"] == "base.en"
    assert load_settings(path) == original


def test_a_corrupt_settings_file_says_so(tmp_path):
    path = tmp_path / "voice.json"
    path.write_text("{not json")
    with pytest.raises(ValueError, match="readable JSON"):
        load_settings(path)


def test_missing_file_means_defaults(tmp_path):
    assert load_settings(tmp_path / "absent.json") == VoiceSettings()


# ------------------------------------------------------------- chunking for TTS
def test_sentences_are_split_for_streaming():
    text = "First sentence. Second one! And a third?"
    assert split_sentences(text) == ["First sentence.", "Second one!", "And a third?"]


def test_a_long_sentence_is_cut_not_returned_whole():
    pieces = split_sentences("word " * 120)
    assert len(pieces) > 1
    assert all(len(piece) <= 260 for piece in pieces)


def test_empty_text_produces_no_chunks():
    assert split_sentences("   \n ") == []


# ------------------------------------------------------------------- refusing
def test_missing_whisper_package_explains_itself(monkeypatch):
    monkeypatch.setattr(WhisperSTT, "package_installed", staticmethod(lambda: False))
    manager = VoiceManager(VoiceSettings())
    status = manager.status()
    assert status.stt_available is False
    assert "faster-whisper" in status.stt_detail
    with pytest.raises(VoiceUnavailable, match="faster-whisper"):
        manager.transcribe(b"RIFF....")


def test_missing_kokoro_files_name_the_file(monkeypatch, tmp_path):
    monkeypatch.setattr(KokoroTTS, "package_installed", staticmethod(lambda: True))
    settings = VoiceSettings(model_dir=str(tmp_path))
    manager = VoiceManager(settings)
    status = manager.status()
    assert status.tts_available is False
    assert KOKORO_MODEL in status.tts_detail and KOKORO_VOICES in status.tts_detail
    with pytest.raises(VoiceUnavailable, match="missing"):
        manager.speak("hello")


def test_cloud_is_refused_without_permission():
    manager = VoiceManager(VoiceSettings(stt_provider="cloud", allow_cloud=False))
    status = manager.status()
    assert status.stt_available is False
    assert "allow_cloud" in status.stt_detail
    with pytest.raises(VoiceUnavailable, match="allow_cloud"):
        manager.transcribe(b"RIFF....")


def test_cloud_without_a_key_is_refused(monkeypatch):
    monkeypatch.delenv("MIMO_CLOUD_STT_KEY", raising=False)
    manager = VoiceManager(VoiceSettings(stt_provider="cloud", allow_cloud=True))
    with pytest.raises(VoiceUnavailable, match="key"):
        manager.transcribe(b"RIFF....")


def test_switched_off_engines_refuse_politely():
    manager = VoiceManager(VoiceSettings(enabled=False))
    with pytest.raises(VoiceUnavailable, match="switched off"):
        manager.transcribe(b"x")
    with pytest.raises(VoiceUnavailable, match="switched off"):
        manager.speak("hello")


def test_speaking_nothing_is_refused():
    with pytest.raises(VoiceUnavailable, match="nothing to say"):
        VoiceManager(VoiceSettings()).speak("   ")


def test_null_engines_are_not_available():
    assert NullSTT("regex").is_available() is False
    assert NullTTS("regex").is_available() is False


def test_transcript_real_time_factor_is_computed_not_guessed():
    fast = Transcript(text="x", duration_s=10.0, inference_ms=2500)
    assert fast.real_time_factor == 0.25
    assert Transcript(text="x").real_time_factor is None
    assert Transcript(text="x", duration_s=0, inference_ms=100).real_time_factor is None


# ---------------------------------------------------------------------- routes
@pytest.fixture
def voice_app(tmp_path, monkeypatch):
    """The real router on a bare app, with voice settings pointed at a temp file."""
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from starlette.testclient import TestClient as StarletteClient  # noqa: F401  (same class)

    monkeypatch.setenv("MIMO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MIMO_VOICE_CONFIG", str(tmp_path / "voice.json"))
    monkeypatch.delenv("MIMO_REQUIRE_AUTH", raising=False)

    from backend.core.voice import routes as voice_routes

    voice_routes.reset_manager()
    app = fastapi.FastAPI()
    app.include_router(voice_routes.router)
    with TestClient(app) as client:
        yield client, voice_routes
    voice_routes.reset_manager()


def test_status_reports_what_is_actually_installed(voice_app):
    client, _ = voice_app
    body = client.get("/voice/status").json()
    assert body["stt_engine"] in ("faster-whisper", "unavailable", "cloud")
    # Whatever this machine has, the report must agree with itself.
    if body["stt_available"]:
        assert body["stt_detail"]
    else:
        assert body["stt_detail"]


def test_settings_can_be_changed_and_are_persisted(voice_app, tmp_path):
    client, voice_routes = voice_app
    response = client.put("/voice/settings", json={"tts_speed": 1.3, "language": "en"})
    assert response.status_code == 200
    assert response.json()["settings"]["tts_speed"] == 1.3
    assert load_settings().tts_speed == 1.3
    assert voice_routes.get_manager().settings.tts_speed == 1.3


def test_bad_settings_are_a_400_not_a_traceback(voice_app):
    client, _ = voice_app
    response = client.put("/voice/settings", json={"tts_speed": 9})
    assert response.status_code == 400
    assert "tts_speed" in response.json()["detail"]


def test_transcribe_needs_audio_and_the_right_type(voice_app):
    client, _ = voice_app
    assert client.post("/voice/transcribe", content=b"x",
                       headers={"content-type": "application/json"}).status_code == 415
    assert client.post("/voice/transcribe", content=b"",
                       headers={"content-type": "audio/wav"}).status_code == 400


def test_oversize_recording_is_refused_before_any_model_runs(voice_app):
    client, _ = voice_app
    huge = b"\0" * (12 * 1024 * 1024 + 10)
    response = client.post("/voice/transcribe", content=huge,
                           headers={"content-type": "audio/wav"})
    assert response.status_code == 413


def test_transcribing_without_a_model_is_503_with_advice(voice_app, monkeypatch):
    """A machine with no engine says "install this", not "bad audio" — and never 500."""
    import io as _io
    import wave as _wave

    from backend.core.voice import routes as voice_routes
    from backend.core.voice.stt_local import WhisperSTT

    monkeypatch.setattr(WhisperSTT, "package_installed", staticmethod(lambda: False))
    voice_routes.reset_manager()

    buffer = _io.BytesIO()
    with _wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 1600)

    client, _ = voice_app
    response = client.post("/voice/transcribe", content=buffer.getvalue(),
                           headers={"content-type": "audio/wav"})
    assert response.status_code == 503
    assert "faster-whisper" in response.json()["detail"]


def test_speak_without_a_model_is_503_with_advice(voice_app):
    client, _ = voice_app
    response = client.post("/voice/speak", json={"text": "hello"})
    if response.status_code == 200:
        assert response.headers["content-type"].startswith("audio/wav")
        return
    assert response.status_code == 503
    assert response.json()["detail"]


def test_speaking_nothing_is_a_503_not_a_silent_file(voice_app):
    client, _ = voice_app
    assert client.post("/voice/speak", json={"text": " "}).status_code in (422, 503)


def test_cancel_reports_whether_anything_was_speaking(voice_app):
    client, _ = voice_app
    body = client.post("/voice/cancel").json()
    assert body["cancelled"] in (True, False)


def test_audio_chunk_carries_its_format():
    chunk = AudioChunk(audio=b"\0\0", sample_rate=24000)
    assert chunk.format == "wav" and len(chunk) == 2


def test_the_voice_package_imports_without_numpy_or_model_libraries():
    """A missing capability must never stop the backend from starting.

    `backend/api.py` imports this package at load time, so an eager `import numpy` here would take
    the whole API down on a machine that only ever wanted text chat.
    """
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    code = (
        "import sys\n"
        "for name in ('numpy', 'faster_whisper', 'kokoro_onnx', 'ctranslate2', 'onnxruntime'):\n"
        "    sys.modules[name] = None\n"
        "import backend.core.voice as v\n"
        "m = v.VoiceManager(v.VoiceSettings())\n"
        "s = m.status()\n"
        "assert s.stt_available is False, s\n"
        "assert 'faster-whisper' in s.stt_detail, s.stt_detail\n"
        "print('ok')\n"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=str(root),
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr[-1500:]
    assert "ok" in result.stdout


def test_unreadable_audio_is_a_400_not_a_missing_model(voice_app):
    """Bad input must not look like a broken install: one is the caller's fault, one is not."""
    client, _ = voice_app
    response = client.post("/voice/transcribe", content=b"not a wav at all",
                           headers={"content-type": "audio/wav"})
    assert response.status_code == 400
    assert "WAV" in response.json()["detail"]


def test_an_empty_recording_inside_a_valid_wav_is_a_400(voice_app):
    import io as _io
    import wave as _wave

    buffer = _io.BytesIO()
    with _wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"")
    response = voice_app[0].post("/voice/transcribe", content=buffer.getvalue(),
                                 headers={"content-type": "audio/wav"})
    assert response.status_code == 400


def test_models_can_be_unloaded_to_free_memory(voice_app):
    """On a 16 GB laptop the owner must be able to give ~1.25 GB back without a restart."""
    client, voice_routes = voice_app
    manager = voice_routes.get_manager()
    manager.stt()                     # touch it so there is something to unload
    assert manager._stt is not None
    body = client.post("/voice/unload").json()
    assert body["unloaded"]["stt"] is True
    assert manager._stt is None
    assert client.get("/voice/status").status_code == 200
