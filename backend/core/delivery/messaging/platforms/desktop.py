from __future__ import annotations

from typing import Any, Callable

from core.delivery.messaging.models import SendResult
from core.delivery.messaging.platforms.base import BaseMessagePlatform
from core.messaging.messages import AgentDialogMessage


class DesktopMessagePlatform(BaseMessagePlatform):
    channel = "desktop_chat"
    label = "Desktop Chat"
    target_required = False

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        emit_dialog: Callable[[AgentDialogMessage], None] | None = None,
    ) -> None:
        super().__init__(config)
        self.emit_dialog = emit_dialog

    def configured(self) -> tuple[bool, str]:
        return (self.emit_dialog is not None, "ready" if self.emit_dialog is not None else "missing_emit_dialog")

    def send(self, *, target: str, text: str) -> SendResult:
        if self.emit_dialog is None:
            return SendResult(self.channel, "failed", "missing_emit_dialog")
        character_name = self._value("character_name") or "assistant"
        emotion = self._value("emotion") or "neutral"
        self.emit_dialog(AgentDialogMessage(name=character_name, text=text, emotion=emotion))
        return SendResult(self.channel, "sent")
