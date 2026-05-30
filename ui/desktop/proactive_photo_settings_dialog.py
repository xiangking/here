"""Settings dialog for proactive-contact photo attachments."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from services.config.config_manager import ConfigManager
from services.i18n import tr
from services.t2i.t2i_manager import T2IAdapterFactory
from ui.desktop.asr_settings_dialog import (
    _build_schema_widgets,
    _read_schema_values,
)
from ui.desktop.combo_style import style_combo_popup
from ui.desktop.edit_context_menu import install_readable_edit_menus

T2I_PROVIDER_LABELS = {
    "image-api": "desktop.settings_dialog.t2i_provider_image_api",
    "xai-grok-imagine": "desktop.settings_dialog.t2i_provider_xai_grok_imagine",
    "openai-gpt-image": "desktop.settings_dialog.t2i_provider_openai_gpt_image",
}


def _t2i_provider_label(provider: str) -> str:
    label = T2I_PROVIDER_LABELS.get(provider, provider)
    if label.startswith("desktop."):
        return tr(label)
    return label


class ProactivePhotoSettingsDialog(QDialog):
    def __init__(
        self,
        parent=None,
        *,
        config_manager: ConfigManager | None = None,
        apply_callback: Callable[[], tuple[bool, str]] | None = None,
        notify_callback: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._config_manager = config_manager or ConfigManager()
        self._apply_callback = apply_callback
        self._notify_callback = notify_callback
        self._extra_editors: dict[str, QWidget] = {}
        self._extra_schema: dict[str, dict] = {}
        self.setWindowTitle(tr("desktop.settings_dialog.proactive_photo_title"))
        self.setModal(True)
        self.resize(580, 640)
        self._build_ui()
        self._load_from_config()
        self._on_provider_changed()

    def _build_ui(self) -> None:
        self.setStyleSheet(
            """
            QDialog {
                background-color: rgba(24, 26, 32, 238);
                color: white;
            }
            QScrollArea,
            QScrollArea QWidget#qt_scrollarea_viewport,
            QWidget#ProactivePhotoSettingsBody,
            QWidget#ProactivePhotoSettingsInlineRow,
            QWidget#ASRSettingsSchemaPanel {
                background-color: rgba(24, 26, 32, 238);
                border: none;
            }
            QLabel {
                color: rgba(255, 255, 255, 220);
                font-size: 13px;
            }
            QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {
                color: white;
                background-color: rgba(44, 47, 57, 235);
                border: 1px solid rgba(255, 255, 255, 72);
                border-radius: 6px;
                padding: 6px;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QComboBox QAbstractItemView {
                color: rgba(255, 255, 255, 230);
                background: rgb(24, 26, 32);
                selection-background-color: rgba(76, 175, 80, 190);
                selection-color: rgb(255, 255, 255);
                border: 1px solid rgba(255, 255, 255, 58);
                border-radius: 6px;
                outline: 0;
                padding: 4px 0;
            }
            QComboBox QAbstractItemView::item {
                min-height: 28px;
                padding: 5px 10px;
                border: none;
                background: transparent;
            }
            QComboBox QAbstractItemView::item:selected {
                background: rgba(76, 175, 80, 190);
                color: rgb(255, 255, 255);
            }
            QComboBox QAbstractItemView::item:hover {
                background: rgba(255, 255, 255, 28);
            }
            QCheckBox {
                color: rgba(255, 255, 255, 220);
                background-color: transparent;
                spacing: 8px;
            }
            QPushButton {
                background-color: rgba(76, 175, 80, 205);
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 14px;
            }
            QPushButton:hover {
                background-color: rgba(76, 175, 80, 245);
            }
            """
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        title = QLabel(tr("desktop.settings_dialog.proactive_photo_heading"), self)
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        root.addWidget(title)

        hint = QLabel(tr("desktop.settings_dialog.proactive_photo_hint"), self)
        hint.setWordWrap(True)
        hint.setStyleSheet("color: rgba(255,255,255,170);")
        root.addWidget(hint)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        scroll.viewport().setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        scroll.viewport().setStyleSheet("background-color: rgba(24, 26, 32, 238);")

        body = QWidget(scroll)
        body.setObjectName("ProactivePhotoSettingsBody")
        body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        form = QFormLayout(body)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.enabled_check = QCheckBox(body)
        form.addRow(tr("desktop.settings_dialog.enabled"), self.enabled_check)

        self.provider_combo = QComboBox(body)
        style_combo_popup(self.provider_combo)
        for provider in T2IAdapterFactory._adapters:
            self.provider_combo.addItem(_t2i_provider_label(provider), provider)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        form.addRow(tr("desktop.settings_dialog.image_provider"), self.provider_combo)

        self.daily_limit = QSpinBox(body)
        self.daily_limit.setRange(0, 12)
        form.addRow(tr("desktop.settings_dialog.daily_photo_limit"), self.daily_limit)

        self.width_spin = QSpinBox(body)
        self.width_spin.setRange(256, 4096)
        self.width_spin.setSingleStep(64)
        form.addRow(tr("desktop.settings_dialog.image_width"), self.width_spin)

        self.height_spin = QSpinBox(body)
        self.height_spin.setRange(256, 4096)
        self.height_spin.setSingleStep(64)
        form.addRow(tr("desktop.settings_dialog.image_height"), self.height_spin)

        self.extra_holder = QWidget(body)
        self.extra_holder.setObjectName("ProactivePhotoSettingsInlineRow")
        self.extra_holder.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.extra_layout = QVBoxLayout(self.extra_holder)
        self.extra_layout.setContentsMargins(0, 0, 0, 0)
        self.extra_layout.setSpacing(8)
        form.addRow(tr("desktop.settings_dialog.image_api_params"), self.extra_holder)

        self.status_label = QLabel("", body)
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: rgba(255,255,255,175);")
        form.addRow(tr("desktop.settings_dialog.status"), self.status_label)

        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        cancel_btn = QPushButton(tr("desktop.menu.cancel"), self)
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton(tr("desktop.settings_dialog.save_photo_settings"), self)
        save_btn.clicked.connect(self._save_and_accept)
        buttons.addStretch(1)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(save_btn)
        root.addLayout(buttons)
        install_readable_edit_menus(self)

    def _load_from_config(self) -> None:
        api_cfg = self._config_manager.config.api_config
        sys_cfg = self._config_manager.config.system_config
        self.enabled_check.setChecked(bool(getattr(sys_cfg, "proactive_photo_enabled", False)))
        provider = str(
            getattr(api_cfg, "selfie_provider", "")
            or getattr(api_cfg, "t2i_provider", "")
            or "image-api"
        ).strip()
        self._set_combo_data(self.provider_combo, provider)
        self.daily_limit.setValue(int(getattr(sys_cfg, "proactive_photo_daily_limit", 1) or 1))
        selfie_extra = dict(getattr(api_cfg, "selfie_extra_configs", {}) or {})
        self.width_spin.setValue(int(selfie_extra.get("width") or 1024))
        self.height_spin.setValue(int(selfie_extra.get("height") or 1024))

    def _set_combo_data(self, combo: QComboBox, value: str) -> None:
        for i in range(combo.count()):
            if str(combo.itemData(i) or "") == value:
                combo.setCurrentIndex(i)
                return

    def _current_provider(self) -> str:
        return str(self.provider_combo.currentData() or "image-api").strip().lower()

    def _clear_extra_layout(self) -> None:
        while self.extra_layout.count():
            item = self.extra_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _on_provider_changed(self) -> None:
        provider = self._current_provider()
        self._clear_extra_layout()
        self._extra_editors = {}
        cls = T2IAdapterFactory._adapters.get(provider)
        self._extra_schema = cls.get_config_schema() if cls else {}
        if not self._extra_schema:
            self.extra_holder.setVisible(False)
        else:
            values = self._config_manager.get_adapter_extra_config("t2i", provider)
            panel, editors = _build_schema_widgets(
                self._extra_schema,
                values,
                self.extra_holder,
            )
            self.extra_layout.addWidget(panel)
            self._extra_editors = editors
            self.extra_holder.setVisible(True)
        self.status_label.setText(
            tr(
                "desktop.settings_dialog.proactive_photo_status",
                label=_t2i_provider_label(provider),
            )
        )

    def _save_and_accept(self) -> None:
        provider = self._current_provider()
        sys_cfg = self._config_manager.config.system_config.model_copy(deep=True)
        sys_cfg.proactive_photo_enabled = bool(self.enabled_check.isChecked())
        sys_cfg.proactive_photo_daily_limit = int(self.daily_limit.value())
        self._config_manager.config.system_config = sys_cfg

        api_cfg = self._config_manager.config.api_config.model_copy(deep=True)
        api_cfg.selfie_provider = provider
        selfie_extra = dict(getattr(api_cfg, "selfie_extra_configs", {}) or {})
        selfie_extra["width"] = int(self.width_spin.value())
        selfie_extra["height"] = int(self.height_spin.value())
        api_cfg.selfie_extra_configs = selfie_extra
        self._config_manager.config.api_config = api_cfg
        self._config_manager.set_adapter_extra_config(
            "t2i",
            provider,
            _read_schema_values(self._extra_schema, self._extra_editors),
        )
        self._config_manager.save_system_config()
        self._config_manager.save_api_config()

        ok, message = True, ""
        if callable(self._apply_callback):
            ok, message = self._apply_callback()
        if callable(self._notify_callback):
            label = _t2i_provider_label(provider)
            if ok:
                self._notify_callback(tr("desktop.settings_dialog.proactive_photo_saved", label=label))
            else:
                self._notify_callback(
                    tr(
                        "desktop.settings_dialog.proactive_photo_saved_apply_failed",
                        label=label,
                        message=message,
                    )
                )
        self.accept()
