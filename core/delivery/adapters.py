from __future__ import annotations

from typing import Callable

from core.delivery.models import DeliveryMessage, DeliveryResult
from core.delivery.messaging import MessagePayload, MessageSender
from core.messaging.messages import AgentDialogMessage


class DesktopDeliveryAdapter:
    def __init__(self, emit_dialog: Callable[[AgentDialogMessage], None]) -> None:
        self.emit_dialog = emit_dialog

    def send(self, message: DeliveryMessage) -> DeliveryResult:
        self.emit_dialog(message.dialog)
        return DeliveryResult(channel="desktop_chat", status="sent")


class MessagingDeliveryAdapter:
    """External delivery through Here's local messaging module."""

    def __init__(self, sender: MessageSender) -> None:
        self.sender = sender

    def send(self, message: DeliveryMessage) -> DeliveryResult:
        text = str(message.dialog.text or "").strip()
        image_path = str(message.image_path or "").strip()
        audio_path = str(message.audio_path or "").strip()
        if not text and not image_path and not audio_path:
            return DeliveryResult(message.target_channel, "skipped", "empty_message")
        result = self.sender.send(
            channel=message.target_channel,
            target=message.recipient,
            payload=MessagePayload(
                text=text,
                character_name=message.character_name,
                image_path=image_path,
                audio_path=audio_path,
                metadata={"emotion": getattr(message.dialog, "emotion", "neutral")},
            ),
        )
        return DeliveryResult(result.channel, result.status, result.reason, result.message_id)


class DeliveryAdapterRegistry:
    def __init__(self, desktop_adapter: DesktopDeliveryAdapter, external_adapter: MessagingDeliveryAdapter | None = None) -> None:
        self.desktop_adapter = desktop_adapter
        self.external_adapter = external_adapter

    def send(self, message: DeliveryMessage) -> DeliveryResult:
        if message.target_channel == "desktop_chat" or self.external_adapter is None:
            return self.desktop_adapter.send(message)
        return self.external_adapter.send(message)
