from __future__ import annotations

from typing import Any

from core.delivery.messaging import CHANNEL_LABELS, MessagingCapabilityProbe, MessagingConfig
from core.delivery.models import EXTERNAL_CHANNELS, DeliveryCapability


class DeliveryCapabilityProbe:
    """Detect safe delivery capabilities without sending any external message."""

    def __init__(self, config_manager: Any | None = None) -> None:
        self.config_manager = config_manager

    def probe(self) -> dict[str, DeliveryCapability]:
        messaging_caps = MessagingCapabilityProbe(MessagingConfig.auto_load()).probe()
        capabilities: dict[str, DeliveryCapability] = {}
        for channel in ("desktop_chat", *EXTERNAL_CHANNELS):
            cap = messaging_caps.get(channel)
            if cap is None:
                supported = False
                configured = False
                available = False
                reason = "unsupported"
            else:
                supported = cap.supported
                configured = cap.configured
                available = cap.available
                reason = cap.reason
            capabilities[channel] = DeliveryCapability(
                channel=channel,
                label=CHANNEL_LABELS.get(channel, channel),
                supported=supported,
                configured=configured,
                available=available,
                reason=reason,
            )
        return capabilities
