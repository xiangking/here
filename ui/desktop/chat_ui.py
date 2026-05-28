import sys
import ctypes
import base64
import uuid
from PIL.ImageChops import screen
import numpy as np
import threading
import yaml
import time
from PySide6.QtCore import QByteArray, QEvent, QPoint, QRect, Qt, Signal, QSize, QUrl
from PySide6.QtGui import (
    QAction,
    QCursor,
    QFont,
    QGuiApplication,
    QHoverEvent,
    QImage,
    QMouseEvent,
    QPixmap,
    QFontMetrics,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QMenu,
    QTextEdit,
    QSizePolicy,
    QToolTip,
)
import os

from pathlib import Path

from infrastructure.paths import get_app_paths

import logging
current_script = Path(__file__).resolve()
project_root = current_script.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from ui.desktop import styles
from ui.desktop.components import CGWidget, ClickableLabel, TypingLabel, SpritePanel
from ui.desktop.desktop_menu import DesktopMenuMixin
from ui.desktop.desktop_toolbar import DesktopToolbarMixin
from ui.desktop.mic_button import MicButton
from ui.desktop.rounded_chrome_button import ChromeSendButton
from ui.desktop.busy_bar import BusyBar
from ui.desktop.theme_chrome import get_chat_chrome_theme
from ui.desktop.workers import ImageDisplayThread
from services.config.config_manager import ConfigManager
from ui.desktop.character_entry import character_entry_line, character_entry_sprite
from core.runtime.app_runtime import try_get_app_runtime
from services.i18n import init_i18n, tr

config_manager = ConfigManager()

_logger = logging.getLogger(__name__)

DIALOG_FRAME_PATH = Path('./assets/system/picture/dialog_frame.png').absolute().as_posix()
INPUT_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


class ImageAttachmentTextEdit(QTextEdit):
    """Text input that accepts image files via paste, drag-and-drop, and file URLs."""

    image_files_added = Signal(list)
    image_pasted = Signal(object)

    def _image_file_paths_from_mime(self, mime) -> list[str]:
        paths: list[str] = []
        if mime is None or not mime.hasUrls():
            return paths
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile()).expanduser()
            if path.is_file() and path.suffix.lower() in INPUT_IMAGE_SUFFIXES:
                paths.append(path.as_posix())
        return paths

    def _mime_has_image_payload(self, mime) -> bool:
        if mime is None:
            return False
        return bool(self._image_file_paths_from_mime(mime)) or mime.hasImage()

    def canInsertFromMimeData(self, source) -> bool:  # noqa: ANN001
        if self._mime_has_image_payload(source):
            return True
        return super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source) -> None:  # noqa: ANN001
        paths = self._image_file_paths_from_mime(source)
        if paths:
            self.image_files_added.emit(paths)
            return
        if source is not None and source.hasImage():
            self.image_pasted.emit(source.imageData())
            return
        super().insertFromMimeData(source)

    def dragEnterEvent(self, event) -> None:  # noqa: ANN001
        if self._mime_has_image_payload(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: ANN001
        if self._mime_has_image_payload(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: ANN001
        mime = event.mimeData()
        paths = self._image_file_paths_from_mime(mime)
        if paths:
            self.image_files_added.emit(paths)
            event.acceptProposedAction()
            return
        if mime is not None and mime.hasImage():
            self.image_pasted.emit(mime.imageData())
            event.acceptProposedAction()
            return
        super().dropEvent(event)


class ChatUIWindow(DesktopToolbarMixin, DesktopMenuMixin, QWidget):
    """桌面助手主窗口"""
    message_submitted = Signal(str)  # 定义信号用于发送消息
    open_chat_history_dialog = Signal()  # 定义信号用于打开聊天历史记录对话框
    change_voice_language = Signal(str)  # 定义信号用于更改语音的语言
    close_window = Signal()  # 关闭窗口信号
    clear_chat_history = Signal()
    skip_speech_signal = Signal()  # 跳过当前语音信号
    agent_reply_finished = Signal()  # Hermes Agent 回复完成信号
    pause_asr_signal = Signal()  # 暂停 ASR 信号
    copy_chat_history_to_clipboard = Signal()  # 复制聊天记录到剪贴板信号.
    revert_chat_history = Signal(int)  # 回溯聊天记录到指定索引

    option_selected = Signal(str)
    background_image_changed = Signal(str)
    notification_changed = Signal(str)
    display_words_changed = Signal(str)
    numeric_info_changed = Signal(str)

    # 聊天输入框 QTextEdit：获得 / 失去焦点（见 eventFilter）
    user_input_started = Signal()
    user_input_ended = Signal()

    def __init__(self, image_queue, emotion_queue, agent_backend, sprite_mode=False, background_mode = False, max_sprite_slots=3):
        """初始化窗口"""
        super().__init__()
        self.CONFIG_FILE = str(get_app_paths().config_dir / "system_config.yaml")
        if background_mode:
            self.HORIZONTAL_MARGIN_PERCENT = 0.2
        else:
            self.HORIZONTAL_MARGIN_PERCENT = 0
        self.image_queue = image_queue
        self.display_thread = None
        self.max_sprite_slots = max_sprite_slots
        self.agent_backend = agent_backend
        self.emotion_queue = emotion_queue
        self.sprite_mode = sprite_mode
        self.current_options = []
        screen = QApplication.primaryScreen()
        screen_geometry = screen.geometry()
        self.original_height = screen_geometry.height() // 4 * 3
        self.original_width = screen_geometry.width() // 4 * 3 if background_mode else self.original_height
        # 字体随窗口缩放：相对初始客户区面积的平方根比例，带上下限
        self._font_scale_ref_w = max(1, int(self.original_width))
        self._font_scale_ref_h = max(1, int(self.original_height))
        # 对话/选项区：小于启动时透明窗初始宽度则横向上与容器同宽（无左右留白）
        self._overlay_min_ref_width = max(1, int(self.original_width))
        self.current_background_path = None
        # 全尺寸图，供 resize 时重缩放，使底栏 input 与整窗共用同一底图
        self._background_source_pixmap = None
        # 底栏叠在立绘上时，对话/选项需避开此高度（含底边留白，在 resize 中更新）
        self._bottom_chrome_h = 130
        # 底栏与窗口边距：左右内缩、距底边留白（与 _layout_input_row 一致）
        self._input_row_inset_h = 16
        self._input_row_inset_bottom = 10

        # 无边框缩放：窗边条 + 角块；全透明分层区无法命中，依赖 _resize_grip_bl/br
        self._resize_margin = 8
        self._window_corner_grip_px = 28
        self._resizing = False
        self._resize_mask = Qt.Edge(0)
        self._resize_start_global = QPoint()
        self._resize_start_geom = QRect()
        self._hover_resize_edges = Qt.Edge(0)
        self._resize_cursor_override_active = False
        self.drag_position = None
        self._dialog_resizing = False
        self._dialog_resize_edges = Qt.Edge(0)
        self._dialog_resize_start_global = QPoint()
        self._dialog_resize_start_geometry = QRect()
        self._dialog_resize_start_size = QSize()
        self._dialog_resize_margin = 8
        self._auto_fitting_sprite_window = False
        self._last_auto_fit_size = QSize()
        self._sprite_dialog_extra_reserved = 0
        self._last_dialog_html = ""
        self._last_dialog_name = ""
        self._last_dialog_name_color = ""
        self._dialog_box_collapsed = bool(
            getattr(config_manager.config.system_config, "dialog_box_collapsed", False)
        )
        self._process_hint_collapsed = bool(
            getattr(config_manager.config.system_config, "process_hint_collapsed", False)
        )
        self._input_bar_collapsed = bool(
            getattr(config_manager.config.system_config, "input_bar_collapsed", False)
        )
        self._external_chat_display_hidden = self._chat_delivery_channel_is_external()
        self._last_busy_bar_text = ""
        self._last_busy_bar_duration = 0.0

        self.base_font_size_px = config_manager.config.system_config.base_font_size_px

        # 设置字体大小
        base_dpi = 150.0
        curren_dpi = screen.logicalDotsPerInch()
        self.font_size = f"{str(int(self.base_font_size_px*curren_dpi//base_dpi))}px;"
        self.btn_font_size = f"{str(int(self.base_font_size_px*curren_dpi//base_dpi))}px;"

        # 对话框颜色
        self.theme_color = config_manager.config.system_config.theme_color
        self.second_color = 'rgba(50, 50, 50, 100)'

        # 设置图像显示线程
        if not self.sprite_mode:
            self.setup_image_thread()
        
        # 初始大小
        self.resize(self.original_width, self.original_height)
        self.setMinimumSize(360, 260)

        # 初始化UI组件
        self.setup_ui()
        self._install_resize_event_filters()

        # 默认位置：工作区内居中；若有上次保存的布局则覆盖
        avail = screen.availableGeometry()
        x = avail.left() + (avail.width() - self.original_width) // 2
        y = avail.top() + (avail.height() - self.original_height) // 2
        self.move(x, y)
        self._restore_chat_window_geometry()

        from ui.desktop.signal_bridge import attach_chat_ui_window

        attach_chat_ui_window(self)

    def _united_available_screen_rect(self) -> QRect:
        united = QRect()
        for s in QGuiApplication.screens():
            united = united.united(s.availableGeometry())
        return united

    def _ensure_window_geometry_visible(self) -> None:
        united = self._united_available_screen_rect()
        if united.isNull():
            return
        fg = self.frameGeometry()
        if united.contains(fg.center()):
            return
        c, tc = fg.center(), united.center()
        self.move(self.x() + tc.x() - c.x(), self.y() + tc.y() - c.y())

    def _restore_chat_window_geometry(self) -> None:
        raw = (config_manager.config.system_config.chat_window_geometry_b64 or "").strip()
        if not raw:
            return
        try:
            data = base64.standard_b64decode(raw.encode("ascii"), validate=True)
        except Exception:
            return
        if not data:
            return
        if not self.restoreGeometry(QByteArray(data)):
            return
        self._ensure_window_geometry_visible()

    def _persist_chat_window_geometry(self) -> None:
        try:
            ba = self.saveGeometry()
            if ba.isEmpty():
                return
            payload = bytes(ba)
            b64 = base64.standard_b64encode(payload).decode("ascii")
            sc = config_manager.config.system_config.model_copy(deep=True)
            sc.chat_window_geometry_b64 = b64
            config_manager.config.system_config = sc
            config_manager.save_system_config()
        except Exception as e:
            _logger.warning("保存聊天窗口布局失败: %s", e)

    def _persist_dialog_box_size(self) -> None:
        try:
            sc = config_manager.config.system_config.model_copy(deep=True)
            sc.dialog_box_width_pct = int(sc.dialog_box_width_pct)
            sc.dialog_box_height_pct = int(sc.dialog_box_height_pct)
            config_manager.config.system_config = sc
            config_manager.save_system_config()
        except Exception as e:
            _logger.warning("保存对话框尺寸失败: %s", e)

    def _window_font_scale(self) -> float:
        rw = max(1, int(getattr(self, "_font_scale_ref_w", self.original_width)))
        rh = max(1, int(getattr(self, "_font_scale_ref_h", self.original_height)))
        sw = self.width() / rw
        sh = self.height() / rh
        s = (sw * sh) ** 0.5
        return max(0.55, min(2.2, s))

    def _make_state_proxy(self):
        """返回一个满足 _ChatUIStateProxy 的对象，仅暴露安全读方法。"""
        class _WindowStateProxy:
            def __init__(self, window: "ChatUIWindow") -> None:
                self._window = window

            def notification_hint(self) -> str:
                return self._window.input_box.placeholderText()

            def input_draft(self) -> str:
                if self._window.is_input_bar_collapsed():
                    return ""
                return self._window.input_box.toPlainText()

            def choice_options(self) -> list[str]:
                return list(self._window.current_options)

            def is_dialog_visible(self) -> bool:
                return (
                    self._window.dialog_label.isVisible()
                    and not self._window.is_dialog_box_collapsed()
                )

            def is_choice_panel_visible(self) -> bool:
                return self._window.options_widget.isVisible()

            def dialog_text(self) -> str:
                return self._window._last_dialog_html or self._window.dialog_label.text()

            def background_image_path(self) -> str | None:
                return self._window.current_background_path

            def base_font_size_px(self) -> int:
                return int(self._window.base_font_size_px)

        return _WindowStateProxy(self)

    def _make_ui_actions(self):
        from app.desktop.ui_context import _ChatUIActions
        return _ChatUIActions(
            set_notification_hint=self.setNotification,
            set_busy_bar=self.setBusyBar,
            set_input_draft=self.input_box.setPlainText,
            clear_input_draft=self.input_box.clear,
            set_choice_options=self.setOptions,
            set_dialog_html=self.setDisplayWords,
            mount_chat_ui_extensions=self.mount_chat_ui_extensions,
        )

    def setup_ui(self):
        """初始化UI组件"""
        # 窗口设置
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Window
            | Qt.WindowType.NoDropShadowWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setObjectName("DesktopAssistantWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # 避免无边框+分层窗口在部分系统上出现非预期的灰边/默认底色渗出
        self.setStyleSheet(
            "#DesktopAssistantWindow { background: transparent; border: none; }"
        )
        
        # 主布局：立绘区独占整窗，底栏不占用 layout（叠在立绘上）
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        self.setup_background_label()        
        # 图像容器
        self.image_container = QWidget()
        self.image_layout = QVBoxLayout(self.image_container)
        self.image_layout.setContentsMargins(0, 0, 0, 0)
        self.image_layout.setSpacing(0)

        # CG
        self.cg_widget = CGWidget(self.theme_color, self.image_container)
        self.cg_widget.cg_display_changed.connect(self.handle_cg_display_change)

        # 数值信息标签
        self.setup_numeric_label()

        # 立绘展示板
        self.setup_image_label()   
        
        # 对话框组件,覆盖在图像上
        self.setup_dialog_label()

        # 选项容器,与对话框标签位置相同
        self.setup_options_widget()

        # 工具栏
        self.setup_toolbar()
        
        # 底栏（叠在立绘上）
        self.setup_input_layout()
        self._busy_bar = BusyBar(self)
        self._busy_bar.hide()
        
        # 将组件添加到主布局
        main_layout.addWidget(self.image_container, 1)
        
        self.background_label.lower()
        self.cg_widget.lower() # 初始时，CG 在背景上方
        self.sprite_panel.raise_() # 立绘在 CG 上方
        self.dialog_label.raise_() # 对话框和选项在所有图像组件上方
        self.name_label.raise_()
        self.options_widget.raise_()

        self.setLayout(main_layout)
        self._layout_input_row()
        self._raise_input_and_toolbar()
        self.apply_chat_delivery_visibility()

        self.cg_widget.setGeometry(0,0,self.original_width, self.original_height)
        self._setup_resize_corner_hit_widgets()
        self.apply_font_styles()
    
    def handle_cg_display_change(self, is_cg_visible: bool):
        """
        处理 CG 显示状态的改变。
        is_cg_visible: True 时隐藏立绘，False 时显示立绘。
        """
        if is_cg_visible:
            # 调整 CG 的层次，使其浮动到立绘之上，实现覆盖
            self.cg_widget.raise_()
            
            # 隐藏立绘
            self.sprite_panel.hide()
            
            # 确保对话框等元素在 CG 之上
            self.dialog_label.raise_()
            self.name_label.raise_()
            self.options_widget.raise_()
            self.numeric_info_label.lower()  # below sprite layer
            self._raise_input_and_toolbar() 
            
        else:
            self.sprite_panel.show()
            # 恢复 CG 到立绘之下
            self.cg_widget.lower()
            self.cg_widget.hide()
            self._raise_input_and_toolbar()
    def show_cg_image(self, cg_path: str):
        """外部接口：显示一个CG，它会触发立绘隐藏"""
        self.cg_widget.show_cg(cg_path)
    def _send_btn_font_px(self) -> int:
        try:
            raw = str(self.btn_font_size).replace("px", "").replace(";", "").strip()
            return max(9, min(12, int(raw)))
        except (ValueError, TypeError):
            return 10

    def apply_font_styles(self):
        """根据 DPI、用户基准字号与当前窗口尺寸更新所有 UI 字号与相关控件。"""
        screen = QApplication.primaryScreen()
        curren_dpi = screen.logicalDotsPerInch()
        base_dpi = 150.0
        win_s = self._window_font_scale()

        body_px = int(self.base_font_size_px * curren_dpi / base_dpi * win_s)
        body_px = max(10, body_px)
        btn_px = int(self.base_font_size_px * 28 / 48 * curren_dpi / base_dpi * win_s)
        btn_px = max(9, btn_px)

        self.font_size = f"{body_px}px;"
        self.btn_font_size = f"{btn_px}px;"
        ch = get_chat_chrome_theme(
            config_manager.config.system_config.chat_ui_theme_path
        )

        # 对话气泡只用 QSS 渐变，不要再叠一层 dialog_frame 位图，否则整图会随 QLabel
        # 拉伸，PNG 里画的装饰/灰边会看起来像「外圈多了一圈框」。
        self.dialog_label.setStyleSheet(
            styles.dialog_label_theme_applied(
                self.font_size,
                self.theme_color,
                self.second_color,
                chrome_extra=ch.dialog_label_extra,
            )
        )
        self.dialog_label.setPixmap(QPixmap())

        # Apply to name label
        if hasattr(self, 'name_label'):
            self.name_label.setStyleSheet(
                f"background:transparent; color:white; "
                f"font-size:{self.font_size}; font-weight:700; "
                f"padding:0 16px; border:none;"
            )

        # Apply to numeric label
        self.numeric_info_label.setStyleSheet(
            styles.numeric_info_label_theme_applied(
                self.font_size,
                self.theme_color,
                self.second_color,
                QUrl.fromLocalFile(DIALOG_FRAME_PATH).toString(),
                chrome_extra=ch.numeric_label_extra,
            )
        )

        # Apply to input box
        self.input_box.setStyleSheet(
            styles.text_edit_input(self.btn_font_size, chrome_extra=ch.input_bar_extra)
        )
        self.input_box.setPlaceholderText(tr("desktop.input_placeholder"))

        # Apply to send button（圆角由 QPainter 绘制，见 ChromeSendButton）
        self.send_btn.setText("➤")
        fp = self._send_btn_font_px()
        self.send_btn.apply_visual(
            ch.send_button_extra,
            self.theme_color,
            "#FFFFFF",
            default_corner_px=12,
            font_px=fp,
        )

        self.options_widget.setStyleSheet(
            styles.options_widget_container(ch.options_container_extra)
        )

        # 选项区须带主题渐变；勿用 option_row_list_refresh，否则会冲掉 setOptions 里的主题色
        self._refresh_option_choice_styles()

        self._layout_toolbar_geometry()
        if getattr(self, "mic_button", None) is not None:
            self.mic_button.apply_window_scale(0.48, ch)
        if getattr(self, "_busy_bar", None) is not None:
            self._busy_bar.set_label_chrome_extra(ch.busy_bar_label_extra)
            self._busy_bar.apply_theme_font(self.font_size)
        if getattr(self, "cg_widget", None) is not None:
            self.cg_widget.set_theme_color(self.theme_color)
        self.dialog_label.adjustSize()
        self.numeric_info_label.adjustSize()
        self._relayout_overlays()

    def setup_numeric_label(self):
        # 1. 创建用于显示富文本的“数值组件”
        self.numeric_info_label = QLabel(self.image_container) # 以 self.label (图像容器) 为父组件
        self.numeric_info_label.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # 允许显示富文本（HTML 格式）
        self.numeric_info_label.setTextFormat(Qt.TextFormat.RichText) 
        # 设置初始文本（示例）
        self.numeric_info_label.setWordWrap(True)
        self.numeric_info_label.setText("<b>HP:</b> <span style='color:red;'>100</span>")
        
        # 3. 设置半透明背景和字体颜色
        # 为了覆盖图像，设置一个半透明背景，并确保文字清晰可见
        self.numeric_info_label.setStyleSheet(
            styles.numeric_info_label_initial(self.font_size)
        )
        
        # 4. 调整大小策略：根据内容自动调整
        self.numeric_info_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        
        # 5. 初始隐藏（如果需要，你也可以直接显示）
        self.numeric_info_label.hide() 

    def setup_dialog_label(self):
        """初始化对话框标签"""
        self.dialog_label = TypingLabel()
        self.dialog_label.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.dialog_label.clicked.connect(lambda: self.skip_speech_signal.emit())
        self.dialog_label.setTextFormat(Qt.TextFormat.RichText)
        self.dialog_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self.dialog_label.setStyleSheet(
            styles.dialog_label_initial(self.font_size, DIALOG_FRAME_PATH)
        )
        self.dialog_label.setWordWrap(True)
        self.dialog_label.hide()
        self.dialog_label.setParent(self.image_container)

        self.dialog_label.installEventFilter(self)
        self.dialog_label.setMouseTracking(True)
        self.dialog_label.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        dialog_viewport = self.dialog_label.viewport()
        if dialog_viewport is not None:
            dialog_viewport.installEventFilter(self)
            dialog_viewport.setMouseTracking(True)
            dialog_viewport.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        self.name_label = QLabel()
        self.name_label.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        self.name_label.setStyleSheet(
            f"background:transparent; color:white;"
            f"font-size:{self.font_size}; font-weight:700; "
            f"padding:0 16px; border:none;"
        )
        self.name_label.hide()
        self.name_label.setParent(self.image_container)

    def setup_options_widget(self):
        """初始化选项容器，与对话框标签位置相同"""
        self.options_widget = QWidget()
        self.options_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        ch = get_chat_chrome_theme(
            config_manager.config.system_config.chat_ui_theme_path
        )
        # 设置容器的基本样式，与dialog_label相似
        self.options_widget.setStyleSheet(
            styles.options_widget_container(ch.options_container_extra)
        )
        
        self.options_layout = QVBoxLayout(self.options_widget)
        self.options_layout.setContentsMargins(40, 40, 40, 40)
        self.options_layout.setSpacing(10)
        
        # 设置父组件，使其覆盖在图像上
        self.options_widget.setParent(self.image_container)
        self.options_widget.hide()

    def setup_image_label(self):
        """初始化立绘标签"""
        self.sprite_panel = SpritePanel(self.original_width, self.original_height, max_slots_num=self.max_sprite_slots)
        self.sprite_panel.sprite_bounds_changed.connect(self._fit_window_to_sprite)
        # self.label = CrossFadeSprite(self.original_width, self.original_height)
        # self.label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.image_layout.addWidget(self.sprite_panel, 1)

    def setup_input_layout(self):
        """初始化底栏；独立叠在窗口底部，使立绘区可铺满至窗口底边。"""
        self.input_row = QWidget(self)
        self.input_row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.input_row.setStyleSheet("background: transparent;")
        
        # 输入框
        ch0 = get_chat_chrome_theme(
            config_manager.config.system_config.chat_ui_theme_path
        )
        self.input_box = ImageAttachmentTextEdit(self.input_row)
        self.input_box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.input_box.setAcceptDrops(True)
        self.input_box.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.input_box.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.input_box.setMinimumHeight(40)
        self.input_box.setMaximumHeight(78)
        self.input_box.setPlaceholderText(tr("desktop.input_placeholder"))
        self.input_box.setStyleSheet(
            styles.text_edit_input(self.btn_font_size, chrome_extra=ch0.input_bar_extra)
        )
        self.input_box.installEventFilter(self)
        input_viewport = self.input_box.viewport()
        if input_viewport is not None:
            input_viewport.installEventFilter(self)
            input_viewport.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.input_row.installEventFilter(self)
        self.input_box.customContextMenuRequested.connect(self._show_input_box_context_menu)
        self.input_box.image_files_added.connect(self._add_input_image_paths)
        self.input_box.image_pasted.connect(self._add_pasted_input_image)
        # self.input_box.returnPressed.connect(self.sendMessage)
        
        # 发送按钮（圆角由 QPainter 绘制）
        self.send_btn = ChromeSendButton("➤", self.input_row)
        self.send_btn.apply_visual(
            ch0.send_button_extra,
            "#4CAF50",
            "#FFFFFF",
            default_corner_px=12,
            font_px=self._send_btn_font_px(),
        )
        self.send_btn.clicked.connect(self.sendMessage)

        self.mic_button = MicButton(None, self.input_row)
        self.mic_button.set_input_widget(self.input_box)
        self.agent_reply_finished.connect(self.mic_button.resume_asr)
        self.pause_asr_signal.connect(self.mic_button.pause_asr)
        self.mic_button.send_final_transcription.connect(self.sendMessage)
        self.mic_button.apply_window_scale(0.48, ch0)
        self.send_btn.raise_()
        self.mic_button.raise_()

    def _layout_input_row(self) -> None:
        if getattr(self, "input_row", None) is None:
            return
        if getattr(self, "_laying_out_input_row", False):
            return
        self._laying_out_input_row = True
        try:
            if self.is_input_bar_collapsed():
                self.input_row.hide()
                self._last_input_row_y = int(self.height())
                self._last_input_row_h = 0
                self._last_input_inner_w = 0
                self._last_input_x = int(self._input_row_inset_h)
                self._bottom_chrome_h = 0
                self._layout_busy_bar()
                self._update_sprite_reserved_bottom()
                self._relayout_overlays()
                return
            self.input_row.show()
            inset_h = self._input_row_inset_h
            inset_b = self._input_row_inset_bottom
            available_w = max(1, int(self.width()) - 2 * inset_h)
            container_width = (
                self.image_container.width()
                if getattr(self, "image_container", None) is not None and self.image_container.width() > 0
                else self.width()
            )
            overlay_x, overlay_w = self._overlay_width_geometry(container_width)
            inner_w = min(available_w, max(248, overlay_w))
            row_h = 62
            gap_to_dialog = 6
            dialog_geo = self.dialog_label.geometry() if getattr(self, "dialog_label", None) is not None else QRect()
            if (
                getattr(self, "dialog_label", None) is not None
                and self.dialog_label.isVisible()
                and dialog_geo.isValid()
                and dialog_geo.height() > 0
            ):
                y = dialog_geo.bottom() + 1 + gap_to_dialog
            else:
                y = int(self.height()) - row_h - inset_b
            x = max(inset_h, overlay_x)
            y_row = max(0, min(int(y), int(self.height()) - row_h - inset_b))
            self.input_row.setGeometry(x, y_row, inner_w, row_h)
            self.input_box.setGeometry(0, 0, inner_w, row_h)
            icon_size = 24
            gap = 5
            right_pad = 8
            bottom_pad = 7
            btn_y = row_h - icon_size - bottom_pad
            self.send_btn.setFixedSize(icon_size, icon_size)
            self.mic_button.setFixedSize(icon_size, icon_size)
            self.send_btn.move(inner_w - right_pad - icon_size, btn_y)
            self.mic_button.move(inner_w - right_pad - icon_size * 2 - gap, btn_y)
            self.mic_button.raise_()
            self.send_btn.raise_()
            self._last_input_row_y = y_row
            self._last_input_row_h = row_h
            self._last_input_inner_w = inner_w
            self._last_input_x = x
            self._bottom_chrome_h = row_h + inset_b
            self._layout_busy_bar()
            self._update_sprite_reserved_bottom()
            self._relayout_overlays()
        finally:
            self._laying_out_input_row = False

    def _layout_busy_bar(self) -> None:
        """底栏输入条正上方；宽度与输入行一致（与窗口左右 inset 内的可视区同宽）。"""
        bb = getattr(self, "_busy_bar", None)
        if bb is None:
            return
        if self.is_process_hint_collapsed():
            bb.hide_bar()
            return
        if not hasattr(self, "_last_input_row_y"):
            return
        inner_w = self._last_input_inner_w
        x = self._last_input_x
        y_input = self._last_input_row_y
        gap = 4
        bb_w = max(1, inner_w)
        x_bb = x
        bb.setFixedWidth(bb_w)
        bh = bb.height_for_bar_width(bb_w)
        y_bb = max(0, y_input - gap - bh)
        bb.setGeometry(x_bb, y_bb, bb_w, bh)

    def _overlay_reserved_height(self) -> int:
        """立绘底部需要避开的叠层高度；对白框只预留向下伸出的部分。"""
        gap = 4
        if getattr(self, "dialog_label", None) is not None and self.dialog_label.isVisible():
            sprite_geo = self._active_sprite_geometry()
            if sprite_geo.isValid() and sprite_geo.height() > 0:
                return max(0, int(sprite_geo.height() * 0.25))
        if getattr(self, "options_widget", None) is not None and self.options_widget.isVisible():
            return int(self.options_widget.height()) + gap
        return 0

    def _update_sprite_reserved_bottom(self) -> None:
        panel = getattr(self, "sprite_panel", None)
        if panel is None:
            return
        panel.set_reserved_bottom(
            int(getattr(self, "_bottom_chrome_h", 0) or 0)
            + self._overlay_reserved_height()
            + int(getattr(self, "_sprite_dialog_extra_reserved", 0) or 0)
        )

    def _above_chrome_y(self, block_height: int, gap: int = 4) -> int:
        h = int(self.image_container.height()) if self.image_container.height() > 0 else int(self.height())
        return max(0, h - self._bottom_chrome_h - gap - int(block_height))

    def _active_sprite_geometry(self) -> QRect:
        panel = getattr(self, "sprite_panel", None)
        if panel is None:
            return QRect()
        if hasattr(panel, "active_sprite_visible_geometry"):
            visible = panel.active_sprite_visible_geometry()
            if visible.isValid() and visible.height() > 0:
                return visible
        if not hasattr(panel, "active_sprite_geometry"):
            return QRect()
        return panel.active_sprite_geometry()

    def _dialog_y_for_sprite_overlap(
        self,
        sprite_geo: QRect,
        dialog_h: int,
        overlap_ratio: float = 0.25,
    ) -> int:
        """按可见立绘高度反推对白框 y，使其覆盖底部指定比例高度。"""
        target_overlap_h = int(round(sprite_geo.height() * max(0.0, min(1.0, overlap_ratio))))
        target_overlap_h = max(1, min(sprite_geo.height(), target_overlap_h, max(1, int(dialog_h))))
        return sprite_geo.bottom() + 1 - target_overlap_h

    def _overlay_margin_and_content_width(self, container_width: int) -> tuple[int, int]:
        """水平：参照启动时窗口宽度；当前容器更窄时铺满（与可视区同宽），否则按比例留白。"""
        cw = max(1, int(container_width))
        ref = max(1, int(getattr(self, "_overlay_min_ref_width", self.original_width)))
        if cw < ref:
            return 0, cw
        margin_width = int(cw * self.HORIZONTAL_MARGIN_PERCENT)
        return margin_width, cw - (2 * margin_width)

    def _overlay_width_geometry(self, container_width: int) -> tuple[int, int]:
        """对白框和输入框共用的水平几何，保证上下同宽同中心。"""
        cw = max(1, int(container_width))
        _margin_width, base_width = self._overlay_margin_and_content_width(cw)
        ch = get_chat_chrome_theme(
            config_manager.config.system_config.chat_ui_theme_path
        )
        saved_w_pct = int(getattr(config_manager.config.system_config, "dialog_box_width_pct", 0) or 0)
        if saved_w_pct > 0:
            w_pct = max(30, min(100, saved_w_pct)) / 100.0
        else:
            w_pct = max(30, min(100, ch.dialog_width_pct)) / 100.0
        width = max(1, int(base_width * w_pct))
        x = (cw - width) // 2
        return x, width

    def _layout_dialog_label_block(self) -> None:
        """按当前 image_container 尺寸排对话框与跳过按钮。调用前已将 _full_text 赋好。"""
        if self.is_dialog_box_collapsed():
            return
        dlg = self.dialog_label
        sizing = getattr(dlg, "_full_text", "") or dlg.text()
        if not sizing:
            return
        container_width = self.image_container.width() or self.original_width
        margin_width, new_width = self._overlay_width_geometry(container_width)
        dlg.setFixedWidth(new_width)
        dlg.adjustSize()
        image_h = self.image_container.height() or self.height()
        bottom_chrome_h = int(getattr(self, "_bottom_chrome_h", 0) or 0)
        avail_h = max(1, image_h - bottom_chrome_h)
        self._sprite_dialog_extra_reserved = 0
        self._update_sprite_reserved_bottom()
        sprite_geo = self._active_sprite_geometry()
        if sprite_geo.isValid() and sprite_geo.height() > 0:
            preferred_height = int(sprite_geo.height() / 3)
        else:
            preferred_height = int(getattr(self, "_last_input_row_h", 58) or 58)
        min_height = max(58, int(avail_h * 0.08))
        max_height = max(min_height, min(int(avail_h * 0.55), 260))
        height = max(min_height, preferred_height)
        height = min(height, max_height)
        if sprite_geo.isValid() and sprite_geo.height() > 0:
            y = self._dialog_y_for_sprite_overlap(sprite_geo, height)
        else:
            y = self._above_chrome_y(height, gap=4)
        ch = get_chat_chrome_theme(
            config_manager.config.system_config.chat_ui_theme_path
        )
        y = max(0, int(y) + ch.dialog_offset_y)
        if not (sprite_geo.isValid() and sprite_geo.height() > 0):
            y = min(y, avail_h - height)
        else:
            row_h = int(getattr(self, "_last_input_row_h", 62) or 62)
            inset_b = int(getattr(self, "_input_row_inset_bottom", 10) or 10)
            gap_to_input = 6
            max_dialog_y = image_h - row_h - inset_b - gap_to_input - height
            if y > max_dialog_y:
                self._sprite_dialog_extra_reserved = max(0, int(y - max_dialog_y))
                self._update_sprite_reserved_bottom()
                y = max(0, max_dialog_y)
            sprite_geo = self._active_sprite_geometry()
            if sprite_geo.isValid() and sprite_geo.height() > 0:
                y = max(
                    0,
                    self._dialog_y_for_sprite_overlap(sprite_geo, height)
                    + ch.dialog_offset_y,
                )
        dlg.setGeometry(margin_width, y, new_width, height)
        dlg.raise_()
        # Position name label above dialog
        nl = getattr(self, "name_label", None)
        if nl is not None and nl.isVisible():
            nl.setFixedWidth(new_width)
            nl.adjustSize()
            name_y = max(0, y - nl.height() - 3)
            nl.setGeometry(margin_width, name_y, new_width, nl.height())

        self._update_sprite_reserved_bottom()
        if not getattr(self, "_laying_out_input_row", False):
            self._layout_input_row()

    def _dialog_edges_at(self, dialog_pos: QPoint) -> Qt.Edge:
        dlg = getattr(self, "dialog_label", None)
        if dlg is None or not dlg.isVisible():
            return Qt.Edge(0)
        m = int(getattr(self, "_dialog_resize_margin", 8) or 8)
        w, h = dlg.width(), dlg.height()
        if w <= 0 or h <= 0:
            return Qt.Edge(0)
        edges = Qt.Edge(0)
        if dialog_pos.x() <= m:
            edges |= Qt.Edge.LeftEdge
        if dialog_pos.x() >= w - m:
            edges |= Qt.Edge.RightEdge
        if dialog_pos.y() <= m:
            edges |= Qt.Edge.TopEdge
        if dialog_pos.y() >= h - m:
            edges |= Qt.Edge.BottomEdge
        return edges

    def _is_dialog_label_event_target(self, obj) -> bool:
        dlg = getattr(self, "dialog_label", None)
        if dlg is None:
            return False
        if obj is dlg:
            return True
        viewport = dlg.viewport() if hasattr(dlg, "viewport") else None
        return obj is viewport

    def _dialog_pos_from_event_target(self, obj, pos: QPoint) -> QPoint:
        dlg = getattr(self, "dialog_label", None)
        if dlg is None or obj is dlg or not isinstance(obj, QWidget):
            return pos
        try:
            global_pos = obj.mapToGlobal(pos)
            return dlg.mapFromGlobal(global_pos)
        except Exception:
            return pos

    def _is_input_bar_event_target(self, obj) -> bool:
        if obj is getattr(self, "input_row", None):
            return True
        if obj is getattr(self, "input_box", None):
            return True
        input_box = getattr(self, "input_box", None)
        if input_box is not None and hasattr(input_box, "viewport") and obj is input_box.viewport():
            return True
        return obj in (getattr(self, "send_btn", None), getattr(self, "mic_button", None))

    def _begin_dialog_resize(self, edges: Qt.Edge, global_pos: QPoint) -> None:
        if edges == Qt.Edge(0):
            return
        self._clear_hover_resize_cursor()
        self._dialog_resizing = True
        self._dialog_resize_edges = edges
        self._dialog_resize_start_global = QPoint(global_pos)
        self._dialog_resize_start_geometry = QRect(self.dialog_label.geometry())
        self._dialog_resize_start_size = QSize(self.dialog_label.size())
        self.drag_position = None
        self.dialog_label.grabMouse()

    def _apply_dialog_resize_step(self, global_pos: QPoint) -> None:
        dg = global_pos - self._dialog_resize_start_global
        container_width = self.image_container.width() or self.original_width
        _, base_width = self._overlay_margin_and_content_width(container_width)
        avail_h = max(1, (self.image_container.height() or self.height()) - self._bottom_chrome_h)
        min_w = max(260, int(base_width * 0.3))
        max_w = max(min_w, int(base_width))
        min_h = max(90, int(avail_h * 0.14))
        max_h = max(min_h, min(int(avail_h * 0.5), 260))
        edges = getattr(self, "_dialog_resize_edges", Qt.Edge(0))
        start = self._dialog_resize_start_geometry
        new_w = start.width()
        new_h = start.height()
        if edges & Qt.Edge.RightEdge:
            new_w = start.width() + dg.x()
        elif edges & Qt.Edge.LeftEdge:
            new_w = start.width() - dg.x()
        if edges & Qt.Edge.BottomEdge:
            new_h = start.height() + dg.y()
        elif edges & Qt.Edge.TopEdge:
            new_h = start.height() - dg.y()
        new_w = max(min_w, min(max_w, new_w))
        new_h = max(min_h, min(max_h, new_h))
        sc = config_manager.config.system_config.model_copy(deep=True)
        sc.dialog_box_width_pct = max(30, min(100, round(new_w / max(1, base_width) * 100)))
        sc.dialog_box_height_pct = max(14, min(70, round(new_h / max(1, avail_h) * 100)))
        config_manager.config.system_config = sc
        self._layout_dialog_label_block()

    def _end_dialog_resize(self) -> None:
        if not self._dialog_resizing:
            return
        self._dialog_resizing = False
        self._dialog_resize_edges = Qt.Edge(0)
        if QWidget.mouseGrabber() is self.dialog_label:
            self.dialog_label.releaseMouse()
        self._clear_hover_resize_cursor()
        self._persist_dialog_box_size()

    def _relayout_overlays(self) -> None:
        """窗口缩放时重算选项区 / 台词框几何。"""
        if getattr(self, "options_widget", None) is None:
            return
        if self.options_widget.isVisible() and self.current_options:
            self.setOptions(self.current_options)
        elif self.dialog_label.isVisible() and not self.is_dialog_box_collapsed():
            self._layout_dialog_label_block()
    
    def setup_image_thread(self):
        """设置图像显示线程"""
        self.display_thread = ImageDisplayThread(self.image_queue)
        self.display_thread.update_signal.connect(self.update_image)
        self.display_thread.start()

    def setup_background_label(self):
        self.background_label = QLabel(self)
        self.background_label.setGeometry(0, 0, self.original_width, self.original_height)
        self.background_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.background_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def _scale_and_apply_background(self) -> None:
        """将底图按当前窗口尺寸铺满（含底栏 input 区域）。"""
        if (
            self._background_source_pixmap is not None
            and not self._background_source_pixmap.isNull()
        ):
            scaled = self._background_source_pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.background_label.setPixmap(scaled)
        self.background_label.setGeometry(0, 0, self.width(), self.height())
        self.background_label.lower()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not getattr(self, "_win_dwm_applied", False):
            self._win_dwm_applied = True
            from ui.win_frameless_dwm import apply_win_frameless_dwm_hacks

            # Win11+：DWMWA_COLOR_NONE 抑制薄边框；Win10 可能仍有一丝灰线属系统限制
            apply_win_frameless_dwm_hacks(self, border_color_none=True)

    def _raise_input_and_toolbar(self) -> None:
        """将输入条、工具栏与调节角置于前；若 busy bar 正在显示则最后抬到最上层。"""
        if getattr(self, "input_row", None) is not None and not self.is_input_bar_collapsed():
            self.input_row.raise_()
        else:
            if getattr(self, "input_box", None) is not None:
                self.input_box.raise_()
            if getattr(self, "mic_button", None) is not None:
                self.mic_button.raise_()
            if getattr(self, "send_btn", None) is not None:
                self.send_btn.raise_()
        if getattr(self, "toolbar", None) is not None:
            if hasattr(self, "_layout_toolbar_geometry"):
                self._layout_toolbar_geometry()
            self.toolbar.raise_()
        for name in ("_resize_grip_bl", "_resize_grip_br"):
            g = getattr(self, name, None)
            if g is not None:
                g.raise_()
        bb = getattr(self, "_busy_bar", None)
        if bb is not None and bb.isVisible() and not self.is_process_hint_collapsed():
            bb.raise_()

    def _setup_resize_corner_hit_widgets(self) -> None:
        """左下/右下：分层透明时 α=0 区域不命中；极小 α>0 叠在最上层抓落实控。"""
        self._resize_grip_bl = QWidget(self)
        self._resize_grip_br = QWidget(self)
        self._resize_grip_bl.setCursor(QCursor(Qt.CursorShape.SizeBDiagCursor))
        self._resize_grip_br.setCursor(QCursor(Qt.CursorShape.SizeFDiagCursor))
        for gw in (self._resize_grip_bl, self._resize_grip_br):
            gw.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            gw.setStyleSheet("background-color: transparent; border: none;")
            gw.setMouseTracking(True)
            gw.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._layout_resize_corner_hit_widgets()

    def _layout_resize_corner_hit_widgets(self) -> None:
        bl = getattr(self, "_resize_grip_bl", None)
        br = getattr(self, "_resize_grip_br", None)
        if bl is None or br is None:
            return
        g = int(self._window_corner_grip_px)
        w, h = max(1, self.width()), max(1, self.height())
        bl.setGeometry(0, max(0, h - g), g, g)
        br.setGeometry(max(0, w - g), max(0, h - g), g, g)
        bl.show()
        br.show()

    def _resize_edges_from_corner_hit_widget(self, obj: object) -> Qt.Edge:
        if obj is getattr(self, "_resize_grip_bl", None):
            return Qt.LeftEdge | Qt.BottomEdge
        if obj is getattr(self, "_resize_grip_br", None):
            return Qt.RightEdge | Qt.BottomEdge
        return Qt.Edge(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_input_row()
        self.apply_font_styles()
        self.cg_widget.setGeometry(
            0,
            0,
            max(1, self.image_container.width()),
            max(1, self.image_container.height()),
        )
        self._scale_and_apply_background()
        self._layout_resize_corner_hit_widgets()
        self._raise_input_and_toolbar()

    def _fit_window_to_sprite(self) -> None:
        """根据当前立绘显示尺寸调整主窗口，窗口不再反向决定立绘大小。"""
        if getattr(self, "_auto_fitting_sprite_window", False):
            return
        if getattr(self, "current_background_path", None):
            return
        panel = getattr(self, "sprite_panel", None)
        if panel is None:
            return
        sprite_size = panel.active_sprite_size()
        if sprite_size.width() <= 0 or sprite_size.height() <= 0:
            return

        self._auto_fitting_sprite_window = True
        try:
            self._layout_input_row()
            bottom_h = int(getattr(self, "_bottom_chrome_h", 80) or 80)
            side_pad = 28
            top_pad = 24
            overlay_h = self._overlay_reserved_height()
            target_w = max(360, sprite_size.width() + side_pad * 2)
            target_h = max(260, sprite_size.height() + bottom_h + overlay_h + top_pad)

            screen = QGuiApplication.screenAt(self.frameGeometry().center()) or QGuiApplication.primaryScreen()
            avail = screen.availableGeometry() if screen is not None else self._united_available_screen_rect()
            if not avail.isNull():
                target_w = min(target_w, max(360, int(avail.width() * 0.86)))
                target_h = min(target_h, max(260, int(avail.height() * 0.86)))

            target = QSize(int(target_w), int(target_h))
            if target == getattr(self, "_last_auto_fit_size", QSize()):
                return

            old_center = self.frameGeometry().center()
            self.resize(target)
            fg = self.frameGeometry()
            fg.moveCenter(old_center)
            if not avail.isNull():
                if fg.left() < avail.left():
                    fg.moveLeft(avail.left())
                if fg.top() < avail.top():
                    fg.moveTop(avail.top())
                if fg.right() > avail.right():
                    fg.moveRight(avail.right())
                if fg.bottom() > avail.bottom():
                    fg.moveBottom(avail.bottom())
            self.move(fg.topLeft())
            self._last_auto_fit_size = target
        finally:
            self._auto_fitting_sprite_window = False

    def _install_resize_event_filters(self) -> None:
        """子控件会吞掉边缘鼠标事件，需过滤后才能在无边框窗体上缩放。"""
        self.installEventFilter(self)
        for w in self.findChildren(QWidget):
            w.installEventFilter(self)
        self._enable_resize_hover_tracking()

    def _enable_resize_hover_tracking(self) -> None:
        """无按键移动也要收到 Hover/MouseMove，角落才会显示缩放光标。"""
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        for w in self.findChildren(QWidget):
            w.setMouseTracking(True)
            w.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def _update_resize_hover_cursor_at_global(self, global_pos: QPoint) -> None:
        """按屏幕坐标更新/清除缩放光标（用于 HoverMove / 无键 MouseMove）。"""
        if self._resizing:
            return
        lp = self.mapFromGlobal(global_pos)
        if not self.rect().contains(lp):
            self._clear_hover_resize_cursor()
            return
        e = self._resize_edges_for_hover(lp)
        if e != Qt.Edge(0):
            self._update_resize_cursor(e)
        else:
            self._clear_hover_resize_cursor()

    def _bottom_corner_resize_edges_at(self, window_pos: QPoint) -> Qt.Edge:
        """窗口客户区左下/右下各一小方块区域：拖曳同时改宽高。"""
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return Qt.Edge(0)
        g = int(self._window_corner_grip_px)
        le = Qt.Edge.LeftEdge
        ri = Qt.Edge.RightEdge
        bt = Qt.Edge.BottomEdge
        if window_pos.x() <= g and window_pos.y() >= h - g:
            return le | bt
        if window_pos.x() >= w - g and window_pos.y() >= h - g:
            return ri | bt
        return Qt.Edge(0)

    def _resize_edges_for_hover(self, window_pos: QPoint) -> Qt.Edge:
        c = self._bottom_corner_resize_edges_at(window_pos)
        if c != Qt.Edge(0):
            return c
        return self._edges_at(window_pos)

    def _edges_at(self, pos: QPoint) -> Qt.Edge:
        """窗口客户区坐标下的可缩放边（可组合为角）。"""
        m = self._resize_margin
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return Qt.Edge(0)
        edges = Qt.Edge(0)
        if pos.x() <= m:
            edges |= Qt.Edge.LeftEdge
        if pos.x() >= w - m:
            edges |= Qt.Edge.RightEdge
        if pos.y() <= m:
            edges |= Qt.Edge.TopEdge
        if pos.y() >= h - m:
            edges |= Qt.Edge.BottomEdge
        return edges

    def _cursor_for_edges(self, edges: Qt.Edge) -> QCursor:
        le, ri = Qt.Edge.LeftEdge, Qt.Edge.RightEdge
        tp, bt = Qt.Edge.TopEdge, Qt.Edge.BottomEdge
        if edges in (le | tp, ri | bt):
            return QCursor(Qt.CursorShape.SizeFDiagCursor)
        if edges in (ri | tp, le | bt):
            return QCursor(Qt.CursorShape.SizeBDiagCursor)
        if edges & (le | ri):
            return QCursor(Qt.CursorShape.SizeHorCursor)
        if edges & (tp | bt):
            return QCursor(Qt.CursorShape.SizeVerCursor)
        return QCursor(Qt.CursorShape.ArrowCursor)

    def _clear_hover_resize_cursor(self) -> None:
        self._hover_resize_edges = Qt.Edge(0)
        if self._resize_cursor_override_active:
            QGuiApplication.restoreOverrideCursor()
            self._resize_cursor_override_active = False

    def _update_resize_cursor(self, edges: Qt.Edge) -> None:
        if edges == self._hover_resize_edges:
            return
        if self._resize_cursor_override_active:
            QGuiApplication.restoreOverrideCursor()
            self._resize_cursor_override_active = False
        self._hover_resize_edges = edges
        if edges != Qt.Edge(0):
            QGuiApplication.setOverrideCursor(self._cursor_for_edges(edges))
            self._resize_cursor_override_active = True
            le, ri = Qt.Edge.LeftEdge, Qt.Edge.RightEdge
            bt = Qt.Edge.BottomEdge
            if edges in (le | bt, ri | bt) and not getattr(
                self, "_resize_corner_hint_shown", False
            ):
                self._resize_corner_hint_shown = True
                QToolTip.showText(
                    QCursor.pos() + QPoint(0, 18),
                    "拖动可调整窗口大小",
                    self,
                    QRect(),
                    3500,
                )

    def _begin_resize(self, edges: Qt.Edge, global_pos: QPoint) -> None:
        self._clear_hover_resize_cursor()
        if edges == Qt.Edge(0):
            return
        # 分层 + 无边框时 QWindow.startSystemResize 常无效，统一用手动几何
        self._resizing = True
        self._resize_mask = edges
        self._resize_start_global = QPoint(global_pos)
        self._resize_start_geom = QRect(self.geometry())
        self.drag_position = None
        self.grabMouse()

    def _end_resize(self) -> None:
        self._resizing = False
        self._resize_mask = Qt.Edge(0)
        if QWidget.mouseGrabber() is self:
            self.releaseMouse()
        self._clear_hover_resize_cursor()

    def _apply_resize_step(self, global_pos: QPoint) -> None:
        dg = global_pos - self._resize_start_global
        g = QRect(self._resize_start_geom)
        min_w = max(1, self.minimumWidth())
        min_h = max(1, self.minimumHeight())
        e = self._resize_mask
        if e & Qt.Edge.LeftEdge:
            new_w = g.width() - dg.x()
            if new_w >= min_w:
                g.setLeft(g.left() + dg.x())
                g.setWidth(new_w)
        if e & Qt.Edge.RightEdge:
            g.setWidth(max(min_w, g.width() + dg.x()))
        if e & Qt.Edge.TopEdge:
            new_h = g.height() - dg.y()
            if new_h >= min_h:
                g.setTop(g.top() + dg.y())
                g.setHeight(new_h)
        if e & Qt.Edge.BottomEdge:
            g.setHeight(max(min_h, g.height() + dg.y()))
        self.setGeometry(g)

    def nativeEvent(self, eventType, message):
        """
        Windows：分层透明窗对全透明像素按 alpha 命中易穿透桌面。
        对客户区统一返回 HTCLIENT，缩放由 Qt startSystemResize / 手动几何完成。
        """
        if sys.platform != "win32":
            return super().nativeEvent(eventType, message)
        try:
            et = bytes(eventType)
        except TypeError:
            et = eventType
        if et != b"windows_generic_MSG" or message is None:
            return super().nativeEvent(eventType, message)
        addr = None
        try:
            addr = int(message)
        except (TypeError, ValueError):
            try:
                addr = int(message.__int__())
            except Exception:
                return super().nativeEvent(eventType, message)
        HTCLIENT = 1
        WM_NCHITTEST = 0x0084
        try:
            from ctypes import wintypes

            msg = ctypes.cast(addr, ctypes.POINTER(wintypes.MSG)).contents
        except (TypeError, ValueError, OverflowError, ctypes.ArgumentError, OSError):
            return super().nativeEvent(eventType, message)
        if msg.message == WM_NCHITTEST and self.isVisible():
            x = ctypes.c_int16(msg.lParam & 0xFFFF).value
            y = ctypes.c_int16((msg.lParam >> 16) & 0xFFFF).value
            gp = QPoint(int(x), int(y))
            lp = self.mapFromGlobal(gp)
            if self.rect().contains(lp):
                return True, HTCLIENT
        return super().nativeEvent(eventType, message)

    def setBackgroundImage(self, image_path: str):
        """
        设置窗口背景图片，图片将缩放填充整个窗口。
        
        :param image_path: 背景图片文件的路径。
        """
        if image_path == self.current_background_path:
            return
        self.sprite_panel.remove_all()  # 清除所有立绘显示
        if not os.path.exists(image_path):
            print(f"Background image file not found: {image_path}")
            self._background_source_pixmap = None
            # 可以设置一个纯色背景作为 fallback
            self.background_label.setStyleSheet(styles.background_label_load_failed())
            self.background_label.setText("背景图加载失败")
            self._raise_input_and_toolbar()
            return

        pixmap = QPixmap(image_path)
        self._background_source_pixmap = pixmap
        self.background_label.setText("")
        self.background_label.setStyleSheet("")
        self._scale_and_apply_background()
        self.current_background_path = image_path
        self.background_image_changed.emit(image_path)
        self._raise_input_and_toolbar()

    def update_image(self, image, character_name="", scale_rate=1.0):
        """更新显示图像"""
        self.original_image = image
        if image.size == 0:
            self.sprite_panel.remove(character_name)
        else:
            self.sprite_panel.switch_sprite(character_name, image, scale_rate)
            if character_name:
                self.sprite_panel.remove_except(character_name)
                self.sprite_panel.remove("")

    def switch_active_character(self, character_name: str) -> None:
        """切换当前角色，并通过正常对白流程加载目标角色立绘。"""
        name = str(character_name or "").strip()
        if not name:
            return
        rt = try_get_app_runtime()
        if rt is not None and rt.active_character is not None:
            name = rt.active_character.set_name(name)
            if hasattr(rt.agent_backend, "reset_session"):
                rt.agent_backend.reset_session()
        else:
            config_manager.set_active_character_name(name)

        self.setNotification(tr("desktop.menu.notify_character_switched", name=name))
        if rt is not None:
            from core.messaging.messages import TTSOutputMessage

            entry_sprite = character_entry_sprite(name, config_manager)
            rt.audio_path_queue.put(
                TTSOutputMessage(
                    audio_path="",
                    name=name,
                    text=character_entry_line(name),
                    asset_id=entry_sprite.asset_id,
                    emotion=entry_sprite.emotion,
                    is_system_message=False,
                    timeout=0,
                )
            )
        else:
            self.setDisplayWords(f"<b>{name}</b>：{character_entry_line(name)}")

    def update_sprite_animation(self, frames, character_name="", scale_rate=1.0, frame_interval_ms=120):
        """更新多帧立绘动画。"""
        if not frames:
            return
        self.original_image = frames[0]
        self.sprite_panel.switch_animation(
            character_name,
            frames,
            scale_rate,
            frame_interval_ms,
        )
        if character_name:
            self.sprite_panel.remove_except(character_name)
            self.sprite_panel.remove("")

    def _append_input_image_reference(self, image_path: str) -> None:
        path = Path(str(image_path or "")).expanduser()
        if not path.is_file():
            return
        text = f"[图片: {path.resolve().as_posix()}]"
        cursor = self.input_box.textCursor()
        current = self.input_box.toPlainText()
        if current and not current.endswith("\n"):
            cursor.insertText("\n")
        cursor.insertText(text + "\n")
        self.input_box.setTextCursor(cursor)
        self.input_box.setFocus()

    def _add_input_image_paths(self, paths: list[str]) -> None:
        added = 0
        for raw in paths or []:
            path = Path(str(raw or "")).expanduser()
            if not path.is_file() or path.suffix.lower() not in INPUT_IMAGE_SUFFIXES:
                continue
            self._append_input_image_reference(path.as_posix())
            added += 1
        if added:
            self.setNotification(f"已加入 {added} 张图片")

    def _add_pasted_input_image(self, image_data) -> None:
        image = QImage()
        if isinstance(image_data, QImage):
            image = image_data
        elif isinstance(image_data, QPixmap):
            image = image_data.toImage()
        if image.isNull():
            return
        out_dir = get_app_paths().input_images_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"pasted_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.png"
        if image.save(out_path.as_posix(), "PNG"):
            self._append_input_image_reference(out_path.as_posix())
            self.setNotification("已加入 1 张图片")

    def sendMessage(self):
        """发送消息函数"""
        if self.is_input_bar_collapsed():
            self.setNotification(tr("desktop.menu.notify_input_bar_collapsed_send"))
            return
        message = self.input_box.toPlainText().strip()
        if message:
            print(f"UI发送消息: {message}")
            self.input_box.clear()
            self.input_box.setPlaceholderText(tr("desktop.sending"))
            self.mic_button.asr_pause_requested.emit()
            
            self.message_submitted.emit(message)  # 发出消息提交信号
    
    def update_numeric_info(self, html_text: str):
        """
        更新数值组件显示的富文本内容。
        例如: window.update_numeric_info("<b>EXP:</b> <span style='color:lime;'>+15</span>")
        """
        self.numeric_info_label.setText(html_text)
        
        # 内容变化后，需要重新调整大小并重新定位
        self.numeric_info_label.adjustSize()
        
        # 如果内容为空，隐藏组件
        if not html_text.strip():
            self.numeric_info_label.hide()
        else:
            self.numeric_info_label.show()
            self.numeric_info_label.lower()  # below sprite layer
            self._raise_input_and_toolbar()
        self.numeric_info_changed.emit(html_text)

    def setBusyBar(self, text: str, duration_seconds: float = 3.0) -> None:
        """
        显示底栏加载条（文案 + 不确定进度条）。
        duration_seconds > 0 时自动隐藏；<= 0 时保持直到传入空字符串。
        工作线程请用 UIUpdateManager.post_busy_bar / hide_busy_bar。
        """
        bb = getattr(self, "_busy_bar", None)
        if bb is None:
            return
        text = (text or "").strip()
        if not (text or "").strip():
            self._last_busy_bar_text = ""
            self._last_busy_bar_duration = 0.0
            bb.hide_bar()
            return
        self._last_busy_bar_text = text
        self._last_busy_bar_duration = float(duration_seconds)
        if self.is_process_hint_collapsed():
            bb.hide_bar()
            return
        # 先更新文案再算高度，否则 heightForWidth 仍按旧文本排版
        bb.show_with(text, duration_seconds)
        self._layout_busy_bar()
        self._raise_input_and_toolbar()

    def setNotification(self, message):
        """设置提示词"""
        text = str(message or "").strip()
        if self.is_input_bar_collapsed():
            self.notification_changed.emit(message)
            return
        self.input_box.setPlaceholderText(text)
        if text:
            self.input_box.setToolTip(text)
        self.notification_changed.emit(message)

    def _chat_delivery_channel_is_external(self) -> bool:
        channel = str(
            getattr(config_manager.config.system_config, "chat_delivery_channel", "desktop_chat")
            or "desktop_chat"
        ).strip().lower()
        return channel != "desktop_chat"

    def apply_chat_delivery_visibility(self) -> None:
        external = self._chat_delivery_channel_is_external()
        if bool(getattr(self, "_external_chat_display_hidden", False)) == external:
            if external:
                self._hide_desktop_chat_chrome()
            return
        self._external_chat_display_hidden = external
        if external:
            self._hide_desktop_chat_chrome()
            return
        self._layout_input_row()
        if not self._process_hint_collapsed and self._last_busy_bar_text:
            bb = getattr(self, "_busy_bar", None)
            if bb is not None:
                bb.show_with(self._last_busy_bar_text, self._last_busy_bar_duration)
                self._layout_busy_bar()
        if not self._dialog_box_collapsed and self._last_dialog_html:
            self.show_dialog_box(persist=False)
        else:
            self._update_sprite_reserved_bottom()
            self._relayout_overlays()
            self._raise_input_and_toolbar()

    def _hide_desktop_chat_chrome(self) -> None:
        if getattr(self, "input_box", None) is not None:
            self.input_box.clearFocus()
        if getattr(self, "input_row", None) is not None:
            self.input_row.hide()
        if getattr(self, "dialog_label", None) is not None:
            if getattr(self.dialog_label, "_is_typing", False):
                self.dialog_label.typing_timer.stop()
                self.dialog_label._is_typing = False
            self.dialog_label.hide()
        if hasattr(self, "name_label"):
            self.name_label.hide()
        if getattr(self, "options_widget", None) is not None:
            self.options_widget.hide()
        bb = getattr(self, "_busy_bar", None)
        if bb is not None:
            bb.hide_bar()
        self._bottom_chrome_h = 0
        self._sprite_dialog_extra_reserved = 0
        self._update_sprite_reserved_bottom()
        self._relayout_overlays()
        self._raise_input_and_toolbar()

    def setDisplayWords(self, text):
        """显示人物说的话"""
        import re
        if text:
            original_text = text
            m = re.search(r'<b([^>]*)>([^<]+)</b>\s*[：:]?', text)
            if m and hasattr(self, 'name_label'):
                name = m.group(2)
                attrs = m.group(1)
                color_match = re.search(r"color\s*:\s*([^;'\"]+)", attrs)
                color = color_match.group(1).strip() if color_match else "white"
                self._last_dialog_name = name
                self._last_dialog_name_color = color
                self.name_label.setText(name)
                # Only update stylesheet if color changed — avoids full widget-tree recalc
                last = getattr(self, '_name_label_color', '')
                if color != last:
                    self._name_label_color = color
                    self.name_label.setStyleSheet(
                        f"background:transparent; color:{color}; "
                        f"font-size:{self.font_size}; font-weight:700; "
                        f"padding:0 16px; border:none;"
                )
                self.name_label.show()
                self.name_label.raise_()
                text = text[:m.start()] + text[m.end():]
                text = re.sub(r'^<p[^>]*>\s*</p>\s*', '', text, count=1)
            elif hasattr(self, 'name_label'):
                self._last_dialog_name = ""
                self._last_dialog_name_color = ""
                self.name_label.hide()

            self._last_dialog_html = text
            self.options_widget.hide()
            if self.is_dialog_box_collapsed():
                if getattr(self.dialog_label, "_is_typing", False):
                    self.dialog_label.typing_timer.stop()
                    self.dialog_label._is_typing = False
                self.dialog_label._full_text = text
                self.dialog_label._final_html_text = original_text
                self.dialog_label.setText(text)
                self.dialog_label.hide()
                if hasattr(self, 'name_label'):
                    self.name_label.hide()
                self._sprite_dialog_extra_reserved = 0
                self._update_sprite_reserved_bottom()
                self._layout_input_row()
                self._raise_input_and_toolbar()
                self.display_words_changed.emit(text)
                return

            # Temporarily show full text for layout measurement, then typewriter overwrites
            self.dialog_label.setText(text)
            self.dialog_label._full_text = text
            self.dialog_label.show()
            self._layout_dialog_label_block()
            self.dialog_label.setDisplayWords(text)
            self._raise_input_and_toolbar()
            self.display_words_changed.emit(text)
        else:
            self._last_dialog_html = ""
            self._last_dialog_name = ""
            self._last_dialog_name_color = ""
            if getattr(self.dialog_label, "_is_typing", False):
                self.dialog_label.typing_timer.stop()
                self.dialog_label._is_typing = False
            self.dialog_label._full_text = ""
            self.dialog_label._final_html_text = ""
            self.dialog_label.setText("")
            self.dialog_label.hide()
            self._sprite_dialog_extra_reserved = 0
            if hasattr(self, 'name_label'):
                self.name_label.hide()
            self._update_sprite_reserved_bottom()
            self._layout_input_row()
            self._raise_input_and_toolbar()
            self.display_words_changed.emit("")

    def is_dialog_box_collapsed(self) -> bool:
        return bool(getattr(self, "_external_chat_display_hidden", False)) or bool(getattr(self, "_dialog_box_collapsed", False))

    def _persist_dialog_box_collapsed(self) -> None:
        try:
            sc = config_manager.config.system_config.model_copy(deep=True)
            sc.dialog_box_collapsed = bool(getattr(self, "_dialog_box_collapsed", False))
            config_manager.config.system_config = sc
            config_manager.save_system_config()
        except Exception as e:
            _logger.warning("保存对白框收起状态失败: %s", e)

    def set_dialog_box_collapsed(self, collapsed: bool, *, persist: bool = True) -> None:
        collapsed = bool(collapsed)
        if getattr(self, "_external_chat_display_hidden", False) and not collapsed:
            self._hide_desktop_chat_chrome()
            return
        if self._dialog_box_collapsed == collapsed:
            if not collapsed and self._last_dialog_html and not self.dialog_label.isVisible():
                self.show_dialog_box(persist=persist)
            return
        self._dialog_box_collapsed = collapsed
        if collapsed:
            if getattr(self.dialog_label, "_is_typing", False):
                self.dialog_label.typing_timer.stop()
                self.dialog_label._is_typing = False
            if self.dialog_label.isVisible():
                current_text = getattr(self.dialog_label, "_final_html_text", "") or getattr(self.dialog_label, "_full_text", "") or self.dialog_label.text()
                if current_text and not self._last_dialog_html:
                    self._last_dialog_html = current_text
            self.dialog_label.hide()
            if hasattr(self, "name_label"):
                self.name_label.hide()
            self._sprite_dialog_extra_reserved = 0
            self._update_sprite_reserved_bottom()
            self._layout_input_row()
            self._raise_input_and_toolbar()
            self.setNotification(tr("desktop.menu.notify_dialog_box_collapsed"))
        else:
            self.show_dialog_box(persist=False)
        if persist:
            self._persist_dialog_box_collapsed()

    def collapse_dialog_box(self) -> None:
        """收起当前对白框，但保留最后一条对白内容。"""
        self.set_dialog_box_collapsed(True)

    def show_dialog_box(self, *, persist: bool = True) -> None:
        """恢复显示已收起的对白框。"""
        if getattr(self, "_external_chat_display_hidden", False):
            return
        self._dialog_box_collapsed = False
        text = self._last_dialog_html or getattr(self.dialog_label, "_final_html_text", "") or getattr(self.dialog_label, "_full_text", "")
        if text:
            self.dialog_label.setText(text)
            self.dialog_label._full_text = text
            self.dialog_label._final_html_text = text
            self.dialog_label.show()
            if hasattr(self, "name_label") and self._last_dialog_name:
                self.name_label.setText(self._last_dialog_name)
                color = self._last_dialog_name_color or "white"
                if color != getattr(self, "_name_label_color", ""):
                    self._name_label_color = color
                    self.name_label.setStyleSheet(
                        f"background:transparent; color:{color}; "
                        f"font-size:{self.font_size}; font-weight:700; "
                        f"padding:0 16px; border:none;"
                    )
                self.name_label.show()
                self.name_label.raise_()
            self._layout_dialog_label_block()
            self._raise_input_and_toolbar()
            self.display_words_changed.emit(text)
        else:
            self._update_sprite_reserved_bottom()
            self._layout_input_row()
            self._raise_input_and_toolbar()
        self.setNotification(tr("desktop.menu.notify_dialog_box_shown"))
        if persist:
            self._persist_dialog_box_collapsed()

    def show_dialog_context_menu(self, global_pos: QPoint) -> None:
        menu = QMenu(self)
        if self.is_dialog_box_collapsed():
            toggle_action = QAction(tr("desktop.menu.show_dialog_box"), self)
            toggle_action.triggered.connect(lambda: self.set_dialog_box_collapsed(False))
        else:
            toggle_action = QAction(tr("desktop.menu.collapse_dialog_box"), self)
            toggle_action.triggered.connect(lambda: self.set_dialog_box_collapsed(True))
        menu.addAction(toggle_action)
        if self.is_process_hint_collapsed():
            process_action = QAction(tr("desktop.menu.show_process_hint"), self)
            process_action.triggered.connect(lambda: self.set_process_hint_collapsed(False))
        else:
            process_action = QAction(tr("desktop.menu.collapse_process_hint"), self)
            process_action.triggered.connect(lambda: self.set_process_hint_collapsed(True))
        menu.addAction(process_action)
        menu.setStyleSheet(styles.menu_popup())
        menu.exec(global_pos)

    def is_process_hint_collapsed(self) -> bool:
        return bool(getattr(self, "_external_chat_display_hidden", False)) or bool(getattr(self, "_process_hint_collapsed", False))

    def _persist_process_hint_collapsed(self) -> None:
        try:
            sc = config_manager.config.system_config.model_copy(deep=True)
            sc.process_hint_collapsed = bool(getattr(self, "_process_hint_collapsed", False))
            config_manager.config.system_config = sc
            config_manager.save_system_config()
        except Exception as e:
            _logger.warning("保存过程提示收起状态失败: %s", e)

    def set_process_hint_collapsed(self, collapsed: bool, *, persist: bool = True) -> None:
        collapsed = bool(collapsed)
        if getattr(self, "_external_chat_display_hidden", False) and not collapsed:
            self._hide_desktop_chat_chrome()
            return
        self._process_hint_collapsed = collapsed
        bb = getattr(self, "_busy_bar", None)
        if collapsed:
            if bb is not None:
                bb.hide_bar()
            self.setNotification(tr("desktop.menu.notify_process_hint_collapsed"))
        else:
            if bb is not None and self._last_busy_bar_text:
                bb.show_with(self._last_busy_bar_text, self._last_busy_bar_duration)
                self._layout_busy_bar()
                self._raise_input_and_toolbar()
            self.setNotification(tr("desktop.menu.notify_process_hint_shown"))
        if persist:
            self._persist_process_hint_collapsed()

    def is_input_bar_collapsed(self) -> bool:
        return bool(getattr(self, "_external_chat_display_hidden", False)) or bool(getattr(self, "_input_bar_collapsed", False))

    def _persist_input_bar_collapsed(self) -> None:
        try:
            sc = config_manager.config.system_config.model_copy(deep=True)
            sc.input_bar_collapsed = bool(getattr(self, "_input_bar_collapsed", False))
            config_manager.config.system_config = sc
            config_manager.save_system_config()
        except Exception as e:
            _logger.warning("保存输入栏收起状态失败: %s", e)

    def set_input_bar_collapsed(self, collapsed: bool, *, persist: bool = True) -> None:
        collapsed = bool(collapsed)
        if getattr(self, "_external_chat_display_hidden", False) and not collapsed:
            self._hide_desktop_chat_chrome()
            return
        self._input_bar_collapsed = collapsed
        if collapsed:
            if getattr(self, "input_box", None) is not None:
                self.input_box.clearFocus()
            if getattr(self, "input_row", None) is not None:
                self.input_row.hide()
            self._bottom_chrome_h = 0
            self.setNotification(tr("desktop.menu.notify_input_bar_collapsed"))
        else:
            if getattr(self, "input_row", None) is not None:
                self.input_row.show()
            self.setNotification(tr("desktop.input_placeholder"))
        self._layout_input_row()
        self._update_sprite_reserved_bottom()
        self._relayout_overlays()
        self._raise_input_and_toolbar()
        if persist:
            self._persist_input_bar_collapsed()

    def show_input_context_menu(self, global_pos: QPoint) -> None:
        menu = QMenu(self)
        if self.is_input_bar_collapsed():
            action = QAction(tr("desktop.menu.show_input_bar"), self)
            action.triggered.connect(lambda: self.set_input_bar_collapsed(False))
        else:
            action = QAction(tr("desktop.menu.collapse_input_bar"), self)
            action.triggered.connect(lambda: self.set_input_bar_collapsed(True))
        menu.addAction(action)
        menu.setStyleSheet(styles.menu_popup())
        menu.exec(global_pos)

    def _show_input_box_context_menu(self, pos: QPoint) -> None:
        global_pos = self.input_box.mapToGlobal(pos)
        self.show_input_context_menu(global_pos)
    
    def option_clicked(self, text):
        """选项按钮点击处理函数"""
        print(f"Option clicked: {text}")
        # Check for pending tool confirmation first
        from core.runtime.app_runtime import try_get_app_runtime
        rt = try_get_app_runtime()
        if rt is not None and hasattr(rt, '_pending_confirm') and rt._pending_confirm:
            confirmed = "取消" not in text and "cancel" not in text.lower()
            for tool_name, (event, result_list) in list(rt._pending_confirm.items()):
                result_list.append(confirmed)
                event.set()
            self.setOptions([])
            return
        self.option_selected.emit(text)
        self.input_box.setText(text) # 将内容添加到输入框
        self.setOptions([])          # 隐藏选项
        self.sendMessage()           # 自动发送消息

    def _low_opacity_theme_accent(self) -> str:
        """与 setOptions 中 hover 晕光一致：由当前主题色推导低透明度 rgba。"""
        try:
            content = self.theme_color.strip().replace("rgba(", "").replace(")", "")
            r, g, b, _a = map(int, content.split(","))
            return f"rgba({r}, {g}, {b}, 50)"
        except Exception:
            return "rgba(50, 50, 50, 25)"

    def _refresh_option_choice_styles(self) -> None:
        """字体/DPI/主题色变化时，保留选项列表内容仅重刷 QSS（与 setOptions 同一套主题样式）。"""
        layout = getattr(self, "options_layout", None)
        if layout is None or layout.count() == 0:
            return
        ch = get_chat_chrome_theme(
            config_manager.config.system_config.chat_ui_theme_path
        )
        low = self._low_opacity_theme_accent()
        qss = styles.option_choice_button(
            self.font_size,
            self.theme_color,
            self.second_color,
            low,
            chrome_extra=ch.option_row_extra,
            chrome_hover_extra=ch.option_row_hover_extra,
        )
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.setStyleSheet(qss)

    def setOptions(self, optionList: list[str]):
        """
        在dialog label相同的地方显示一组半透明选项按钮，并隐藏dialog label。
        
        点击选项按钮会将内容添加到输入框并发送。
        """
        self.current_options = optionList
        print(f"Setting options: {optionList}")
        # 1. 互斥：隐藏对话框标签
        self.dialog_label.hide()
        if hasattr(self, 'name_label'):
            self.name_label.hide()

        # 2. 清除现有按钮
        while self.options_layout.count():
            item = self.options_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not optionList:
            # 3. 如果列表为空，隐藏选项容器并返回
            self.options_widget.hide()
            self._update_sprite_reserved_bottom()
            return

        low_opacity_theme = self._low_opacity_theme_accent()
        ch_opt = get_chat_chrome_theme(
            config_manager.config.system_config.chat_ui_theme_path
        )

        # 4. 添加新按钮
        for option_text in optionList:
            option_btn = ClickableLabel()
            option_btn.setText(option_text)
            option_btn.setTextFormat(Qt.TextFormat.RichText)
            option_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            option_btn.setWordWrap(True)
            
            # 设置半透明样式，使用主题色和字体大小
            option_btn.setStyleSheet(
                styles.option_choice_button(
                    self.font_size,
                    self.theme_color,
                    self.second_color,
                    low_opacity_theme,
                    chrome_extra=ch_opt.option_row_extra,
                    chrome_hover_extra=ch_opt.option_row_hover_extra,
                )
            )
            
            # 连接点击事件，使用 lambda 传递选项内容
            option_btn.clicked.connect(lambda text=option_text: self.option_clicked(text))
            self.options_layout.addWidget(option_btn)

        container_width = self.image_container.width() or self.original_width
        ch = get_chat_chrome_theme(
            config_manager.config.system_config.chat_ui_theme_path
        )
        margin_width, base_width = self._overlay_margin_and_content_width(container_width)
        w_pct = max(30, min(100, ch.dialog_width_pct)) / 100.0
        new_width = int(base_width * w_pct)
        margin_width = (container_width - new_width) // 2

        # 5a. 临时设置宽度来获取正确的 sizeHint (高度)
        self.options_widget.setFixedWidth(new_width)
        self.options_layout.setContentsMargins(ch.dialog_padding, ch.dialog_padding, ch.dialog_padding, ch.dialog_padding)
        self.options_layout.setSpacing(ch.options_gap)
        self.options_layout.activate()
        self.options_widget.adjustSize()
        
        # 5b. 获取适应新宽度后的高度
        final_height = self.options_widget.sizeHint().height()
        # 某些时机（如启动初期/回溯后）sizeHint 可能尚未稳定。
        # 使用当前字体度量估算每个选项文本所需高度，避免只显示一条缝或内容被截断。
        font = QFont('Microsoft YaHei')
        # self.font_size 形如 "32px;"，提取数字并设置给测量字体
        font_px = self.base_font_size_px
        try:
            font_px = int(self.font_size.replace("px", "").replace(";", "").strip())
        except Exception:
            pass
        font.setPixelSize(max(12, font_px))

        metrics = QFontMetrics(font)
        # 选项按钮可用文本宽度（扣掉左右边距和按钮 padding）
        text_width = max(120, new_width - 30 - 18)
        estimated_height = 15 + 15 + 10  # 容器上下边距 + 首个间距基线
        for option_text in optionList:
            rect = metrics.boundingRect(
                0, 0, text_width, 10000, int(Qt.TextFlag.TextWordWrap), option_text
            )
            # 按钮文本高度 + 按钮内边距 + 最小按钮高度 + 按钮间距
            option_height = max(40, rect.height() + 18)
            estimated_height += option_height + 10

        min_visible_height = max(80, estimated_height)
        final_height = max(final_height, min_visible_height)
        
        # 6. 贴在底栏上方，跟随 dialog_offset_y
        y = self._above_chrome_y(final_height, gap=4)
        avail_h = max(1, (self.image_container.height() or self.height()) - self._bottom_chrome_h)
        y = max(0, min(y + ch.dialog_offset_y, avail_h - final_height))
        
        # 7. 设置居中的位置和最终的尺寸
        self.options_widget.setGeometry(margin_width, y, new_width, final_height)
        # 7. 显示选项
        self.options_widget.show()
        # 确保在图像和其他元素上方显示 (工具栏和对话框标签除外)
        self.options_widget.raise_()
        self._update_sprite_reserved_bottom()
        self._fit_window_to_sprite()
        self._raise_input_and_toolbar()

    def mount_chat_ui_extensions(self, contributions: list) -> None:
        """
        Embed runtime extension widgets into the Chat UI. ``placement`` hints:
        ``toolbar`` (left of existing actions), ``input_row`` (left of input),
        anything else: child of ``image_container`` (overlay).
        """
        if not contributions:
            return
        from app.desktop.ui_context import try_get_chat_ui_context

        build_arg = try_get_chat_ui_context()
        if build_arg is None:
            build_arg = self
        for c in sorted(contributions, key=lambda x: x.order):
            try:
                w = c.build(build_arg)
            except Exception:
                _logger.exception("Chat UI extension widget failed: %s", c.widget_id)
                continue
            pl = (c.placement or "overlay").lower()
            if pl == "toolbar":
                tb = getattr(self, "toolbar", None)
                if tb is not None:
                    lay = tb.layout()
                    if lay is not None:
                        lay.insertWidget(0, w)
                        nw = max(200, lay.sizeHint().width() + 24)
                        cap = max(320, int(self.image_container.width() * 0.55))
                        tb.setFixedWidth(min(nw, cap))
                        x = max(0, self.image_container.width() - tb.width())
                        tb.move(x, 10)
            elif pl == "input_row":
                row = getattr(self, "input_row", None)
                if row is not None:
                    il = row.layout()
                    if il is not None:
                        il.insertWidget(0, w)
            else:
                w.setParent(self.image_container)
                w.show()
            w.installEventFilter(self)
            w.setMouseTracking(True)
            w.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
            self._raise_input_and_toolbar()

    def mousePressEvent(self, event):
        """窗口左下/右下小块缩放手柄；其余窗边在非 Windows 上手拖；其它区域拖动弹窗。"""
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            corner = self._bottom_corner_resize_edges_at(pos)
            if corner != Qt.Edge(0):
                self._begin_resize(corner, event.globalPosition().toPoint())
                event.accept()
                return
            edge = self._edges_at(pos)
            if edge:
                self._begin_resize(edge, event.globalPosition().toPoint())
                event.accept()
                return
            g = event.globalPosition().toPoint()
            self.drag_position = g - self.frameGeometry().topLeft()
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            self.show_settings_menu(event.globalPosition().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dialog_resizing:
            self._apply_dialog_resize_step(event.globalPosition().toPoint())
            event.accept()
            return
        if self._resizing:
            self._apply_resize_step(event.globalPosition().toPoint())
            event.accept()
            return
        if (
            event.buttons() == Qt.MouseButton.LeftButton
            and self.drag_position is not None
        ):
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()
            return
        if event.buttons() == Qt.MouseButton.NoButton:
            self._update_resize_hover_cursor_at_global(event.globalPosition().toPoint())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._dialog_resizing:
            self._end_dialog_resize()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._resizing:
            self._end_resize()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = None
        super().mouseReleaseEvent(event)

    def closeEvent(self, event):
        """关闭窗口时停止线程"""
        if self._resizing:
            self._end_resize()
        if self._dialog_resizing:
            self._end_dialog_resize()
        self._persist_chat_window_geometry()
        self.mic_button.close()
        if self.display_thread:
            self.display_thread.stop()
            self.display_thread.wait()
        super().closeEvent(event)
        self.close_window.emit()
        from ui.desktop.signal_bridge import detach_chat_ui_window

        detach_chat_ui_window()

    def eventFilter(self, obj, event):
        et = event.type()
        if et == QEvent.Type.HoverMove and isinstance(event, QHoverEvent):
            if not self._resizing:
                self._update_resize_hover_cursor_at_global(event.globalPosition().toPoint())
        elif self._is_dialog_label_event_target(obj) and et in (QEvent.Type.Leave, QEvent.Type.HoverLeave):
            if not self._dialog_resizing:
                self._clear_hover_resize_cursor()
        elif obj is self and et in (QEvent.Type.Leave, QEvent.Type.HoverLeave):
            self._clear_hover_resize_cursor()
        if obj == self.input_box:
            et_in = event.type()
            if et_in == QEvent.Type.FocusIn:
                self.user_input_started.emit()
            elif et_in == QEvent.Type.FocusOut:
                self.user_input_ended.emit()
            elif et_in == QEvent.Type.KeyPress:
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    # 同样判断是否带有修饰键
                    if not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                        self.send_btn.click()  # 你的发送函数
                        return True  # 表示事件已处理，不再向下传递（即不换行）
        if isinstance(event, QMouseEvent):
            met = event.type()
            is_dialog_target = self._is_dialog_label_event_target(obj)
            is_input_target = self._is_input_bar_event_target(obj)
            if met == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.RightButton:
                if is_dialog_target:
                    self.show_dialog_context_menu(event.globalPosition().toPoint())
                elif obj is getattr(self, "mic_button", None):
                    self.show_asr_settings()
                elif is_input_target:
                    self.show_input_context_menu(event.globalPosition().toPoint())
                else:
                    self.show_settings_menu(event.globalPosition().toPoint())
                return True
            if met == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                if is_dialog_target and not self._dialog_resizing:
                    de = self._dialog_edges_at(
                        self._dialog_pos_from_event_target(obj, event.position().toPoint())
                    )
                    if de != Qt.Edge(0):
                        self._begin_dialog_resize(de, event.globalPosition().toPoint())
                        return True
                ge = self._resize_edges_from_corner_hit_widget(obj)
                if ge != Qt.Edge(0) and not self._resizing:
                    self._begin_resize(ge, event.globalPosition().toPoint())
                    return True
                lp = self.mapFromGlobal(event.globalPosition().toPoint())
                ce = self._bottom_corner_resize_edges_at(lp)
                if ce != Qt.Edge(0) and not self._resizing:
                    self._begin_resize(ce, event.globalPosition().toPoint())
                    return True
                edges = self._edges_at(lp)
                if edges and not self._resizing:
                    self._begin_resize(edges, event.globalPosition().toPoint())
                    return True
            if (
                met == QEvent.Type.MouseMove
                and is_dialog_target
                and self._dialog_resizing
            ):
                self._apply_dialog_resize_step(event.globalPosition().toPoint())
                return True
            if (
                met == QEvent.Type.MouseButtonRelease
                and is_dialog_target
                and self._dialog_resizing
            ):
                self._end_dialog_resize()
                return True
            if (
                met == QEvent.Type.MouseMove
                and is_dialog_target
                and event.buttons() == Qt.MouseButton.NoButton
                and not self._resizing
                and not self._dialog_resizing
            ):
                self._update_resize_cursor(
                    self._dialog_edges_at(
                        self._dialog_pos_from_event_target(obj, event.position().toPoint())
                    )
                )
                return False
            if (
                met == QEvent.Type.Leave
                and is_dialog_target
                and not self._dialog_resizing
            ):
                self._clear_hover_resize_cursor()
                return False
            if (
                met == QEvent.Type.MouseMove
                and event.buttons() == Qt.MouseButton.NoButton
                and not self._resizing
            ):
                self._update_resize_hover_cursor_at_global(
                    event.globalPosition().toPoint()
                )
        return super().eventFilter(obj, event)
