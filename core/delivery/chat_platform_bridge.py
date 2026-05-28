from __future__ import annotations

import threading
from typing import Any, Callable

import requests

from core.delivery.messaging import MessagingConfig
from core.delivery.messaging.wechat_openclaw import monitor_manager


class TelegramChatBridge:
    """Poll Telegram messages from the configured chat and feed Here chat."""

    def __init__(
        self,
        *,
        config: MessagingConfig,
        emit_user_text: Callable[[str], None],
        notify: Callable[[str], None] | None = None,
    ) -> None:
        self.config = config
        self.emit_user_text = emit_user_text
        self.notify = notify
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._offset = 0

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="TelegramChatBridge", daemon=True)
        self._thread.start()

    def stop(self, *, wait: bool = False) -> None:
        self._stop_event.set()
        thread = self._thread
        if wait and thread is not None and thread.is_alive():
            thread.join(timeout=2)

    def _run(self) -> None:
        cfg = self.config.platform("telegram")
        token = str(cfg.get("token") or "").strip()
        target = _first_config_value(cfg, "target", "chat_id", "recipient")
        if not token or not target:
            self._notify("Telegram 聊天平台未配置 token 或 chat_id。")
            return
        url = f"https://api.telegram.org/bot{token}/getUpdates"
        self._prime_offset(url, target)
        while not self._stop_event.is_set():
            try:
                response = requests.get(
                    url,
                    params={"timeout": 8, "offset": self._offset, "allowed_updates": '["message"]'},
                    timeout=12,
                )
                data = response.json()
            except Exception as exc:
                self._notify(f"Telegram 接收失败：{type(exc).__name__}")
                self._stop_event.wait(5)
                continue
            if self._stop_event.is_set():
                return
            if not isinstance(data, dict) or not data.get("ok"):
                self._notify(f"Telegram 接收失败：{data.get('description') if isinstance(data, dict) else 'unknown'}")
                self._stop_event.wait(5)
                continue
            for update in data.get("result") or []:
                self._handle_update(update, target)

    def _prime_offset(self, url: str, target: str) -> None:
        try:
            response = requests.get(url, params={"timeout": 0, "allowed_updates": '["message"]'}, timeout=3)
            data = response.json()
        except Exception:
            return
        if not isinstance(data, dict) or not data.get("ok"):
            return
        updates = data.get("result") or []
        if updates:
            self._offset = max(int(update.get("update_id", 0) or 0) for update in updates) + 1

    def _handle_update(self, update: dict[str, Any], target: str) -> None:
        try:
            update_id = int(update.get("update_id", 0) or 0)
        except (TypeError, ValueError):
            update_id = 0
        if update_id >= self._offset:
            self._offset = update_id + 1
        message = update.get("message")
        if not isinstance(message, dict):
            return
        chat = message.get("chat")
        if not isinstance(chat, dict):
            return
        chat_id = str(chat.get("id") or "").strip()
        if chat_id != target:
            return
        text = str(message.get("text") or "").strip()
        if not text:
            return
        self.emit_user_text(text)

    def _notify(self, text: str) -> None:
        if self.notify is not None:
            try:
                self.notify(text)
            except Exception:
                pass


class WeChatChatBridge:
    """Reuse the existing WeChat monitor to feed inbound messages into chat."""

    def __init__(
        self,
        *,
        emit_user_text: Callable[[str], None],
        notify: Callable[[str], None] | None = None,
    ) -> None:
        self.emit_user_text = emit_user_text
        self.notify = notify
        self._monitors: list[Any] = []

    def start(self) -> None:
        try:
            self._monitors = monitor_manager.start_saved_accounts(
                on_message=self._on_message,
                on_status=lambda text: self._notify(f"WeChat: {text}"),
            )
        except Exception as exc:
            self._notify(f"WeChat 接收启动失败：{type(exc).__name__}")

    def stop(self, *, wait: bool = False) -> None:
        for monitor in list(self._monitors):
            stop = getattr(monitor, "stop", None)
            if callable(stop):
                stop()
        self._monitors = []

    def _on_message(self, message: Any) -> None:
        text = str(getattr(message, "text", "") or "").strip()
        if text:
            self.emit_user_text(text)

    def _notify(self, text: str) -> None:
        if self.notify is not None:
            try:
                self.notify(text)
            except Exception:
                pass


def start_chat_platform_bridge(
    *,
    channel: str,
    emit_user_text: Callable[[str], None],
    notify: Callable[[str], None] | None = None,
) -> Any | None:
    normalized = str(channel or "desktop_chat").strip().lower()
    if normalized == "telegram":
        bridge = TelegramChatBridge(
            config=MessagingConfig.auto_load(),
            emit_user_text=emit_user_text,
            notify=notify,
        )
        bridge.start()
        return bridge
    if normalized == "wechat":
        bridge = WeChatChatBridge(emit_user_text=emit_user_text, notify=notify)
        bridge.start()
        return bridge
    if normalized not in {"desktop_chat", "telegram", "wechat"} and notify is not None:
        try:
            notify(f"{normalized} 聊天平台目前仅支持发送；接收需要对应平台的入站监听配置。")
        except Exception:
            pass
    return None


def stop_chat_platform_bridge(bridge: Any | None, *, wait: bool = False) -> None:
    stop = getattr(bridge, "stop", None)
    if callable(stop):
        try:
            stop(wait=wait)
        except TypeError:
            stop()


def _first_config_value(config: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(config.get(key) or "").strip()
        if value:
            return value
    return ""
