"""Delivery routing, capability probing, and adapters."""

from core.delivery.adapters import DeliveryAdapterRegistry, DesktopDeliveryAdapter, MessagingDeliveryAdapter
from core.delivery.capabilities import DeliveryCapabilityProbe
from core.delivery.models import (
    DeliveryCapability,
    DeliveryMessage,
    DeliveryResult,
    DeliveryRoute,
)
from core.delivery.router import DeliveryRouter

__all__ = [
    "DeliveryAdapterRegistry",
    "DeliveryCapability",
    "DeliveryCapabilityProbe",
    "DeliveryMessage",
    "DeliveryResult",
    "DeliveryRoute",
    "DeliveryRouter",
    "DesktopDeliveryAdapter",
    "MessagingDeliveryAdapter",
]
