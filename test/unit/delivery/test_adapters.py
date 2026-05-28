from __future__ import annotations

from core.delivery import DeliveryMessage, DesktopDeliveryAdapter, MessagingDeliveryAdapter
from core.delivery.messaging import SendResult
from core.messaging.messages import AgentDialogMessage


def test_desktop_adapter_only_emits_dialog():
    out = []
    adapter = DesktopDeliveryAdapter(out.append)
    dialog = AgentDialogMessage(name="Alice", text="hi")

    result = adapter.send(DeliveryMessage(dialog, "Alice", "desktop_chat"))

    assert result.status == "sent"
    assert out == [dialog]


def test_messaging_adapter_delegates_to_local_sender():
    class Sender:
        def __init__(self):
            self.calls = []

        def send(self, **kwargs):
            self.calls.append(kwargs)
            return SendResult(channel="telegram", status="sent", message_id="m1")

    sender = Sender()
    adapter = MessagingDeliveryAdapter(sender)
    dialog = AgentDialogMessage(name="Alice", text="hello")

    result = adapter.send(DeliveryMessage(dialog, "Alice", "telegram"))

    assert result.status == "sent"
    assert result.message_id == "m1"
    call = sender.calls[0]
    assert call["channel"] == "telegram"
    assert call["payload"].text == "hello"
    assert call["payload"].character_name == "Alice"


def test_messaging_adapter_passes_media_paths():
    class Sender:
        def __init__(self):
            self.calls = []

        def send(self, **kwargs):
            self.calls.append(kwargs)
            return SendResult(channel="telegram", status="sent", message_id="m1")

    sender = Sender()
    adapter = MessagingDeliveryAdapter(sender)
    dialog = AgentDialogMessage(name="Alice", text="hello")

    result = adapter.send(
        DeliveryMessage(
            dialog,
            "Alice",
            "telegram",
            image_path="/tmp/pic.png",
            audio_path="/tmp/voice.wav",
        )
    )

    assert result.status == "sent"
    payload = sender.calls[0]["payload"]
    assert payload.image_path == "/tmp/pic.png"
    assert payload.audio_path == "/tmp/voice.wav"
