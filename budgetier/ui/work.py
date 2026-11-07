"""Slow work, off the window's thread: talking to SimpleFIN, and reading files that may be PDFs.

Only one piece runs at a time, and while it does, nothing else can change the data: the
window's contents are held still, and a note says what's happening. The answer comes back on
the window's thread, where the window can safely use it.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from .dialogs import attempt


class _Done(QObject):
    finished = Signal(bool, object)


class _Job(QRunnable):
    def __init__(self, work: Callable, args: tuple, done: _Done):
        super().__init__()
        self.work, self.args, self.done = work, args, done
        self.setAutoDelete(True)

    def run(self):
        ok, result = attempt(self.work, *self.args)
        self.done.finished.emit(ok, result)


class Runner(QObject):
    """window.runner.start(work, args, then): then(ok, result) runs on the window's thread.
    ok and result are as attempt() gives them."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.busy = False
        self._done: _Done | None = None

    def start(self, work: Callable, args: tuple, then: Callable[[bool, object], None], note: str = "") -> bool:
        if self.busy:
            self.window.toast.say("Wait for the last step to finish.")
            return False
        self.busy = True
        self.window.hold(True, note)
        self._done = _Done()

        def finished(ok: bool, result: object) -> None:
            self.busy = False
            self._done = None
            self.window.hold(False)
            then(ok, result)

        self._done.finished.connect(finished)
        self.pool.start(_Job(work, args, self._done))
        return True

    def wait(self, seconds: float = 30) -> bool:
        """For tests: let the work finish and its answer arrive. False if it didn't in time."""
        import time

        from PySide6.QtCore import QCoreApplication, QEventLoop
        deadline = time.monotonic() + seconds
        while self.busy and time.monotonic() < deadline:
            QCoreApplication.processEvents(QEventLoop.AllEvents, 50)
            time.sleep(.01)
        return not self.busy
