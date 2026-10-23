"""The 3-D map on the real display (run by test_ui.py): prints one JSON line.

``ok`` says OpenGL rendered (a real framebuffer); ``drawn`` counts the frame's pixels that are not
the background, so an empty frame fails.
"""

import json
import shutil
import sys
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "python"), str(ROOT / "studio")]

from sever_studio.actions import Studio  # noqa: E402
from sever_studio.ui import theme  # noqa: E402
from sever_studio.ui.main_window import MainWindow  # noqa: E402

app = QApplication([])
work = ROOT / "studio/work/test-map3d"
shutil.rmtree(work, ignore_errors=True)
s = Studio(ROOT, "synthetic", work, dev=True, rows=120)
s.open()
s.backend.insert_next(120)
w = MainWindow(s)
w.resize(1100, 700)
w.show()
w.go("explore")
e = w.sections["explore"]
e.set_mode("3d")
t0 = time.monotonic()
while time.monotonic() - t0 < 3 or w.worker.pending:
    app.processEvents()
    time.sleep(0.02)
m3 = e.map3d
rids, _, _ = m3.data()
drawn = 0
if m3.ok and m3.view is not None:
    img = m3.view.grabFramebuffer()
    bg = theme.BG.lower()
    for y in range(0, img.height(), 4):
        for x in range(0, img.width(), 4):
            if img.pixelColor(x, y).name() != bg:
                drawn += 1
print(
    json.dumps(
        {
            "ok": m3.ok,
            "reason": m3.reason,
            "dots": len(rids),
            "records": len(e.map.rids),
            "drawn": drawn,
        }
    )
)
w.close()
s.backend.close()
shutil.rmtree(work, ignore_errors=True)
