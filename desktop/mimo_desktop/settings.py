"""Desktop settings: the backend address and this PC's device token.

The token is written with owner-only permissions and never appears in a log line. Re-pairing
overwrites it; forgetting the device deletes the file's token field.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from .api import DEFAULT_BASE

SETTINGS_PATH = Path(os.environ.get("MIMO_DESKTOP_CONFIG", "~/.mimo/desktop.json")).expanduser()


@dataclass
class DesktopSettings:
    base_url: str = DEFAULT_BASE
    token: Optional[str] = None
    device_id: Optional[str] = None
    device_name: str = "Windows desktop"
    speak_replies: bool = False

    @property
    def is_paired(self) -> bool:
        return bool(self.token and self.device_id)


def load_settings(path: Optional[Path] = None) -> DesktopSettings:
    target = path or SETTINGS_PATH
    if not target.exists():
        return DesktopSettings()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # A corrupt settings file must not stop the app from opening: start unpaired instead and
        # let the user pair again, rather than crashing on launch.
        return DesktopSettings()
    return DesktopSettings(
        base_url=raw.get("base_url") or DEFAULT_BASE,
        token=raw.get("token"),
        device_id=raw.get("device_id"),
        device_name=raw.get("device_name") or "Windows desktop",
        speak_replies=bool(raw.get("speak_replies", False)),
    )


def save_settings(settings: DesktopSettings, path: Optional[Path] = None) -> Path:
    target = path or SETTINGS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(asdict(settings), indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    return target
