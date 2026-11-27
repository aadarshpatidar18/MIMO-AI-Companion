"""Running one HTTP call off the UI thread.

Qt widgets may only be touched from the GUI thread, so every backend call goes through here and
comes back as a signal.
"""
from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from .api import MimoError


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class Call(QRunnable):
    def __init__(self, fn: Callable[..., Any], *args, **kwargs) -> None:
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.signals = _Signals()

    @Slot()
    def run(self) -> None:
        try:
            self.signals.done.emit(self.fn(*self.args, **self.kwargs))
        except MimoError as error:
            self.signals.failed.emit(str(error))
        except Exception as error:                      # never let a thread die silently
            self.signals.failed.emit(f"Unexpected error: {error}")


# A QRunnable's Python wrapper is collected as soon as the last Python reference goes away, even
# while its C++ half is still running — and then its signals have no source. Holding each call
# until it reports back is what keeps the result from being delivered to a dead object.
_live: set = set()


def run_async(fn: Callable[..., Any], on_done: Callable[[Any], None],
              on_error: Callable[[str], None], *args, **kwargs) -> None:
    call = Call(fn, *args, **kwargs)
    _live.add(call)

    def finish_done(value: Any) -> None:
        _live.discard(call)
        on_done(value)

    def finish_error(message: str) -> None:
        _live.discard(call)
        on_error(message)

    call.signals.done.connect(finish_done)
    call.signals.failed.connect(finish_error)
    QThreadPool.globalInstance().start(call)
