from __future__ import annotations

from core.delivery.messaging.wechat_openclaw import api, state
from core.delivery.messaging.wechat_openclaw.monitor import WeChatMonitor, WeChatMonitorManager
from core.delivery.messaging.wechat_openclaw.models import LoginStartResult, WeChatAccount
from ui.desktop.wechat_login_dialog import _LoginWorker, _download_qr_image


def test_download_qr_image_renders_login_url_when_not_image() -> None:
    image = _download_qr_image(
        LoginStartResult(
            session_key="session",
            qrcode="qrcode-token",
            qrcode_url="https://liteapp.weixin.qq.com/q/example?bot_type=3",
        )
    )

    assert image.startswith(b"\x89PNG")


def test_login_worker_waits_between_scanned_statuses(monkeypatch) -> None:
    sleeps = []
    polls = []
    worker = _LoginWorker()

    monkeypatch.setattr(
        "ui.desktop.wechat_login_dialog.api.start_login",
        lambda **_: LoginStartResult(session_key="session", qrcode="qr", qrcode_url="login-url"),
    )
    monkeypatch.setattr("ui.desktop.wechat_login_dialog._download_qr_image", lambda _: b"")
    def fake_sleep(value):
        sleeps.append(value)
        worker.cancel()

    monkeypatch.setattr("ui.desktop.wechat_login_dialog.QThread.msleep", fake_sleep)

    def fake_poll_login(**kwargs):
        polls.append(kwargs)
        return api.LoginPollResult(status="scaned")

    monkeypatch.setattr("ui.desktop.wechat_login_dialog.api.poll_login", fake_poll_login)

    worker.run()

    assert polls[0]["timeout"] == 8
    assert sleeps == [1000]


def test_poll_login_uses_custom_timeout(monkeypatch) -> None:
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "wait"}

    def fake_get(url, **kwargs):
        calls.append(kwargs)
        return Response()

    monkeypatch.setattr("requests.get", fake_get)

    result = api.poll_login(qrcode="qr", base_url="https://wx.example", timeout=3)

    assert result.status == "wait"
    assert calls[0]["timeout"] == 3


def test_replace_accounts_removes_previous_login(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERE_WECHAT_STATE_DIR", str(tmp_path))
    state.save_account(WeChatAccount(account_id="old@im.bot", token="old-token"))
    state.set_context_token("old@im.bot", "user@im.wechat", "ctx")

    state.replace_accounts(WeChatAccount(account_id="new@im.bot", token="new-token"))

    assert state.list_account_ids() == ["new@im.bot"]
    assert state.load_account("old@im.bot") is None
    assert state.load_account("new@im.bot").token == "new-token"
    assert state.list_context_user_ids("old@im.bot") == []


def test_append_inbound_debug_redacts_tokens(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HERE_WECHAT_STATE_DIR", str(tmp_path))

    state.append_inbound_debug("acc@im.bot", {
        "from_user_id": "user",
        "context_token": "secret",
        "item_list": [{"type": 3, "voice_item": {"playtime": 1000}}],
    })

    text = state.inbound_debug_path("acc@im.bot").read_text(encoding="utf-8")

    assert '"context_token":"***"' in text
    assert '"voice_item":{"playtime":1000}' in text


def test_monitor_manager_stop_except_stops_old_monitors(monkeypatch) -> None:
    stopped = []

    monkeypatch.setattr(WeChatMonitor, "running", property(lambda self: True))
    monkeypatch.setattr(WeChatMonitor, "start", lambda self: None)
    monkeypatch.setattr(WeChatMonitor, "stop", lambda self: stopped.append(self.account.account_id))
    manager = WeChatMonitorManager()
    manager.start_account(WeChatAccount(account_id="old@im.bot", token="old"))
    manager.start_account(WeChatAccount(account_id="new@im.bot", token="new"))

    manager.stop_except("new@im.bot")

    assert stopped == ["old@im.bot"]


def test_monitor_manager_restarts_same_account_when_token_changes(monkeypatch) -> None:
    stopped = []

    monkeypatch.setattr(WeChatMonitor, "running", property(lambda self: True))
    monkeypatch.setattr(WeChatMonitor, "start", lambda self: None)
    monkeypatch.setattr(WeChatMonitor, "stop", lambda self: stopped.append(self.account.token))
    manager = WeChatMonitorManager()

    first = manager.start_account(WeChatAccount(account_id="same@im.bot", token="old"))
    second = manager.start_account(WeChatAccount(account_id="same@im.bot", token="new"))

    assert stopped == ["old"]
    assert second is not first


def test_monitor_manager_updates_callbacks_for_running_monitor(monkeypatch) -> None:
    messages = []
    statuses = []

    monkeypatch.setattr(WeChatMonitor, "running", property(lambda self: True))
    monkeypatch.setattr(WeChatMonitor, "start", lambda self: None)
    manager = WeChatMonitorManager()

    def on_message(message) -> None:
        messages.append(message)

    monitor = manager.start_account(
        WeChatAccount(account_id="same@im.bot", token="token"),
        on_status=lambda text: statuses.append(f"first:{text}"),
    )
    reused = manager.start_account(
        WeChatAccount(account_id="same@im.bot", token="token"),
        on_message=on_message,
        on_status=lambda text: statuses.append(f"second:{text}"),
    )

    assert reused is monitor
    monitor.on_message("hello")
    monitor._status("started")
    assert messages == ["hello"]
    assert statuses == ["second:started"]
