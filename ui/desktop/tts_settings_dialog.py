"""Desktop TTS settings dialog used by the pet window."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from services.config.config_manager import ConfigManager
from services.i18n import tr
from services.tts.tts_manager import TTSAdapterFactory
from ui.desktop.asr_settings_dialog import (
    _build_schema_widgets,
    _make_status_label,
    _read_schema_values,
    _set_status_label_text,
)
from ui.desktop.combo_style import style_combo_popup
from ui.desktop.edit_context_menu import install_readable_edit_menus

TTS_PROVIDER_LABELS = {
    "none": "desktop.settings_dialog.tts_provider_none",
    "edge-tts": "desktop.settings_dialog.tts_provider_edge",
    "openai-tts": "desktop.settings_dialog.tts_provider_openai",
    "elevenlabs": "desktop.settings_dialog.tts_provider_elevenlabs",
    "minimax-tts": "desktop.settings_dialog.tts_provider_minimax",
    "fish-audio": "desktop.settings_dialog.tts_provider_fish",
}


def _tts_provider_label(provider: str) -> str:
    label = TTS_PROVIDER_LABELS.get(provider, provider)
    if label.startswith("desktop."):
        return tr(label)
    return label


class TTSSettingsDialog(QDialog):
    def __init__(
        self,
        parent=None,
        *,
        config_manager: ConfigManager | None = None,
        apply_callback: Callable[[str], tuple[bool, str]] | None = None,
        notify_callback: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._config_manager = config_manager or ConfigManager()
        self._apply_callback = apply_callback
        self._notify_callback = notify_callback
        self._extra_editors: dict[str, QWidget] = {}
        self._extra_schema: dict[str, dict] = {}
        self.setWindowTitle(tr("desktop.settings_dialog.tts_title"))
        self.setModal(True)
        self.resize(580, 660)
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
            QWidget#TTSSettingsBody,
            QWidget#TTSSettingsInlineRow,
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
            QCheckBox {
                color: rgba(255, 255, 255, 220);
                background-color: transparent;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
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
            QPushButton:disabled {
                background-color: rgba(90, 92, 98, 180);
                color: rgba(255, 255, 255, 120);
            }
            """
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        title = QLabel(tr("desktop.settings_dialog.tts_heading"), self)
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        root.addWidget(title)

        hint = QLabel(
            tr("desktop.settings_dialog.tts_hint"),
            self,
        )
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
        body.setObjectName("TTSSettingsBody")
        body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        form = QFormLayout(body)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(10)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.provider_combo = QComboBox(body)
        style_combo_popup(self.provider_combo)
        self.provider_combo.addItem(_tts_provider_label("none"), "none")
        for provider in TTSAdapterFactory._adapters:
            self.provider_combo.addItem(_tts_provider_label(provider), provider)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        form.addRow(tr("desktop.settings_dialog.backend"), self.provider_combo)

        self.speed_spin = QDoubleSpinBox(body)
        self.speed_spin.setRange(0.5, 3.0)
        self.speed_spin.setSingleStep(0.1)
        self.speed_spin.setDecimals(1)
        self.speed_spin.setSuffix("x")
        form.addRow(tr("desktop.settings_dialog.global_speed"), self.speed_spin)

        self.split_enabled = QCheckBox(body)
        form.addRow(tr("desktop.settings_dialog.split_enabled"), self.split_enabled)

        self.max_sentence_length = QSpinBox(body)
        self.max_sentence_length.setRange(5, 100)
        self.max_sentence_length.setSingleStep(1)
        form.addRow(tr("desktop.settings_dialog.max_sentence_length"), self.max_sentence_length)

        self.extra_holder = QWidget(body)
        self.extra_holder.setObjectName("TTSSettingsInlineRow")
        self.extra_holder.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.extra_layout = QVBoxLayout(self.extra_holder)
        self.extra_layout.setContentsMargins(0, 0, 0, 0)
        self.extra_layout.setSpacing(8)
        form.addRow(tr("desktop.settings_dialog.advanced"), self.extra_holder)

        self.status_label = _make_status_label(body)
        form.addRow(tr("desktop.settings_dialog.status"), self.status_label)

        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        cancel_btn = QPushButton(tr("desktop.settings_dialog.cancel"), self)
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton(tr("desktop.settings_dialog.save_reset_tts"), self)
        save_btn.clicked.connect(self._save_and_accept)
        buttons.addStretch(1)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(save_btn)
        root.addLayout(buttons)
        install_readable_edit_menus(self)

    def _load_from_config(self) -> None:
        api_cfg = self._config_manager.config.api_config
        self._set_combo_data(
            self.provider_combo,
            str(getattr(api_cfg, "tts_provider", "") or "none"),
        )
        self.speed_spin.setValue(float(getattr(api_cfg, "tts_speed", 1.0) or 1.0))
        self.split_enabled.setChecked(bool(getattr(api_cfg, "tts_split_enabled", False)))
        self.max_sentence_length.setValue(
            int(getattr(api_cfg, "tts_max_sentence_length", 15) or 15)
        )

    def _set_combo_data(self, combo: QComboBox, value: str) -> None:
        for i in range(combo.count()):
            if str(combo.itemData(i) or "") == value:
                combo.setCurrentIndex(i)
                return

    def _current_provider(self) -> str:
        return str(self.provider_combo.currentData() or "none").strip().lower()

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
        cls = TTSAdapterFactory._adapters.get(provider)
        self._extra_schema = cls.get_config_schema() if cls else {}
        if not self._extra_schema:
            self.extra_holder.setVisible(False)
        else:
            values = self._config_manager.get_adapter_extra_config("tts", provider)
            panel, editors = _build_schema_widgets(
                self._extra_schema,
                values,
                self.extra_holder,
            )
            self.extra_layout.addWidget(panel)
            self._extra_editors = editors
            self.extra_holder.setVisible(True)
        _set_status_label_text(self.status_label, self._status_for_provider(provider))

    def _status_for_provider(self, provider: str) -> str:
        if provider == "none":
            return tr("desktop.settings_dialog.tts_status_none")
        label = _tts_provider_label(provider)
        return tr("desktop.settings_dialog.tts_status_provider", label=label)

    def _save_and_accept(self) -> None:
        provider = self._current_provider()
        api_cfg = self._config_manager.config.api_config.model_copy(deep=True)
        api_cfg.tts_provider = provider
        api_cfg.tts_speed = float(self.speed_spin.value())
        api_cfg.tts_split_enabled = bool(self.split_enabled.isChecked())
        api_cfg.tts_max_sentence_length = int(self.max_sentence_length.value())
        self._config_manager.config.api_config = api_cfg
        if provider != "none":
            self._config_manager.set_adapter_extra_config(
                "tts",
                provider,
                _read_schema_values(self._extra_schema, self._extra_editors),
            )
        self._config_manager.save_api_config()

        ok, message = True, ""
        if callable(self._apply_callback):
            ok, message = self._apply_callback(provider)
        if callable(self._notify_callback):
            label = _tts_provider_label(provider)
            if ok:
                self._notify_callback(tr("desktop.settings_dialog.tts_saved", label=label))
            else:
                self._notify_callback(
                    tr("desktop.settings_dialog.tts_saved_apply_failed", label=label, message=message)
                )
        self.accept()
