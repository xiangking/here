from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from core.messaging.messages import AgentDialogMessage


EXTERNAL_CHANNELS = ("telegram", "discord", "wechat", "feishu", "whatsapp")
DELIVERY_CHANNELS = ("desktop_chat", *EXTERNAL_CHANNELS)


@dataclass(frozen=True)
class DeliveryCapability:
    channel: str
    label: str
    supported: bool
    configured: bool
    available: bool
    reason: str = "ready"

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "label": self.label,
            "supported": self.supported,
            "configured": self.configured,
            "available": self.available,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class DeliveryRoute:
    allowed: bool
    channel: str = "none"
    reason: str = "disabled"
    requires_confirmation: bool = False


@dataclass(frozen=True)
class DeliveryMessage:
    dialog: AgentDialogMessage
    character_name: str
    target_channel: str
    recipient: str = ""
    image_path: str = ""
    audio_path: str = ""


@dataclass(frozen=True)
class DeliveryResult:
    channel: str
    status: Literal["sent", "failed", "skipped"]
    reason: str = "sent"
    message_id: str = ""
