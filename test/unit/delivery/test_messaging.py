from __future__ import annotations

import yaml

from core.delivery.messaging import MessagePayload, MessageSender, MessagingConfig
from core.delivery.messaging.platforms.discord import DiscordMessagePlatform
from core.delivery.messaging.platforms.feishu import FeishuMessagePlatform
from core.delivery.messaging.platforms.telegram import TelegramMessagePlatform
from core.delivery.messaging.platforms.whatsapp import WhatsAppMessagePlatform
from core.delivery.messaging.platforms.wechat import WeChatMessagePlatform
from core.delivery.messaging.wechat_openclaw import api as wechat_api
from core.delivery.messaging.wechat_openclaw.models import WeChatAccount
from core.delivery.messaging.sender import create_default_registry


def test_sender_sends_desktop_message():
    out = []
    sender = MessageSender(
        config=MessagingConfig({}),
        registry=create_default_registry(out.append),
    )

    result = sender.send(
        channel="desktop_chat",
        payload=MessagePayload(text="hi", character_name="Alice"),
    )

    assert result.status == "sent"
    assert out[0].name == "Alice"
    assert out[0].text == "hi"


def test_sender_rejects_disabled_external_channel():
    sender = MessageSender(
        config=MessagingConfig({"telegram": {"enabled": False, "token": "t", "target": "123"}}),
        registry=create_default_registry(lambda _: None),
    )

    result = sender.send(channel="telegram", payload=MessagePayload(text="hi"))

    assert result.status == "failed"
    assert result.reason == "disabled"


def test_messaging_config_can_save_platform_settings(tmp_path):
    path = tmp_path / "messaging.yaml"
    config = MessagingConfig({"telegram": {"enabled": False}})

    config.set_platform("telegram", {"enabled": True, "token": "t", "target": "123"})
    config.save(path)

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["telegram"]["enabled"] is True
    assert data["telegram"]["token"] == "t"
    assert data["telegram"]["target"] == "123"


def test_sender_posts_to_telegram(monkeypatch):
    calls = []

    class Response:
        status_code = 200
        text = "{}"

        def json(self):
            return {"ok": True, "result": {"message_id": 42}}

    def fake_post(url, **kwargs):
        calls.append({"url": url, "kwargs": kwargs})
        return Response()

    monkeypatch.setattr("requests.post", fake_post)
    sender = MessageSender(
        config=MessagingConfig({"telegram": {"enabled": True, "token": "token", "target": "123"}}),
        registry=create_default_registry(lambda _: None),
    )

    result = sender.send(channel="telegram", payload=MessagePayload(text="hi"))

    assert result.status == "sent"
    assert result.message_id == "42"
    assert calls[0]["url"] == "https://api.telegram.org/bottoken/sendMessage"
    assert calls[0]["kwargs"]["json"]["chat_id"] == "123"


def test_sender_posts_telegram_photo(monkeypatch, tmp_path):
    calls = []
    image = tmp_path / "pic.png"
    image.write_bytes(b"png")

    class Response:
        status_code = 200
        text = "{}"

        def json(self):
            return {"ok": True, "result": {"message_id": 43}}

    def fake_post(url, **kwargs):
        calls.append({"url": url, "kwargs": kwargs})
        return Response()

    monkeypatch.setattr("requests.post", fake_post)
    sender = MessageSender(
        config=MessagingConfig({"telegram": {"enabled": True, "token": "token", "target": "123"}}),
        registry=create_default_registry(lambda _: None),
    )

    result = sender.send(channel="telegram", payload=MessagePayload(text="caption", image_path=str(image)))

    assert result.status == "sent"
    assert calls[0]["url"] == "https://api.telegram.org/bottoken/sendPhoto"
    assert calls[0]["kwargs"]["data"]["caption"] == "caption"
    assert "photo" in calls[0]["kwargs"]["files"]


def test_sender_posts_telegram_audio(monkeypatch, tmp_path):
    calls = []
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"wav")

    class Response:
        status_code = 200
        text = "{}"

        def json(self):
            return {"ok": True, "result": {"message_id": 44}}

    def fake_post(url, **kwargs):
        calls.append({"url": url, "kwargs": kwargs})
        return Response()

    monkeypatch.setattr("requests.post", fake_post)
    sender = MessageSender(
        config=MessagingConfig({"telegram": {"enabled": True, "token": "token", "target": "123"}}),
        registry=create_default_registry(lambda _: None),
    )

    result = sender.send(channel="telegram", payload=MessagePayload(text="caption", audio_path=str(audio)))

    assert result.status == "sent"
    assert calls[0]["url"] == "https://api.telegram.org/bottoken/sendAudio"
    assert "audio" in calls[0]["kwargs"]["files"]


def test_desktop_channel_is_not_chunked():
    out = []
    sender = MessageSender(
        config=MessagingConfig({}),
        registry=create_default_registry(out.append),
    )

    result = sender.send(
        channel="desktop_chat",
        payload=MessagePayload(text="x" * 12000, character_name="Alice"),
    )

    assert result.status == "sent"
    assert len(out) == 1
    assert out[0].text == "x" * 12000


def test_discord_bot_requires_discord_user_id_target_field():
    adapter = DiscordMessagePlatform({"bot_token": "bot", "phone_number": "123"})

    configured, reason = adapter.configured()

    assert configured is False
    assert reason == "missing_target"


def test_discord_bot_sends_dm_to_user(monkeypatch):
    calls = []

    class Response:
        status_code = 200
        text = "{}"

        def __init__(self, data):
            self._data = data

        def json(self):
            return self._data

    def fake_post(url, **kwargs):
        calls.append({"url": url, "kwargs": kwargs})
        if url.endswith("/users/@me/channels"):
            return Response({"id": "dm-channel"})
        return Response({"id": "message-id"})

    monkeypatch.setattr("requests.post", fake_post)
    adapter = DiscordMessagePlatform({"bot_token": "bot", "target": "user-id"})

    result = adapter.send(target="user-id", text="hi")

    assert result.status == "sent"
    assert calls[0]["url"] == "https://discord.com/api/v10/users/@me/channels"
    assert calls[0]["kwargs"]["json"] == {"recipient_id": "user-id"}
    assert calls[1]["url"] == "https://discord.com/api/v10/channels/dm-channel/messages"


def test_feishu_receive_id_type_uses_config_before_prefix_magic():
    adapter = FeishuMessagePlatform({"receive_id_type": "union_id"})

    assert adapter._receive_id_type("plain-union-id") == "union_id"


def test_feishu_receive_id_type_infers_only_known_prefixes():
    adapter = FeishuMessagePlatform({})

    assert adapter._receive_id_type("ou_user") == "open_id"
    assert adapter._receive_id_type("person@example.com") == "email"
    assert adapter._receive_id_type("plain") == "open_id"


def test_whatsapp_uses_configurable_api_version_and_target_not_phone_number(monkeypatch):
    calls = []

    class Response:
        status_code = 200
        text = "{}"

        def json(self):
            return {"messages": [{"id": "wamid"}]}

    def fake_post(url, **kwargs):
        calls.append({"url": url, "kwargs": kwargs})
        return Response()

    monkeypatch.setattr("requests.post", fake_post)
    sender = MessageSender(
        config=MessagingConfig({
            "whatsapp": {
                "enabled": True,
                "api_token": "token",
                "phone_number_id": "sender-id",
                "api_version": "v20.0",
                "target": "15551234567",
                "phone_number": "should-not-be-target",
            }
        }),
        registry=create_default_registry(lambda _: None),
    )

    result = sender.send(channel="whatsapp", payload=MessagePayload(text="hi"))

    assert result.status == "sent"
    assert calls[0]["url"] == "https://graph.facebook.com/v20.0/sender-id/messages"
    assert calls[0]["kwargs"]["json"]["to"] == "15551234567"


def test_whatsapp_error_body_is_not_treated_as_sent():
    class Response:
        status_code = 200

        def json(self):
            return {"error": {"code": 100, "message": "bad request"}}

    adapter = WhatsAppMessagePlatform({})

    assert adapter._api_error(Response()) == "whatsapp_error:{'code': 100, 'message': 'bad request'}"


def test_http_post_retries_retryable_status(monkeypatch):
    calls = []

    class Response:
        text = "temporary"
        headers = {}

        def __init__(self, status_code):
            self.status_code = status_code

        def json(self):
            return {}

    def fake_post(url, **kwargs):
        calls.append(kwargs)
        return Response(500 if len(calls) == 1 else 200)

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("time.sleep", lambda _: None)
    adapter = TelegramMessagePlatform({"token": "token", "target": "123", "retries": 1, "verify": False, "proxy": "http://proxy"})

    result = adapter.send(target="", text="hi")

    assert result.status == "sent"
    assert len(calls) == 2
    assert calls[0]["verify"] is False
    assert calls[0]["proxies"] == {"http": "http://proxy", "https": "http://proxy"}


def test_wechat_openclaw_sends_with_context_token(monkeypatch):
    calls = []

    def fake_load_account(account_id=""):
        return WeChatAccount(account_id="acc", token="bot-token", base_url="https://wx.example", user_id="self")

    def fake_get_context_token(account_id, user_id):
        return "ctx-token"

    def fake_send_text(**kwargs):
        calls.append(kwargs)
        return "client-id"

    monkeypatch.setattr("core.delivery.messaging.platforms.wechat.state.load_account", fake_load_account)
    monkeypatch.setattr("core.delivery.messaging.platforms.wechat.state.get_context_token", fake_get_context_token)
    monkeypatch.setattr("core.delivery.messaging.platforms.wechat.api.send_text", fake_send_text)
    sender = MessageSender(
        config=MessagingConfig({"wechat": {"enabled": True, "target": "user@im.wechat"}}),
        registry=create_default_registry(lambda _: None),
    )

    result = sender.send(channel="wechat", payload=MessagePayload(text="hi"))

    assert result.status == "sent"
    assert result.message_id == "client-id"
    assert calls[0]["to_user_id"] == "user@im.wechat"
    assert calls[0]["context_token"] == "ctx-token"


def test_wechat_platform_sends_image_and_audio(monkeypatch, tmp_path):
    calls = []
    image = tmp_path / "pic.png"
    image.write_bytes(b"png")
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"wav")

    monkeypatch.setattr("core.delivery.messaging.platforms.wechat.state.get_context_token", lambda *_: "ctx")
    monkeypatch.setattr(
        "core.delivery.messaging.platforms.wechat.api.send_image",
        lambda **kwargs: calls.append(("image", kwargs)) or "image-id",
    )
    monkeypatch.setattr(
        "core.delivery.messaging.platforms.wechat.api.send_file",
        lambda **kwargs: calls.append(("file", kwargs)) or "file-id",
    )
    adapter = WeChatMessagePlatform({"token": "bot-token", "account_id": "acc", "target": "user"})

    image_result = adapter.send_image(target="user", image_path=str(image), caption="pic")
    audio_result = adapter.send_audio(target="user", audio_path=str(audio), caption="voice")

    assert image_result.message_id == "image-id"
    assert audio_result.message_id == "file-id"
    assert calls[0][1]["context_token"] == "ctx"
    assert calls[1][1]["file_path"] == str(audio)


def test_wechat_upload_media_encrypts_and_uploads(monkeypatch, tmp_path):
    media = tmp_path / "pic.png"
    media.write_bytes(b"123456789")
    posts = []
    uploads = []

    def fake_post(account, endpoint, body, *, timeout):
        posts.append({"endpoint": endpoint, "body": body})
        return {
            "upload_full_url": "https://upload.example/file",
            "upload_param": "upload-param",
        }

    class UploadResponse:
        headers = {"x-encrypted-param": "encrypted-param"}

        def raise_for_status(self):
            return None

    def fake_upload(url, **kwargs):
        uploads.append({"url": url, "kwargs": kwargs})
        return UploadResponse()

    monkeypatch.setattr(wechat_api, "_post", fake_post)
    monkeypatch.setattr("requests.post", fake_upload)

    uploaded = wechat_api.upload_media(
        account=WeChatAccount(account_id="acc", token="token"),
        path=str(media),
        media_type="image",
        to_user_id="user",
    )

    assert posts[0]["endpoint"] == "ilink/bot/getuploadurl"
    assert posts[0]["body"]["rawsize"] == 9
    assert posts[0]["body"]["media_type"] == 1
    assert uploads[0]["url"] == "https://upload.example/file"
    assert len(uploads[0]["kwargs"]["data"]) % 16 == 0
    assert uploaded.encrypted_param == "encrypted-param"


def test_wechat_parse_inbound_tracks_item_types():
    messages = wechat_api.parse_inbound_messages({
        "msgs": [
            {
                "from_user_id": "user",
                "to_user_id": "bot",
                "context_token": "ctx",
                "item_list": [
                    {"type": 3, "voice_item": {"text": "hello"}},
                    {"type": 2, "image_item": {}},
                ],
            }
        ]
    })

    assert messages[0].text == "hello"
    assert messages[0].item_types == (3, 2)
