"""Desktop lifecycle helpers."""

from __future__ import annotations

from typing import Any


def connect_desktop_shutdown(app: Any, callbacks: list[Any]) -> None:
    for callback in callbacks:
        app.aboutToQuit.connect(callback)
