from __future__ import annotations

import time

from core.delivery.chat_platform_bridge import TelegramChatBridge, WeChatChatBridge, stop_chat_platform_bridge
from core.delivery.messaging import MessagingConfig
from core.delivery.messaging.telegram_discovery import discover_next_private_chat_id, private_chat_candidate
from core.delivery.messaging.wechat_openclaw.models import WeChatInboundMessage


class SlowBridge:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self, *, wait: bool = False) -> None:
        self.stopped = True
        if wait:
            time.sleep(0.2)


def test_stop_chat_platform_bridge_is_non_blocking_by_default():
    bridge = SlowBridge()
    start = time.perf_counter()

    stop_chat_platform_bridge(bridge)

    assert bridge.stopped is True
    assert time.perf_counter() - start < 0.1


def test_telegram_bridge_accepts_chat_id_alias(monkeypatch):
    calls = []
    handled_targets = []

    class Response:
        def __init__(self, data):
            self._data = data

        def json(self):
            return self._data

    responses = [
        {"ok": True, "result": []},
        {
            "ok": True,
            "result": [
                {
                    "update_id": 7,
                    "message": {
                        "chat": {"id": 12345},
                        "text": "hello",
                    },
                }
            ],
        },
    ]

    def fake_get(url, **kwargs):
        calls.append(kwargs)
        return Response(responses.pop(0))

    monkeypatch.setattr("core.delivery.chat_platform_bridge.requests.get", fake_get)
    bridge = TelegramChatBridge(
        config=MessagingConfig({"telegram": {"token": "token", "chat_id": "12345"}}),
        emit_user_text=lambda _: None,
    )

    def fake_handle_update(update, target):
        handled_targets.append(target)
        bridge._stop_event.set()

    monkeypatch.setattr(bridge, "_handle_update", fake_handle_update)

    bridge._run()

    assert calls[1]["params"]["offset"] == 0
    assert handled_targets == ["12345"]


def test_telegram_discovery_uses_next_private_message(monkeypatch):
    calls = []
    responses = [
        {"ok": True, "result": [{"update_id": 10, "message": {"chat": {"id": 1, "type": "private"}}}]},
        {
            "ok": True,
            "result": [
                {"update_id": 11, "message": {"chat": {"id": -99, "type": "group"}, "text": "ignored"}},
                {
                    "update_id": 12,
                    "message": {
                        "chat": {
                            "id": 12345,
                            "type": "private",
                            "first_name": "Ada",
                            "username": "ada_here",
                        },
                        "text": "bind",
                    },
                },
            ],
        },
        {"ok": True, "result": []},
    ]

    class Response:
        def __init__(self, data):
            self._data = data

        def json(self):
            return self._data

    def fake_get(url, **kwargs):
        calls.append(kwargs)
        return Response(responses.pop(0))

    monkeypatch.setattr("core.delivery.messaging.telegram_discovery.time.monotonic", lambda: 0)

    result = discover_next_private_chat_id("token", request_get=fake_get)

    assert result.chat_id == "12345"
    assert "Ada @ada_here" in result.description
    assert calls[0]["params"]["timeout"] == 0
    assert calls[1]["params"]["offset"] == 11
    assert calls[2]["params"]["offset"] == 13


def test_telegram_private_chat_candidate_ignores_groups():
    candidate = private_chat_candidate({
        "update_id": 1,
        "message": {
            "chat": {"id": -100, "type": "group"},
            "text": "hello",
        },
    })

    assert candidate is None


def test_wechat_bridge_filters_inbound_messages_by_configured_target():
    emitted = []
    bridge = WeChatChatBridge(
        config=MessagingConfig({"wechat": {"target": "user-b"}}),
        emit_user_text=emitted.append,
    )

    bridge._on_message(WeChatInboundMessage(from_user_id="user-a", text="from A"))
    bridge._on_message(WeChatInboundMessage(from_user_id="user-b", text="from B"))

    assert emitted == ["from B"]


def test_wechat_bridge_does_not_start_without_target(monkeypatch):
    started = False
    notices = []

    def fake_start_saved_accounts(**_kwargs):
        nonlocal started
        started = True
        return []

    monkeypatch.setattr(
        "core.delivery.chat_platform_bridge.monitor_manager.start_saved_accounts",
        fake_start_saved_accounts,
    )
    bridge = WeChatChatBridge(
        config=MessagingConfig({"wechat": {"enabled": True}}),
        emit_user_text=lambda _: None,
        notify=notices.append,
    )

    bridge.start()

    assert started is False
    assert notices
