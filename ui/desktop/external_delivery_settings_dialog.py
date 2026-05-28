from __future__ import annotations

from PySide6.QtCore import QObject, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.delivery.messaging import MessagingConfig
from core.delivery.messaging.telegram_discovery import TelegramChatDiscoveryResult, discover_next_private_chat_id
from core.delivery.messaging.wechat_openclaw import state
from core.delivery.messaging.wechat_openclaw.models import WeChatAccount
from ui.desktop.wechat_login_dialog import WeChatLoginDialog


CHANNEL_FORMS = {
    "telegram": ("Telegram", ("token", "target")),
    "discord": ("Discord", ("bot_token", "target")),
    "wechat": ("WeChat", ()),
    "feishu": ("Feishu", ("app_id", "app_secret", "target", "receive_id_type")),
    "whatsapp": ("WhatsApp", ("api_token", "phone_number_id", "api_version", "target")),
}

CHANNEL_HELP = {
    "telegram": (
        "配置步骤：\n"
        "1. 在 Telegram 搜索 @BotFather，创建一个 bot，复制它给你的 Bot Token。\n"
        "2. 点击“自动识别 chat_id”，再用你的 Telegram 账号给这个 bot 发一条消息。\n"
        "3. here 会自动填入你的个人 chat_id；勾选启用并保存。"
    ),
    "discord": (
        "配置步骤：\n"
        "1. 在 Discord Developer Portal 创建 bot，复制 Bot Token。\n"
        "2. 让接收者和这个 bot 有共同服务器，并允许接收私信。\n"
        "3. 在“接收用户 ID”填接收者的 Discord User ID。消息会通过 bot 私信发给这个用户。"
    ),
    "wechat": (
        "个人微信配置步骤：\n"
        "1. 点击下方“微信扫码登录”，用手机微信扫码并确认。\n"
        "2. 让你想接收主动联系的微信用户，给这个登录账号发一条消息。\n"
        "3. 项目会自动监听、缓存接收方并写入配置；只需要保存并启用这个渠道。"
    ),
    "feishu": (
        "配置步骤：\n"
        "1. 在飞书开放平台创建应用机器人，填写 App ID 和 App Secret。\n"
        "2. 在“接收 ID”填接收者的 open_id、user_id 或邮箱。\n"
        "3. “接收 ID 类型”对应填写 open_id、user_id 或 email。"
    ),
    "whatsapp": (
        "WhatsApp Cloud API 配置步骤：\n"
        "1. 在 Meta Developers / WhatsApp Cloud API 里获取 API Token。\n"
        "2. phone_number_id 填 Meta 分配的发送方 Phone Number ID，不是接收方手机号。\n"
        "3. 在“接收方手机号”填真正要收到消息的手机号，通常是 E.164 数字串，例如 15551234567。"
    ),
}


FIELD_LABELS = {
    "account_id": "账号 ID",
    "api_secret": "API Secret",
    "api_token": "API Token",
    "api_version": "API 版本",
    "app_id": "App ID",
    "app_secret": "App Secret",
    "base_url": "Base URL",
    "bot_token": "Bot Token",
    "phone_number_id": "发送方 Phone Number ID",
    "receive_id_type": "接收 ID 类型",
    "require_context_token": "要求 context_token",
    "target": "接收方",
    "token": "Token",
    "user_id": "当前登录用户 ID",
    "webhook_url": "Webhook URL",
}

CHANNEL_FIELD_LABELS = {
    "telegram": {
        "target": "接收 chat_id",
    },
    "discord": {
        "target": "接收用户 ID",
    },
    "feishu": {
        "target": "接收 ID",
    },
    "whatsapp": {
        "target": "接收方手机号",
    },
}

FIELD_HINTS = {
    "telegram": {
        "token": "从 @BotFather 复制，例如 123456:ABC...",
        "target": "接收者的个人 chat_id",
    },
    "discord": {
        "bot_token": "Discord bot token",
        "target": "接收者的 Discord User ID",
    },
    "wechat": {
        "account_id": "扫码登录后生成；通常可留空使用第一个已登录账号",
        "base_url": "默认即可，通常不需要修改",
        "user_id": "扫码登录后生成，用来标识当前登录的微信用户",
        "target": "目标用户通道 ID，例如 xxx@im.wechat",
    },
    "feishu": {
        "app_id": "飞书开放平台应用 App ID",
        "app_secret": "飞书开放平台应用 App Secret",
        "target": "接收者 open_id、user_id 或邮箱",
        "receive_id_type": "open_id、user_id 或 email",
    },
    "whatsapp": {
        "api_token": "Meta WhatsApp Cloud API Token",
        "phone_number_id": "发送方 Phone Number ID",
        "api_version": "默认 v20.0",
        "target": "接收方手机号，通常不带 +，例如 15551234567",
    },
}

FIELD_NOTES = {
    "telegram": {
        "target": "这里填接收者个人 chat_id，不填群或频道。",
    },
    "discord": {
        "target": "这里填接收者的 Discord User ID，消息会通过 bot 私信发送。",
    },
    "wechat": {
        "account_id": "这是项目保存的微信登录账号 ID，扫码成功后会自动填入。",
        "base_url": "这是微信登录节点地址，扫码成功后会按接口返回自动填入。",
        "user_id": "这是当前扫码登录的微信用户 ID，只用于识别登录者；消息发给谁仍然填下面的“微信用户 ID（接收方）”。",
        "target": "这是消息要发给谁，不是当前登录账号。扫码登录后，让对方先给这个微信发一条消息；下面“已缓存接收方”里出现的 ID 才能填到这里。",
        "require_context_token": "开启后会要求本地已缓存这个用户的 context_token，避免微信主动发送失败。",
    },
    "feishu": {
        "target": "填个人接收者 ID。填什么类型，要和下面的“接收 ID 类型”一致。",
        "receive_id_type": "常用 open_id、user_id 或 email。不要填群 chat_id。",
    },
    "whatsapp": {
        "phone_number_id": "这是 Meta 分配给发送方号码的 ID，不是接收人的手机号。",
        "target": "这里填接收人的手机号，通常不要带 + 号，例如 15551234567。",
    },
}


class _TelegramDiscoveryWorker(QObject):
    finished = Signal(object)

    def __init__(self, token: str) -> None:
        super().__init__()
        self.token = token
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        result = discover_next_private_chat_id(
            self.token,
            timeout_seconds=45,
            should_stop=lambda: self._cancelled,
        )
        self.finished.emit(result)


class ExternalDeliverySettingsDialog(QDialog):
    def __init__(self, parent=None, *, initial_channel: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("外部发送渠道配置")
        self.resize(560, 560)
        self.config = MessagingConfig.auto_load()
        self._fields: dict[str, dict[str, QLineEdit | QCheckBox]] = {}
        self._enabled: dict[str, QCheckBox] = {}
        self._wechat_account_label: QLabel | None = None
        self._wechat_recipients_label: QLabel | None = None
        self._last_wechat_recipients: list[str] = []
        self._telegram_status_label: QLabel | None = None
        self._telegram_discovery_thread: QThread | None = None
        self._telegram_discovery_worker: _TelegramDiscoveryWorker | None = None
        self._wechat_refresh_timer = QTimer(self)
        self._wechat_refresh_timer.setInterval(2000)
        self._wechat_refresh_timer.timeout.connect(self._refresh_wechat_labels)

        outer = QVBoxLayout(self)
        hint = QLabel(
            "先选择一个渠道，按照说明填完必要信息，勾选启用并保存。"
            "“接收方”指消息最终发给哪个人，不配置群聊、频道或客服号。"
        )
        hint.setWordWrap(True)
        outer.addWidget(hint)

        self.tabs = QTabWidget(self)
        outer.addWidget(self.tabs, 1)
        for channel, (label, fields) in CHANNEL_FORMS.items():
            self._add_channel_tab(channel, label, fields)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        save_btn = QPushButton("保存")
        cancel_btn = QPushButton("取消")
        save_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        button_row.addWidget(save_btn)
        button_row.addWidget(cancel_btn)
        outer.addLayout(button_row)

        if initial_channel in CHANNEL_FORMS:
            self.tabs.setCurrentIndex(list(CHANNEL_FORMS).index(initial_channel))
        self.tabs.currentChanged.connect(self._on_current_tab_changed)
        self._on_current_tab_changed(self.tabs.currentIndex())

    def accept(self) -> None:
        for channel in CHANNEL_FORMS:
            values: dict[str, object] = {"enabled": self._enabled[channel].isChecked()}
            for key, widget in self._fields[channel].items():
                if isinstance(widget, QCheckBox):
                    values[key] = widget.isChecked()
                else:
                    values[key] = widget.text().strip()
            if channel == "wechat":
                values.update(_wechat_auto_config())
            self.config.set_platform(channel, values)
        self.config.save()
        super().accept()

    def _add_channel_tab(self, channel: str, label: str, fields: tuple[str, ...]) -> None:
        cfg = self.config.platform(channel)
        panel = QWidget()
        layout = QVBoxLayout(panel)
        help_label = QLabel(CHANNEL_HELP.get(channel, ""))
        help_label.setWordWrap(True)
        help_label.setObjectName("externalDeliveryHelp")
        layout.addWidget(help_label)
        form = QFormLayout()
        enabled = QCheckBox("启用")
        enabled.setChecked(_as_bool(cfg.get("enabled", False)))
        self._enabled[channel] = enabled
        form.addRow("状态", enabled)
        field_widgets: dict[str, QLineEdit | QCheckBox] = {}
        for key in fields:
            if key == "require_context_token":
                widget = QCheckBox()
                widget.setChecked(_as_bool(cfg.get(key, True)))
            else:
                widget = QLineEdit(str(cfg.get(key) or _default_value(channel, key)))
                hint = FIELD_HINTS.get(channel, {}).get(key, "")
                if hint:
                    widget.setPlaceholderText(hint)
                    widget.setToolTip(hint)
                if key in {"token", "bot_token", "app_secret", "api_token"}:
                    widget.setEchoMode(QLineEdit.EchoMode.Password)
            field_widgets[key] = widget
            note = _field_note(channel, key)
            if note:
                field_box = QWidget()
                field_layout = QVBoxLayout(field_box)
                field_layout.setContentsMargins(0, 0, 0, 0)
                field_layout.setSpacing(4)
                field_layout.addWidget(widget)
                note_label = QLabel(note)
                note_label.setWordWrap(True)
                note_label.setObjectName("externalDeliveryFieldNote")
                field_layout.addWidget(note_label)
                form.addRow(_field_label(channel, key), field_box)
            else:
                form.addRow(_field_label(channel, key), widget)
        self._fields[channel] = field_widgets
        layout.addLayout(form)
        if channel == "wechat":
            account_label = QLabel(self._wechat_account_text())
            account_label.setWordWrap(True)
            account_label.setObjectName("externalDeliveryHelp")
            self._wechat_account_label = account_label
            recipients_label = QLabel(self._wechat_recipients_text())
            recipients_label.setWordWrap(True)
            recipients_label.setObjectName("externalDeliveryHelp")
            self._wechat_recipients_label = recipients_label
            login_btn = QPushButton("微信扫码登录")
            login_btn.clicked.connect(self._open_wechat_login)
            layout.addWidget(account_label)
            layout.addWidget(recipients_label)
            layout.addWidget(login_btn)
        if channel == "telegram":
            status_label = QLabel("")
            status_label.setWordWrap(True)
            status_label.setObjectName("externalDeliveryHelp")
            self._telegram_status_label = status_label
            discover_btn = QPushButton("自动识别 chat_id")
            discover_btn.clicked.connect(self._start_telegram_discovery)
            layout.addWidget(status_label)
            layout.addWidget(discover_btn)
        layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(panel)
        scroll.setWidgetResizable(True)
        self.tabs.addTab(scroll, label)

    def _open_wechat_login(self) -> None:
        dialog = WeChatLoginDialog(self)
        dialog.account_ready.connect(self._apply_wechat_account)
        dialog.show()

    def _start_telegram_discovery(self) -> None:
        if self._telegram_discovery_thread is not None and self._telegram_discovery_thread.isRunning():
            self._set_telegram_status("正在等待 Telegram 新消息。")
            return
        token_widget = self._fields.get("telegram", {}).get("token")
        token = token_widget.text().strip() if isinstance(token_widget, QLineEdit) else ""
        if not token:
            self._set_telegram_status("请先填写 Telegram Bot Token。")
            return
        self._set_telegram_status("请现在用你的 Telegram 账号给这个 bot 发一条消息。")
        thread = QThread(self)
        worker = _TelegramDiscoveryWorker(token)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_telegram_discovery_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_telegram_discovery_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._telegram_discovery_thread = thread
        self._telegram_discovery_worker = worker
        thread.start()

    def _on_telegram_discovery_finished(self, result: TelegramChatDiscoveryResult) -> None:
        if result.chat_id:
            self._set_line_edit(self._fields.get("telegram", {}).get("target"), result.chat_id)
            self._set_telegram_status(f"已识别并填入：{result.description}")
            return
        self._set_telegram_status(_telegram_discovery_reason(result.reason))

    def _on_telegram_discovery_thread_finished(self) -> None:
        self._telegram_discovery_thread = None
        self._telegram_discovery_worker = None

    def _set_telegram_status(self, text: str) -> None:
        if self._telegram_status_label is not None:
            self._telegram_status_label.setText(text)

    def _apply_wechat_account(self, account: WeChatAccount) -> None:
        if self._wechat_account_label is not None:
            self._wechat_account_label.setText(self._wechat_account_text())
        if self._wechat_recipients_label is not None:
            self._wechat_recipients_label.setText(self._wechat_recipients_text())

    def _refresh_wechat_labels(self) -> None:
        if self._wechat_account_label is not None:
            self._wechat_account_label.setText(self._wechat_account_text())
        if self._wechat_recipients_label is not None:
            self._wechat_recipients_label.setText(self._wechat_recipients_text())
        self._maybe_fill_wechat_target()

    def _on_current_tab_changed(self, index: int) -> None:
        channels = list(CHANNEL_FORMS)
        if 0 <= index < len(channels) and channels[index] == "wechat":
            self._wechat_refresh_timer.start()
            self._refresh_wechat_labels()
        else:
            self._wechat_refresh_timer.stop()

    def _set_line_edit(self, widget: QLineEdit | QCheckBox | None, value: str) -> None:
        if isinstance(widget, QLineEdit) and value:
            widget.setText(value)

    def _wechat_account_text(self) -> str:
        ids = state.list_account_ids()
        if not ids:
            return "当前没有已登录的个人微信账号。"
        return "当前登录账号：" + ", ".join(ids)

    def _wechat_recipients_text(self) -> str:
        account = state.load_account()
        if account is None:
            self._last_wechat_recipients = []
            return "已缓存接收方：暂无。扫码登录后，让要接收消息的人先给这个微信发一条消息。"
        recipients = state.list_context_user_ids(account.account_id)
        self._last_wechat_recipients = recipients
        if not recipients:
            return "已缓存接收方：暂无。让要接收消息的人先给这个微信发一条消息，监听到后这里会显示可填写的用户 ID。"
        if len(recipients) == 1:
            return "已绑定接收方：" + recipients[0]
        return "已缓存多个接收方，将默认使用最近保存的第一个：" + recipients[0]

    def _maybe_fill_wechat_target(self) -> None:
        return

    def closeEvent(self, event) -> None:
        worker = self._telegram_discovery_worker
        if worker is not None:
            worker.cancel()
        super().closeEvent(event)


def _as_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", "disabled", ""}
    return bool(value)


def _default_value(channel: str, key: str) -> str:
    if channel == "wechat" and key == "base_url":
        return "https://ilinkai.weixin.qq.com"
    if channel == "whatsapp" and key == "api_version":
        return "v20.0"
    if channel == "feishu" and key == "receive_id_type":
        return "chat_id"
    return ""


def _field_label(channel: str, key: str) -> str:
    return CHANNEL_FIELD_LABELS.get(channel, {}).get(key) or FIELD_LABELS.get(key, key)


def _field_note(channel: str, key: str) -> str:
    return FIELD_NOTES.get(channel, {}).get(key, "")


def _wechat_auto_config() -> dict[str, object]:
    account = state.load_account()
    values: dict[str, object] = {
        "require_context_token": True,
        "account_id": "",
        "base_url": "",
        "user_id": "",
        "target": "",
    }
    if account is None:
        return values
    recipients = state.list_context_user_ids(account.account_id)
    values.update({
        "account_id": account.account_id,
        "base_url": account.base_url,
        "user_id": account.user_id,
        "target": recipients[0] if recipients else "",
    })
    return values


def _telegram_discovery_reason(reason: str) -> str:
    if reason == "missing_token":
        return "请先填写 Telegram Bot Token。"
    if reason == "timeout":
        return "没有识别到新消息，请确认你已经给这个 bot 发了消息。"
    if reason == "cancelled":
        return "已取消 Telegram 自动识别。"
    if reason == "no_private_message":
        return "没有识别到私聊消息，请用你的个人账号直接给 bot 发消息。"
    if reason.startswith("telegram_error:"):
        return "Telegram 返回错误：" + reason.removeprefix("telegram_error:")
    if reason.startswith("request_error:"):
        return "Telegram 连接失败：" + reason.removeprefix("request_error:")
    return "Telegram 自动识别失败：" + reason
