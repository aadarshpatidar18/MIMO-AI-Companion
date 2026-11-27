"""HTTP surface for voice. Mounted in backend/api.py."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from ..security.gate import require_scope
from .base import VoiceUnavailable
from .config import VoiceSettings, load_settings, save_settings
from .manager import VoiceManager

logger = logging.getLogger("mimo.voice")

router = APIRouter(prefix="/voice", tags=["voice"])

MAX_AUDIO_BYTES = 12 * 1024 * 1024     # ~4 minutes of 16 kHz mono PCM in a WAV container

_manager: Optional[VoiceManager] = None


def get_manager() -> VoiceManager:
    global _manager
    if _manager is None:
        _manager = VoiceManager(load_settings())
    return _manager


def reset_manager() -> None:
    """Test and settings hook: drop the loaded models so the next request reloads them."""
    global _manager
    _manager = None


class SpeakBody(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    speed: Optional[float] = Field(default=None, ge=0.5, le=2.0)


class SettingsPatch(BaseModel):
    enabled: Optional[bool] = None
    stt_provider: Optional[str] = None
    stt_model: Optional[str] = None
    stt_compute_type: Optional[str] = None
    stt_device: Optional[str] = None
    stt_beam_size: Optional[int] = None
    language: Optional[str] = None
    tts_provider: Optional[str] = None
    tts_voice: Optional[str] = None
    tts_speed: Optional[float] = None
    allow_cloud: Optional[bool] = None
    max_utterance_s: Optional[int] = None
    model_dir: Optional[str] = None


@router.get("/status")
def voice_status(manager: VoiceManager = Depends(get_manager),
                 _: Optional[dict] = Depends(require_scope("chat:read", allow_unpaired=True))) -> dict:
    return manager.status().as_dict()


@router.get("/settings")
def read_settings(_: Optional[dict] = Depends(require_scope("chat:read", allow_unpaired=True))
                  ) -> dict:
    return load_settings().model_dump()


@router.put("/settings")
def write_settings(body: SettingsPatch,
                   _: Optional[dict] = Depends(require_scope("chat:write", allow_unpaired=True))
                   ) -> dict:
    current = load_settings()
    merged = current.model_dump()
    for key, value in body.model_dump(exclude_none=True).items():
        merged[key] = value
    try:
        updated = VoiceSettings.model_validate(merged)
    except ValueError as error:               # pydantic's message names the offending field
        raise HTTPException(status_code=400, detail=str(error)) from None
    if updated.stt_provider == "cloud" and not updated.allow_cloud:
        # Saving this is harmless — the manager refuses to send anything — but the user should
        # know why nothing will happen.
        logger.info("cloud STT selected without allow_cloud; requests will be refused")
    save_settings(updated)
    get_manager().configure(updated)
    return {"saved": True, "settings": updated.model_dump(), "status": get_manager().status().as_dict()}


@router.post("/transcribe")
async def transcribe(
    request: Request,
    language: Optional[str] = Query(default=None, max_length=12),
    vad: bool = Query(default=True),
    manager: VoiceManager = Depends(get_manager),
    _: Optional[dict] = Depends(require_scope("chat:write", allow_unpaired=True)),
) -> dict:
    """Raw audio in the body (audio/wav), not a multipart upload: one dependency less, and every
    client that can record audio can also post a byte array."""
    content_type = (request.headers.get("content-type") or "").split(";")[0].strip()
    if content_type not in ("audio/wav", "audio/wave", "audio/x-wav", "application/octet-stream"):
        raise HTTPException(status_code=415,
                            detail="Send the audio as audio/wav in the request body.")
    audio = await request.body()
    if not audio:
        raise HTTPException(status_code=400, detail="The request had no audio.")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413,
                            detail=f"That recording is too long (max {MAX_AUDIO_BYTES // (1024 * 1024)} MB).")
    try:
        transcript = manager.transcribe(audio, language=language, vad=vad)
    except VoiceUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from None
    except Exception:
        logger.exception("transcription failed")
        raise HTTPException(status_code=500, detail="Speech recognition failed.") from None
    return {
        "text": transcript.text,
        "language": transcript.language,
        "duration_s": transcript.duration_s,
        "engine": transcript.engine,
        "inference_ms": transcript.inference_ms,
        "real_time_factor": transcript.real_time_factor,
        "segments": [
            {"start": s.start, "end": s.end, "text": s.text} for s in transcript.segments
        ],
    }


@router.post("/speak")
def speak(body: SpeakBody, manager: VoiceManager = Depends(get_manager),
          _: Optional[dict] = Depends(require_scope("chat:write", allow_unpaired=True))) -> Response:
    try:
        chunk = manager.speak(body.text, speed=body.speed)
    except VoiceUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from None
    except Exception:
        logger.exception("speech synthesis failed")
        raise HTTPException(status_code=500, detail="Speech synthesis failed.") from None
    return Response(
        content=chunk.audio,
        media_type="audio/wav",
        headers={"Cache-Control": "no-store", "X-MIMO-Sample-Rate": str(chunk.sample_rate)},
    )


@router.post("/cancel")
def cancel(manager: VoiceManager = Depends(get_manager),
           _: Optional[dict] = Depends(require_scope("chat:write", allow_unpaired=True))) -> dict:
    return {"cancelled": manager.cancel_speech()}
