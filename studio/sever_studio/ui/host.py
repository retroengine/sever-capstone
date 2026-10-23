"""What every section may ask of the window."""

from collections.abc import Callable
from typing import Any, Protocol

from ..actions import Studio
from .worker import Worker


class Host(Protocol):
    studio: Studio
    worker: Worker
    #: certificate log position -> (record ID, account), for this session's deletions

    def toast(
        self,
        text: str,
        ok: bool | None = True,
        action: str = "",
        on: Callable[[], None] | None = None,
    ) -> None: ...

    def changed(self) -> None:
        """The database or the checklist changed: refresh what shows them."""

    def go(self, section: str, tab: str | None = None, **kw: Any) -> None:
        """Switches to a section (and one of its tabs); ``kw`` go to its ``arrive``."""

    def error(self, message: str) -> None: ...
