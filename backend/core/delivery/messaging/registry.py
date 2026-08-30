from __future__ import annotations

from typing import Any

from core.delivery.messaging.platforms.base import BaseMessagePlatform


class MessagingRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, type[BaseMessagePlatform]] = {}

    def register(self, channel: str, adapter: type[BaseMessagePlatform]) -> None:
        self._adapters[str(channel or "").strip().lower()] = adapter

    def create(self, channel: str, config: dict[str, Any] | None = None) -> BaseMessagePlatform:
        normalized = str(channel or "").strip().lower()
        if normalized not in self._adapters:
            raise KeyError(normalized)
        return self._adapters[normalized](config or {})

    def channels(self) -> tuple[str, ...]:
        return tuple(self._adapters)
