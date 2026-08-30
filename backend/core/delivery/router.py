from __future__ import annotations

from datetime import datetime, time
from typing import Any

from core.delivery.capabilities import DeliveryCapabilityProbe
from core.delivery.models import DELIVERY_CHANNELS, DeliveryCapability, DeliveryRoute


class DeliveryRouter:
    """Pure routing policy. It does not send messages."""

    def __init__(self, config_manager: Any, capability_probe: DeliveryCapabilityProbe | None = None) -> None:
        self.config_manager = config_manager
        self.capability_probe = capability_probe or DeliveryCapabilityProbe(config_manager)

    def route(self, *, now: datetime | None = None) -> DeliveryRoute:
        system = self.config_manager.config.system_config
        if not bool(getattr(system, "proactive_contact_enabled", False)):
            return DeliveryRoute(False, "none", "proactive_contact_disabled", False)
        if not bool(getattr(system, "external_delivery_enabled", False)):
            return DeliveryRoute(True, "desktop_chat", "external_delivery_disabled", False)
        channel = _normalize_channel(getattr(system, "external_delivery_channel", "desktop_chat"))
        if channel == "desktop_chat":
            return DeliveryRoute(True, "desktop_chat", "desktop_selected", False)
        if _in_quiet_hours(now or datetime.now(), str(getattr(system, "external_delivery_quiet_hours", "") or "")):
            return DeliveryRoute(True, "desktop_chat", "quiet_hours_fallback", False)
        capabilities = self.capability_probe.probe()
        capability = capabilities.get(channel)
        if capability is None or not capability.available:
            return DeliveryRoute(True, "desktop_chat", capability.reason if capability else "channel_unavailable", False)
        return DeliveryRoute(
            True,
            channel,
            "external_available",
            bool(getattr(system, "external_delivery_requires_confirmation", True)),
        )

    def route_chat_response(self) -> DeliveryRoute:
        """Route normal user-initiated chat replies.

        Unlike proactive contact, an active chat reply should follow the user's
        selected delivery channel immediately and should not be blocked by
        proactive-contact enablement, quiet hours, confirmation, or daily limits.
        """
        system = self.config_manager.config.system_config
        channel = _normalize_channel(getattr(system, "chat_delivery_channel", "desktop_chat"))
        if channel == "desktop_chat":
            return DeliveryRoute(True, "desktop_chat", "desktop_selected", False)
        capabilities = self.capability_probe.probe()
        capability = capabilities.get(channel)
        if capability is None or not capability.available:
            return DeliveryRoute(True, "desktop_chat", capability.reason if capability else "channel_unavailable", False)
        return DeliveryRoute(True, channel, "external_available", False)


def _normalize_channel(value: str) -> str:
    channel = str(value or "").strip().lower()
    if channel in DELIVERY_CHANNELS:
        return channel
    return "desktop_chat"


def _in_quiet_hours(now: datetime, quiet_hours: str) -> bool:
    text = quiet_hours.strip()
    if not text or "-" not in text:
        return False
    start_s, end_s = [part.strip() for part in text.split("-", 1)]
    start = _parse_hhmm(start_s)
    end = _parse_hhmm(end_s)
    if start is None or end is None:
        return False
    cur = now.timetz().replace(tzinfo=None)
    cur_m = cur.hour * 60 + cur.minute
    start_m = start.hour * 60 + start.minute
    end_m = end.hour * 60 + end.minute
    if end_m <= start_m:
        return cur_m >= start_m or cur_m < end_m
    return start_m <= cur_m < end_m


def _parse_hhmm(value: str) -> time | None:
    try:
        hour, minute = value.split(":", 1)
        return time(int(hour), int(minute))
    except Exception:
        return None
