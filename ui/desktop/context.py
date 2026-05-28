"""向后兼容：自 :mod:`app.desktop.ui_context` 重新导出。"""

from app.desktop.ui_context import (
    ChatUIContext,
    _ChatUIActions,
    get_chat_ui_context,
    set_chat_ui_context,
    try_get_chat_ui_context,
)

__all__ = [
    "ChatUIContext",
    "_ChatUIActions",
    "get_chat_ui_context",
    "set_chat_ui_context",
    "try_get_chat_ui_context",
]
