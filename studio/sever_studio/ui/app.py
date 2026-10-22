"""Starts the window on a prepared database."""

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from ..actions import Studio
from . import theme
from .main_window import MainWindow


def run(root: Path, data: str, rows: int, work: Path, dev: bool) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    assert isinstance(app, QApplication)
    app.setApplicationName("SEVER-DB Studio")
    app.setFont(theme.font(11))
    app.setStyleSheet(theme.STYLE)
    if not (work / "index.json").exists():
        QMessageBox.information(
            None,
            "SEVER-DB Studio",
            f"No prepared database in {work}.\n\nRun first:\n  studio/studio.sh prepare"
            + (" --data synthetic" if data == "synthetic" else ""),
        )
        return 2
    studio = Studio(root, data, work, dev, rows)
    studio.open()
    win = MainWindow(studio)
    win.show()
    return app.exec()
