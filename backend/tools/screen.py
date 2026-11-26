"""Screen understanding and computer interaction.

Both need real hardware. On this machine they report exactly what is missing instead of pretending;
on Windows they use ImageGrab / pyautogui. Screenshots are written inside the allowed folders and
OCR text stays on the machine.
"""
from __future__ import annotations

import platform
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from ..core.agent.registry import CONSEQUENTIAL, READ_ONLY, REVERSIBLE, ToolError, ToolRegistry, ToolSpec
from .paths import allowed_roots, resolve_in_roots

KEY_NAMES = ("enter", "tab", "esc", "space", "backspace", "delete", "up", "down", "left", "right",
             "home", "end", "pageup", "pagedown", "ctrl", "alt", "shift", "win", "f5", "ctrl+s",
             "ctrl+c", "ctrl+v", "ctrl+z", "ctrl+a", "alt+tab")


class _Capture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: Optional[str] = Field(default=None, max_length=1000,
                                description="where to save; defaults into your allowed folders")


class _OCR(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: Optional[str] = Field(default=None, max_length=1000,
                                description="an existing image; captures the screen when empty")


class _Type(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=2000)


class _Keys(BaseModel):
    model_config = ConfigDict(extra="forbid")
    combo: str = Field(min_length=1, max_length=40, description="for example 'ctrl+s' or 'enter'")


class _Click(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: int = Field(ge=0, le=20000)
    y: int = Field(ge=0, le=20000)
    button: str = Field(default="left", max_length=10)


class _Scroll(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: int = Field(default=-3, ge=-20, le=20, description="negative scrolls down")


def _screenshot_dir() -> Path:
    roots = allowed_roots()
    if not roots:
        raise ToolError("No folder is allowed for screenshots. Set MIMO_FILE_ROOTS.")
    target = roots[0] / "mimo-screenshots"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _capture(p: _Capture) -> dict:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if p.path:
        dest = resolve_in_roots(p.path, must_exist=False)
    else:
        dest = _screenshot_dir() / f"screen-{stamp}.png"
    dest.parent.mkdir(parents=True, exist_ok=True)

    system = platform.system()
    if system == "Windows":
        try:
            from PIL import ImageGrab
        except ImportError:
            raise ToolError("Install 'pillow' to capture the screen.") from None
        image = ImageGrab.grab()
    else:
        try:
            import mss
        except ImportError:
            raise ToolError("Screen capture on this platform needs the optional 'mss' package; "
                            "on Windows it uses pillow instead.") from None
        with mss.mss() as sct:
            from PIL import Image
            raw = sct.grab(sct.monitors[1])
            image = Image.frombytes("RGB", raw.size, raw.rgb)
    image.save(dest, "PNG")
    size = dest.stat().st_size
    if size < 1000:
        raise ToolError("The screenshot came out empty; the display may be unavailable.")
    return {"path": str(dest), "width": image.width, "height": image.height, "bytes": size}


def _ocr(p: _OCR) -> dict:
    if p.path:
        image_path = resolve_in_roots(p.path)
    else:
        image_path = Path(_capture(_Capture()).get("path", ""))
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        raise ToolError("Reading text from a screen needs the optional 'pytesseract' and "
                        "'pillow' packages, plus the Tesseract program installed.") from None
    try:
        text = pytesseract.image_to_string(Image.open(image_path))
    except Exception as e:
        raise ToolError(f"OCR failed on that image: {e}") from None
    clean = "\n".join(line for line in (l.strip() for l in text.splitlines()) if line)
    return {"path": str(image_path), "chars": len(clean), "text": clean[:8000]}


def _require_pyautogui():
    if platform.system() not in ("Windows", "Darwin", "Linux"):
        raise ToolError(f"Computer control is not supported on {platform.system()}.")
    try:
        import pyautogui
    except ImportError:
        raise ToolError("Install the optional 'pyautogui' package to control the mouse and "
                        "keyboard.") from None
    pyautogui.FAILSAFE = True          # moving to a corner aborts, the user's emergency brake
    return pyautogui


def _type(p: _Type) -> dict:
    gui = _require_pyautogui()
    time.sleep(0.15)
    gui.write(p.text, interval=0.01)
    return {"typed": len(p.text)}


def _press(p: _Keys) -> dict:
    if p.combo.lower().replace(" ", "") not in KEY_NAMES:
        raise ToolError(f"'{p.combo}' is not one of the keys I am allowed to press.")
    gui = _require_pyautogui()
    keys = [k.strip() for k in p.combo.lower().split("+")]
    gui.hotkey(*keys) if len(keys) > 1 else gui.press(keys[0])
    return {"pressed": p.combo}


def _click(p: _Click) -> dict:
    if p.button not in ("left", "right", "middle"):
        raise ToolError("button must be left, right or middle.")
    gui = _require_pyautogui()
    gui.moveTo(p.x, p.y, duration=0.15)
    gui.click(button=p.button)
    return {"clicked": [p.x, p.y], "button": p.button}


def _scroll(p: _Scroll) -> dict:
    gui = _require_pyautogui()
    gui.scroll(p.amount)
    return {"scrolled": p.amount}


def register_screen_tools(registry: ToolRegistry) -> ToolRegistry:
    registry.register(ToolSpec(
        "capture_screen", "Take a screenshot and save it inside your allowed folders.",
        _Capture, _capture, REVERSIBLE,
        verify=lambda p, out: isinstance(out, dict) and out.get("bytes", 0) > 1000))
    registry.register(ToolSpec(
        "read_screen_text", "Read the text visible on screen (or in an image) with OCR.",
        _OCR, _ocr, READ_ONLY))
    registry.register(ToolSpec("type_text", "Type text into the focused window.",
                               _Type, _type, CONSEQUENTIAL))
    registry.register(ToolSpec("press_keys", "Press a key or key combination in the focused window.",
                               _Keys, _press, CONSEQUENTIAL))
    registry.register(ToolSpec("click_at", "Move the mouse to a point and click.",
                               _Click, _click, CONSEQUENTIAL))
    registry.register(ToolSpec("scroll", "Scroll the focused window.", _Scroll, _scroll, REVERSIBLE))
    return registry


def capabilities() -> dict:
    """What this machine can actually do right now - used by /system/capabilities and the UI."""
    def has(module: str) -> bool:
        try:
            __import__(module)
            return True
        except ImportError:
            return False

    system = platform.system()
    return {
        "platform": system,
        "files": bool(allowed_roots()),
        "file_roots": [str(r) for r in allowed_roots()],
        "shell": system == "Windows" and bool(shutil_which("powershell")),
        "screenshot": has("PIL") if system == "Windows" else has("mss") and has("PIL"),
        "ocr": has("pytesseract") and has("PIL"),
        "input": has("pyautogui"),
        "windows": has("pygetwindow") and system == "Windows",
        "apps": system in ("Windows", "Darwin", "Linux"),
        "processes": has("psutil"),
    }


def shutil_which(name: str):
    import shutil
    return shutil.which(name)
