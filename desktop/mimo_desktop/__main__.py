"""Entry point: `python -m mimo_desktop` or the MIMO Desktop shortcut.

The browser interface keeps working exactly as before; this is a second front end over the same
backend, not a replacement for it.
"""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .api import MimoApi
from .settings import load_settings
from .theme import QSS
from .window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("MIMO")
    app.setStyleSheet(QSS)
    settings = load_settings()
    window = MainWindow(settings, MimoApi(settings.base_url, settings.token))
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
