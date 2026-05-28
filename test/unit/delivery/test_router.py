from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from services.config.schema import SystemConfig
from core.delivery.models import DeliveryCapability
from core.delivery.router import DeliveryRouter


class StaticProbe:
    def __init__(self, caps):
        self.caps = caps
        self.called = False

    def probe(self):
        self.called = True
        return self.caps


def _config(system_config: SystemConfig):
    cfg = MagicMock()
    cfg.config.system_config = system_config
    return cfg


def test_router_uses_desktop_when_external_disabled():
    probe = StaticProbe({})
    router = DeliveryRouter(
        _config(SystemConfig(proactive_contact_enabled=True, external_delivery_enabled=False)),
        probe,
    )

    route = router.route(now=datetime(2026, 5, 26, 12, 0))

    assert route.allowed is True
    assert route.channel == "desktop_chat"
    assert probe.called is False


def test_router_blocks_when_proactive_disabled():
    router = DeliveryRouter(
        _config(SystemConfig(proactive_contact_enabled=False, external_delivery_enabled=True)),
        StaticProbe({}),
    )

    route = router.route(now=datetime(2026, 5, 26, 12, 0))

    assert route.allowed is False
    assert route.channel == "none"


def test_router_falls_back_when_selected_channel_unavailable():
    router = DeliveryRouter(
        _config(SystemConfig(
            proactive_contact_enabled=True,
            external_delivery_enabled=True,
            external_delivery_channel="telegram",
        )),
        StaticProbe({
            "telegram": DeliveryCapability("telegram", "Telegram", True, False, False, "missing_config")
        }),
    )

    route = router.route(now=datetime(2026, 5, 26, 12, 0))

    assert route.channel == "desktop_chat"
    assert route.reason == "missing_config"


def test_router_allows_available_external_channel():
    router = DeliveryRouter(
        _config(SystemConfig(
            proactive_contact_enabled=True,
            external_delivery_enabled=True,
            external_delivery_channel="telegram",
        )),
        StaticProbe({
            "telegram": DeliveryCapability("telegram", "Telegram", True, True, True, "ready")
        }),
    )

    route = router.route(now=datetime(2026, 5, 26, 12, 0))

    assert route.channel == "telegram"
    assert route.requires_confirmation is True


def test_chat_response_uses_chat_delivery_channel_not_proactive_channel():
    router = DeliveryRouter(
        _config(SystemConfig(
            proactive_contact_enabled=True,
            external_delivery_enabled=True,
            external_delivery_channel="desktop_chat",
            chat_delivery_channel="telegram",
        )),
        StaticProbe({
            "telegram": DeliveryCapability("telegram", "Telegram", True, True, True, "ready")
        }),
    )

    route = router.route_chat_response()

    assert route.channel == "telegram"
    assert route.requires_confirmation is False


def test_chat_response_allows_any_configured_delivery_channel():
    router = DeliveryRouter(
        _config(SystemConfig(chat_delivery_channel="feishu")),
        StaticProbe({
            "feishu": DeliveryCapability("feishu", "Feishu", True, True, True, "ready")
        }),
    )

    route = router.route_chat_response()

    assert route.channel == "feishu"
