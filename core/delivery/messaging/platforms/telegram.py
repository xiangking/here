from __future__ import annotations

from pathlib import Path

import requests

from core.delivery.messaging.models import SendResult
from core.delivery.messaging.platforms.base import BaseMessagePlatform


class TelegramMessagePlatform(BaseMessagePlatform):
    channel = "telegram"
    label = "Telegram"
    required_fields = ("token",)
    target_fields = ("target", "chat_id", "recipient")

    def send(self, *, target: str, text: str) -> SendResult:
        token = self._value("token")
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        return self._post_json(
            url,
            {
                "chat_id": target,
                "text": text,
                "disable_web_page_preview": True,
            },
        )

    def send_image(self, *, target: str, image_path: str, caption: str = "") -> SendResult:
        token = self._value("token")
        path = Path(image_path).expanduser()
        if not path.is_file():
            return SendResult(self.channel, "failed", "missing_image")
        url = f"https://api.telegram.org/bot{token}/sendPhoto"
        return self._post_file(url, field="photo", path=path, data={"chat_id": target, "caption": caption[:1024]})

    def send_audio(self, *, target: str, audio_path: str, caption: str = "") -> SendResult:
        token = self._value("token")
        path = Path(audio_path).expanduser()
        if not path.is_file():
            return SendResult(self.channel, "failed", "missing_audio")
        method = "sendVoice" if path.suffix.lower() in {".ogg", ".oga", ".opus"} else "sendAudio"
        field = "voice" if method == "sendVoice" else "audio"
        url = f"https://api.telegram.org/bot{token}/{method}"
        return self._post_file(url, field=field, path=path, data={"chat_id": target, "caption": caption[:1024]})

    def _api_error(self, response) -> str:
        try:
            data = response.json()
        except ValueError:
            return ""
        if isinstance(data, dict) and data.get("ok") is False:
            return f"telegram_error:{data.get('description') or data}"
        return ""

    def _post_file(self, url: str, *, field: str, path: Path, data: dict[str, str]) -> SendResult:
        try:
            with path.open("rb") as handle:
                response = requests.post(
                    url,
                    data=data,
                    files={field: (path.name, handle)},
                    timeout=float(self.config.get("timeout") or 60),
                    verify=self._verify(),
                    proxies=self._proxies(),
                )
        except requests.RequestException as exc:
            return SendResult(self.channel, "failed", f"request_error:{exc.__class__.__name__}")
        if response.status_code in (200, 201, 202):
            api_error = self._api_error(response)
            if api_error:
                return SendResult(self.channel, "failed", api_error)
            return SendResult(self.channel, "sent", message_id=self._message_id(response))
        retryable = "retryable" if response.status_code in self.retryable_statuses else "http_error"
        return SendResult(self.channel, "failed", f"{retryable}:{response.status_code}")
