"""One background thread for every database call, so the window never freezes.

Calls run one at a time, in order (the database is one open handle). Each job reports back on the
window's thread: ``done(result)``, ``failed(message)`` and any number of ``progress(...)`` calls.
The SDK releases Python's lock while the engine works, so drawing goes on meanwhile.
"""

import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(object)


class _Job(QRunnable):
    def __init__(self, fn: Callable[..., Any], signals: _Signals, with_progress: bool) -> None:
        super().__init__()
        self.fn = fn
        self.signals = signals
        self.with_progress = with_progress

    def run(self) -> None:
        try:
            if self.with_progress:
                out = self.fn(lambda *a: self.signals.progress.emit(a))
            else:
                out = self.fn()
        except Exception as e:  # reported on screen; §17 errors carry no secret
            self.signals.failed.emit(f"{type(e).__name__}: {e}")
            traceback.print_exc()
            return
        self.signals.done.emit(out)


class Worker(QObject):
    busy_changed = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(1)
        self.pending = 0
        self._keep: list[_Signals] = []

    def submit(
        self,
        fn: Callable[..., Any],
        done: Callable[[Any], None] | None = None,
        failed: Callable[[str], None] | None = None,
        progress: Callable[[tuple[Any, ...]], None] | None = None,
    ) -> None:
        """Runs ``fn()`` (or ``fn(report)`` when ``progress`` is given) on the worker thread."""
        sig = _Signals()
        self._keep.append(sig)

        def finish() -> None:
            self.pending -= 1
            self._keep.remove(sig)
            if self.pending == 0:
                self.busy_changed.emit(False)

        if done:
            sig.done.connect(done)
        if failed:
            sig.failed.connect(failed)
        if progress:
            sig.progress.connect(progress)
        sig.done.connect(lambda _: finish())
        sig.failed.connect(lambda _: finish())
        self.pending += 1
        if self.pending == 1:
            self.busy_changed.emit(True)
        self.pool.start(_Job(fn, sig, progress is not None))

    def wait(self) -> None:
        self.pool.waitForDone()
