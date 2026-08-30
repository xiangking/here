from __future__ import annotations

from core.delivery.messaging.models import SendResult
from core.delivery.messaging.platforms.base import BaseMessagePlatform


class DiscordMessagePlatform(BaseMessagePlatform):
    channel = "discord"
    label = "Discord"
    required_fields = ("bot_token",)
    target_fields = ("target", "user_id", "recipient")
    target_required = True

    def configured(self) -> tuple[bool, str]:
        return super().configured()

    def send(self, *, target: str, text: str) -> SendResult:
        token = self._value("bot_token")
        headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
        dm = self._post_json(
            "https://discord.com/api/v10/users/@me/channels",
            {"recipient_id": target},
            headers=headers,
        )
        if dm.status != "sent" or not dm.message_id:
            return dm
        return self._post_json(
            f"https://discord.com/api/v10/channels/{dm.message_id}/messages",
            {"content": text},
            headers=headers,
        )
