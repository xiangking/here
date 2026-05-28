from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


CHANNEL_LABELS = {
    "desktop_chat": "Desktop Chat",
    "telegram": "Telegram",
    "discord": "Discord",
    "wechat": "WeChat",
    "feishu": "Feishu",
    "whatsapp": "WhatsApp",
}


@dataclass(frozen=True)
class MessagePayload:
    text: str
    character_name: str = ""
    image_path: str = ""
    audio_path: str = ""
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class SendResult:
    channel: str
    status: Literal["sent", "failed", "skipped"]
    reason: str = "sent"
    message_id: str = ""


@dataclass(frozen=True)
class ChannelCapability:
    channel: str
    label: str
    supported: bool
    configured: bool
    available: bool
    reason: str = "ready"
