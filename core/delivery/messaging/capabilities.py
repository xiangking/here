from __future__ import annotations

from core.delivery.messaging.config import MessagingConfig
from core.delivery.messaging.models import CHANNEL_LABELS, ChannelCapability
from core.delivery.messaging.sender import create_default_registry


class MessagingCapabilityProbe:
    def __init__(self, config: MessagingConfig | None = None) -> None:
        self.config = config or MessagingConfig.auto_load()
        self.registry = create_default_registry(emit_dialog=lambda _: None)

    def probe(self) -> dict[str, ChannelCapability]:
        capabilities: dict[str, ChannelCapability] = {}
        for channel in self.registry.channels():
            supported = True
            try:
                adapter = self.registry.create(channel, self.config.platform(channel))
                configured, reason = adapter.configured()
            except Exception as exc:
                supported = False
                configured = False
                reason = str(exc) or "unsupported"
            if channel != "desktop_chat" and not self.config.enabled(channel):
                configured = False
                reason = "disabled"
            capabilities[channel] = ChannelCapability(
                channel=channel,
                label=CHANNEL_LABELS.get(channel, channel),
                supported=supported,
                configured=configured,
                available=bool(supported and configured),
                reason=reason,
            )
        return capabilities
