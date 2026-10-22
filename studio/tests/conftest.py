"""Shared set-up for Studio's tests.

Every Qt test in this process draws offscreen on an emulated 1280 × 800 screen at device pixel
ratio 2: the owner's laptop under WSLg, where a window wider than the screen was killed by the
compositor. The display the tests started on is kept in ``REAL_DISPLAY`` for the live smoke test.

Tests marked ``full`` (the real display, the NQ data, the soak, live sabotage) run only with
``SEVER_STUDIO_FULL=1`` (``studio/studio.sh test --full``). Every test may add numbers to the
report, written to ``studio/work/test-report.json`` at the end.
"""

import json
import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "studio/work"
FULL = os.environ.get("SEVER_STUDIO_FULL") == "1"
REAL_DISPLAY = os.environ.get("QT_QPA_PLATFORM", "")


def screen_config(path: Path, width: int, height: int, dpr: float) -> str:
    path.write_text(
        json.dumps(
            {
                "synchronousWindowSystemEvents": True,
                "windowFrameMargins": False,
                "screens": [
                    {
                        "name": f"emulated-{width}x{height}",
                        "x": 0,
                        "y": 0,
                        "width": width,
                        "height": height,
                        "logicalDpi": 96,
                        "logicalBaseDpi": 96,
                        "dpr": dpr,
                    }
                ],
            }
        ),
        "utf-8",
    )
    return f"offscreen:configfile={path}"


WORK.mkdir(parents=True, exist_ok=True)
os.environ["QT_QPA_PLATFORM"] = screen_config(WORK / ".screen-1280x800.json", 1280, 800, 2.0)
os.environ.setdefault("PYTHONHASHSEED", "0")

REPORT: dict[str, Any] = {
    "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "tests": {},
}


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "full: slow; runs only with SEVER_STUDIO_FULL=1")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if FULL:
        return
    skip = pytest.mark.skip(reason="full tier: studio/studio.sh test --full")
    for item in items:
        if "full" in item.keywords:
            item.add_marker(skip)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> Iterator[None]:
    outcome = yield
    rep = outcome.get_result()  # type: ignore[attr-defined]
    if rep.when == "call" or (rep.when == "setup" and rep.outcome != "passed"):
        entry = REPORT["tests"].setdefault(item.nodeid, {})
        entry["outcome"] = rep.outcome
        entry["seconds"] = round(rep.duration, 2)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    REPORT["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    REPORT["full"] = FULL
    REPORT["exit"] = int(exitstatus)
    (WORK / "test-report.json").write_text(json.dumps(REPORT, indent=1), "utf-8")


@pytest.fixture
def report(request: pytest.FixtureRequest) -> dict[str, Any]:
    """Numbers a test wants in the report (no key, ``r_t`` or passage text)."""
    entry: dict[str, Any] = REPORT["tests"].setdefault(request.node.nodeid, {})
    return entry
