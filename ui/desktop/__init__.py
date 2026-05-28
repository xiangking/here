"""Desktop chat UI package."""

from __future__ import annotations

import importlib
from typing import Any

from ui.desktop.character_entry import CharacterEntrySprite, character_entry_line, character_entry_sprite
from ui.desktop.chat_ui import ChatUIWindow
from ui.desktop.signal_bridge import (
    ChatUISignalBridge,
    attach_chat_ui_window,
    detach_chat_ui_window,
    get_chat_ui_signal_bridge,
)

__all__ = [
    "ChatUIWindow",
    "CharacterEntrySprite",
    "character_entry_line",
    "character_entry_sprite",
    "ChatUIContext",
    "ChatUISignalBridge",
    "attach_chat_ui_window",
    "detach_chat_ui_window",
    "get_chat_ui_context",
    "get_chat_ui_signal_bridge",
    "set_chat_ui_context",
    "try_get_chat_ui_context",
]

_CTX_NAMES = frozenset({
    "ChatUIContext",
    "get_chat_ui_context",
    "set_chat_ui_context",
    "try_get_chat_ui_context",
})


def __getattr__(name: str) -> Any:
    if name in _CTX_NAMES:
        mod = importlib.import_module("app.desktop.ui_context")
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
