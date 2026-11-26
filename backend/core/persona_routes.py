"""HTTP API for MIMO's character, and the web app it is served with."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import persona as persona_mod

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
INDEX = WEB_DIR / "index.html"

router = APIRouter(tags=["persona"])


class PersonaBody(BaseModel):
    name: str = Field(default="MIMO", max_length=24)
    tagline: str = Field(default="", max_length=120)
    address_as: str = Field(default="", max_length=24)
    warmth: int = Field(default=3, ge=1, le=5)
    humour: int = Field(default=1, ge=0, le=3)
    verbosity: str = Field(default="balanced", max_length=10)
    signature: bool = True


@router.get("/persona")
def read_persona() -> dict:
    store = persona_mod.get_store()
    current = store.load()
    return {"persona": current, "greeting": persona_mod.greeting(current),
            "traits": list(persona_mod.TRAITS),
            "verbosities": list(persona_mod.VERBOSITIES)}


@router.put("/persona")
def write_persona(body: PersonaBody) -> dict:
    if body.verbosity not in persona_mod.VERBOSITIES:
        raise HTTPException(status_code=400,
                            detail=f"verbosity must be one of {', '.join(persona_mod.VERBOSITIES)}")
    saved = persona_mod.get_store().save(body.model_dump())
    return {"persona": saved, "greeting": persona_mod.greeting(saved)}


@router.post("/persona/reset")
def reset_persona() -> dict:
    saved = persona_mod.get_store().reset()
    return {"persona": saved, "greeting": persona_mod.greeting(saved)}


@router.get("/app", include_in_schema=False)
def web_app() -> FileResponse:
    """The MIMO interface. Works on a phone browser and a laptop browser alike."""
    if not INDEX.is_file():
        raise HTTPException(status_code=500, detail="The web interface is missing from this build.")
    return FileResponse(INDEX, media_type="text/html",
                        headers={"Cache-Control": "no-cache"})


@router.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)
