from __future__ import annotations

import io
import urllib.request

from PySide6.QtCore import QObject, QThread, Signal, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from core.delivery.messaging.wechat_openclaw import api, state
from core.delivery.messaging.wechat_openclaw.models import DEFAULT_BASE_URL, DEFAULT_BOT_TYPE, LoginStartResult, WeChatAccount
from core.delivery.messaging.wechat_openclaw.monitor import monitor_manager


class _LoginWorker(QObject):
    started = Signal(object, bytes)
    status = Signal(str)
    account_ready = Signal(object)
    finished = Signal(bool, str)

    def __init__(self, base_url: str = DEFAULT_BASE_URL, bot_type: str = DEFAULT_BOT_TYPE) -> None:
        super().__init__()
        self.base_url = base_url
        self.bot_type = bot_type
        self._cancelled = False
        self._last_status = ""

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            login = api.start_login(base_url=self.base_url, bot_type=self.bot_type)
            if self._cancelled:
                self.finished.emit(False, "已取消微信登录。")
                return
            image = _download_qr_image(login)
            self.started.emit(login, image)
            poll_base_url = self.base_url
            while not self._cancelled:
                result = api.poll_login(qrcode=login.qrcode, base_url=poll_base_url, timeout=8)
                if self._cancelled:
                    break
                if result.status == "scaned_but_redirect" and result.redirect_base_url:
                    poll_base_url = result.redirect_base_url
                    self._emit_status("已切换登录节点，继续等待确认...")
                    self._wait_before_next_poll(1.0)
                    continue
                if result.status == "scaned":
                    self._emit_status("已扫码，请在手机上确认登录。")
                    self._wait_before_next_poll(1.0)
                    continue
                if result.status == "wait":
                    self._emit_status("等待扫码...")
                    self._wait_before_next_poll(1.0)
                    continue
                if result.status == "expired":
                    self.finished.emit(False, "二维码已过期，请重新打开登录。")
                    return
                if result.status == "confirmed" and result.account is not None:
                    state.replace_accounts(result.account)
                    monitor_manager.stop_except(result.account.account_id)
                    monitor_manager.start_account(result.account)
                    self.account_ready.emit(result.account)
                    self.finished.emit(True, f"微信已连接：{result.account.account_id}")
                    return
                if result.status == "failed":
                    self.finished.emit(False, result.message or "登录失败")
                    return
                self._emit_status(f"等待登录确认：{result.status}")
                self._wait_before_next_poll(1.0)
            self.finished.emit(False, "已取消微信登录。")
        except Exception as exc:
            self.finished.emit(False, f"微信登录失败：{exc}")

    def _emit_status(self, text: str) -> None:
        if text == self._last_status:
            return
        self._last_status = text
        self.status.emit(text)

    def _wait_before_next_poll(self, seconds: float) -> None:
        if seconds <= 0:
            return
        QThread.msleep(max(1, int(seconds * 1000)))


class WeChatLoginDialog(QDialog):
    account_ready = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("微信扫码登录")
        self.setModal(False)
        self.resize(360, 460)
        self._thread: QThread | None = None
        self._worker: _LoginWorker | None = None
        self._closing_after_worker = False

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.status_label = QLabel("正在生成二维码...")
        self.status_label.setWordWrap(True)
        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setMinimumSize(300, 300)
        self.link_label = QLabel()
        self.link_label.setWordWrap(True)
        self.close_btn = QPushButton("关闭")
        self.close_btn.clicked.connect(self.close)
        layout.addWidget(self.status_label)
        layout.addWidget(self.qr_label)
        layout.addWidget(self.link_label)
        layout.addStretch(1)
        layout.addWidget(self.close_btn)
        self._start()

    def closeEvent(self, event) -> None:
        if self._closing_after_worker:
            super().closeEvent(event)
            return
        if self._worker is not None:
            self._worker.cancel()
        if self._thread is not None and self._thread.isRunning():
            self.close_btn.setEnabled(False)
            self.status_label.setText("正在停止微信登录，请稍候...")
            self._thread.finished.connect(self.close)
            event.ignore()
            return
        super().closeEvent(event)

    def _start(self) -> None:
        self._thread = QThread(self)
        self._worker = _LoginWorker()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.started.connect(self._on_login_started)
        self._worker.status.connect(self.status_label.setText)
        self._worker.account_ready.connect(self._on_account_ready)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_login_started(self, login: LoginStartResult, image: bytes) -> None:
        pixmap = QPixmap()
        if image:
            pixmap.loadFromData(image)
        if not pixmap.isNull():
            self.qr_label.setPixmap(pixmap.scaled(300, 300, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else:
            self.qr_label.setText("二维码图片生成失败，请复制下方链接打开后扫码。")
        self.status_label.setText(login.message or "请使用微信扫码。")
        self.link_label.setText(f"二维码链接：{login.qrcode_url}")

    def _on_finished(self, ok: bool, message: str) -> None:
        self.status_label.setText(message)
        if ok:
            self.close_btn.setText("完成")

    def _on_account_ready(self, account: WeChatAccount) -> None:
        self.account_ready.emit(account)

    def _on_thread_finished(self) -> None:
        self._worker = None
        self._thread = None
        if not self.close_btn.isEnabled():
            self._closing_after_worker = True
            self.close()


def _download_qr_image(login: LoginStartResult) -> bytes:
    image = _read_image_url(login.qrcode_url)
    if image:
        return image
    return _render_qr_png(login.qrcode_url or login.qrcode)


def _read_image_url(url: str) -> bytes:
    if not url.startswith(("http://", "https://")):
        return b""
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            data = response.read()
            content_type = str(response.headers.get("Content-Type") or "").lower()
            if content_type.startswith("image/") or _looks_like_image(data):
                return data
            return b""
    except Exception:
        return b""


def _render_qr_png(text: str) -> bytes:
    if not text:
        return b""
    try:
        import qrcode
    except Exception:
        return b""
    image = qrcode.make(text)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _looks_like_image(data: bytes) -> bool:
    return data.startswith((
        b"\x89PNG\r\n\x1a\n",
        b"\xff\xd8\xff",
        b"GIF87a",
        b"GIF89a",
        b"BM",
        b"RIFF",
    ))
