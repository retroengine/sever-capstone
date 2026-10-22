"""What every screen may ask of the window."""

from collections.abc import Callable
from typing import Any, Protocol

from ..actions import Studio
from .worker import Worker


class Host(Protocol):
    studio: Studio
    worker: Worker
    #: certificate log position -> (record ID, account), for this session's deletions
    receipts_of: dict[int, tuple[str, str]]

    def toast(
        self, text: str, colour: str = ..., action: str = "", on: Callable[[], None] | None = None
    ) -> None: ...

    def changed(self) -> None:
        """Something in the database or the checklist changed: refresh what shows it."""

    def go(self, screen: str, **kw: Any) -> None:
        """Switches to a screen; ``kw`` are passed to its ``arrive``."""

    def error(self, message: str) -> None: ...
