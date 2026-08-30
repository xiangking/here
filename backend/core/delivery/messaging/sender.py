from __future__ import annotations

from typing import Callable

from core.delivery.messaging.config import MessagingConfig
from core.delivery.messaging.models import MessagePayload, SendResult
from core.delivery.messaging.platforms import (
    DesktopMessagePlatform,
    DiscordMessagePlatform,
    FeishuMessagePlatform,
    TelegramMessagePlatform,
    WeChatMessagePlatform,
    WhatsAppMessagePlatform,
)
from core.delivery.messaging.registry import MessagingRegistry
from core.messaging.messages import AgentDialogMessage


MAX_LENGTHS = {
    "desktop_chat": 10**9,
    "telegram": 4096,
    "discord": 2000,
    "wechat": 4000,
    "feishu": 10000,
    "whatsapp": 4096,
}

LENGTH_UNITS = {
    "telegram": "utf16",
    "discord": "utf16",
    "whatsapp": "utf8",
}


def create_default_registry(
    emit_dialog: Callable[[AgentDialogMessage], None] | None = None,
) -> MessagingRegistry:
    registry = MessagingRegistry()

    class BoundDesktopMessagePlatform(DesktopMessagePlatform):
        def __init__(self, config=None):
            super().__init__(config, emit_dialog=emit_dialog)

    registry.register("desktop_chat", BoundDesktopMessagePlatform)
    registry.register("telegram", TelegramMessagePlatform)
    registry.register("discord", DiscordMessagePlatform)
    registry.register("wechat", WeChatMessagePlatform)
    registry.register("feishu", FeishuMessagePlatform)
    registry.register("whatsapp", WhatsAppMessagePlatform)
    return registry


class MessageSender:
    def __init__(
        self,
        config: MessagingConfig | None = None,
        registry: MessagingRegistry | None = None,
    ) -> None:
        self.config = config or MessagingConfig.auto_load()
        self.registry = registry or create_default_registry()

    def send(self, *, channel: str, payload: MessagePayload, target: str = "") -> SendResult:
        normalized = str(channel or "").strip().lower()
        text = str(payload.text or "").strip()
        image_path = str(payload.image_path or "").strip()
        audio_path = str(payload.audio_path or "").strip()
        if not text and not image_path and not audio_path:
            return SendResult(normalized or "none", "skipped", "empty_message")
        try:
            cfg = self.config.platform(normalized)
            if normalized == "desktop_chat":
                cfg.update({
                    "character_name": payload.character_name,
                    "emotion": (payload.metadata or {}).get("emotion", "neutral"),
                })
            adapter = self.registry.create(normalized, cfg)
        except KeyError:
            return SendResult(normalized or "none", "failed", "unsupported")
        if normalized != "desktop_chat" and not self.config.enabled(normalized):
            return SendResult(normalized, "failed", "disabled")
        configured, reason = adapter.configured()
        if not configured:
            return SendResult(normalized, "failed", reason)
        recipient = str(target or adapter.default_target()).strip()
        result = SendResult(normalized, "sent")
        if image_path:
            result = adapter.send_image(target=recipient, image_path=image_path, caption=text)
            if result.status != "sent":
                return result
        if audio_path:
            result = adapter.send_audio(target=recipient, audio_path=audio_path, caption=text if not image_path else "")
            if result.status != "sent":
                return result
        if not text or image_path or audio_path:
            return result
        chunks = [text] if normalized == "desktop_chat" else _chunk_message(
            text,
            MAX_LENGTHS.get(normalized, 10000),
            unit=LENGTH_UNITS.get(normalized, "codepoint"),
        )
        for chunk in chunks:
            result = adapter.send(target=recipient, text=chunk)
            if result.status != "sent":
                return result
        return result


def _chunk_message(message: str, max_length: int, *, unit: str = "codepoint") -> list[str]:
    length = _length_fn(unit)
    if length(message) <= max_length:
        return [message]
    chunks: list[str] = []
    text = message
    reserved = 24
    limit = max(1, max_length - reserved)
    while text:
        chunk = _take_prefix(text, limit, length)
        split_at = chunk.rfind("\n")
        if split_at > 0 and length(chunk[:split_at]) > int(limit * 0.65):
            chunk = chunk[:split_at]
        chunks.append(chunk)
        text = text[len(chunk) :].lstrip()
    total = len(chunks)
    return [f"[Part {index + 1}/{total}]\n{chunk}" for index, chunk in enumerate(chunks)]


def _length_fn(unit: str):
    if unit == "utf16":
        return lambda text: len(text.encode("utf-16-le")) // 2
    if unit == "utf8":
        return lambda text: len(text.encode("utf-8"))
    return len


def _take_prefix(text: str, limit: int, length) -> str:
    total = 0
    out: list[str] = []
    for char in text:
        char_len = length(char)
        if out and total + char_len > limit:
            break
        out.append(char)
        total += char_len
        if total >= limit:
            break
    return "".join(out) or text[:1]
