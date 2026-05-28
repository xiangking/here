from __future__ import annotations

from core.delivery.messaging.models import SendResult
from core.delivery.messaging.platforms.base import BaseMessagePlatform


class WhatsAppMessagePlatform(BaseMessagePlatform):
    channel = "whatsapp"
    label = "WhatsApp"
    required_fields = ("api_token", "phone_number_id")
    target_fields = ("target", "recipient")

    def send(self, *, target: str, text: str) -> SendResult:
        api_version = self._value("api_version") or "v20.0"
        url = f"https://graph.facebook.com/{api_version}/{self._value('phone_number_id')}/messages"
        return self._post_json(
            url,
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": target,
                "type": "text",
                "text": {"body": text},
            },
            headers={"Authorization": f"Bearer {self._value('api_token')}", "Content-Type": "application/json"},
        )

    def _api_error(self, response) -> str:
        try:
            data = response.json()
        except ValueError:
            return ""
        if isinstance(data, dict) and "error" in data:
            return f"whatsapp_error:{data['error']}"
        return ""
