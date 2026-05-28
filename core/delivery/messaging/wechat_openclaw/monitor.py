from __future__ import annotations

import threading
import time
from collections.abc import Callable

from core.delivery.messaging.wechat_openclaw import api, state
from core.delivery.messaging.wechat_openclaw.models import WeChatAccount, WeChatInboundMessage


class WeChatMonitor:
    def __init__(
        self,
        account: WeChatAccount,
        *,
        on_message: Callable[[WeChatInboundMessage], None] | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> None:
        self.account = account
        self.on_message = on_message
        self.on_status = on_status
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=f"WeChatMonitor-{self.account.account_id}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def same_session(self, account: WeChatAccount) -> bool:
        return self.account.token == account.token and self.account.base_url == account.base_url

    def update_callbacks(
        self,
        *,
        on_message: Callable[[WeChatInboundMessage], None] | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> None:
        if on_message is not None:
            self.on_message = on_message
        if on_status is not None:
            self.on_status = on_status

    def _run(self) -> None:
        self._status("started")
        sync_buf = state.load_sync_buf(self.account.account_id)
        timeout = 35
        failures = 0
        while not self._stop.is_set():
            try:
                data = api.get_updates(account=self.account, get_updates_buf=sync_buf, timeout=timeout + 5)
                if data.get("longpolling_timeout_ms"):
                    timeout = max(1, int(data["longpolling_timeout_ms"]) // 1000)
                errcode = int(data.get("errcode") or data.get("ret") or 0)
                if errcode == -14:
                    self._status("session_expired")
                    self._stop.wait(3600)
                    continue
                if errcode != 0:
                    failures += 1
                    self._status(f"poll_error:{errcode}")
                    self._stop.wait(30 if failures >= 3 else 2)
                    if failures >= 3:
                        failures = 0
                    continue
                failures = 0
                next_buf = str(data.get("get_updates_buf") or "")
                if next_buf:
                    sync_buf = next_buf
                    state.save_sync_buf(self.account.account_id, sync_buf)
                for raw_message in data.get("msgs") or []:
                    if isinstance(raw_message, dict):
                        state.append_inbound_debug(self.account.account_id, raw_message)
                for message in api.parse_inbound_messages(data):
                    if message.context_token:
                        state.set_context_token(self.account.account_id, message.from_user_id, message.context_token)
                    self.on_message(message) if self.on_message is not None else None
            except Exception as exc:
                failures += 1
                self._status(f"error:{exc.__class__.__name__}")
                self._stop.wait(30 if failures >= 3 else 2)
                if failures >= 3:
                    failures = 0
        self._status("stopped")

    def _status(self, text: str) -> None:
        if self.on_status is not None:
            self.on_status(text)


class WeChatMonitorManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._monitors: dict[str, WeChatMonitor] = {}

    def start_account(
        self,
        account: WeChatAccount,
        *,
        on_message: Callable[[WeChatInboundMessage], None] | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> WeChatMonitor:
        with self._lock:
            monitor = self._monitors.get(account.account_id)
            if monitor is not None and monitor.running and not monitor.same_session(account):
                monitor.stop()
                monitor = None
            if monitor is None or not monitor.running:
                monitor = WeChatMonitor(account, on_message=on_message, on_status=on_status)
                self._monitors[account.account_id] = monitor
                monitor.start()
            else:
                monitor.update_callbacks(on_message=on_message, on_status=on_status)
            return monitor

    def stop_except(self, account_id: str) -> None:
        with self._lock:
            for existing_account_id, monitor in list(self._monitors.items()):
                if existing_account_id == account_id:
                    continue
                monitor.stop()
                self._monitors.pop(existing_account_id, None)

    def start_saved_accounts(
        self,
        *,
        on_message: Callable[[WeChatInboundMessage], None] | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> list[WeChatMonitor]:
        monitors = []
        for account_id in state.list_account_ids():
            account = state.load_account(account_id)
            if account is not None:
                monitors.append(self.start_account(account, on_message=on_message, on_status=on_status))
        return monitors


monitor_manager = WeChatMonitorManager()
