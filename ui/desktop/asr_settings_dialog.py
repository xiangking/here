"""Desktop ASR settings dialog used by the pet window."""

from __future__ import annotations

import threading
import importlib
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from services.asr.asr_adapter import (
    VOSK_SMALL_CN_MODEL_DIRNAME,
    default_vosk_model_path,
    is_vosk_model_dir,
    missing_asr_requirements,
    normalize_asr_provider_storage_key,
)
from services.asr.asr_manager import ASRAdapterFactory
from services.config.config_manager import ConfigManager
from services.i18n import tr
from infrastructure.paths import install_user_python_packages_path
from ui.desktop.combo_style import style_combo_popup
from ui.desktop.edit_context_menu import install_readable_edit_menus

SCHEMA_LABEL_TRANSLATION_KEYS = {
    "Vosk model path": "desktop.settings_dialog.schema_vosk_model_path",
    "Sample rate": "desktop.settings_dialog.schema_sample_rate",
    "Chunk size": "desktop.settings_dialog.schema_chunk_size",
    "VAD filter": "desktop.settings_dialog.schema_vad_filter",
    "Chunk seconds": "desktop.settings_dialog.schema_chunk_seconds",
    "Beam size": "desktop.settings_dialog.schema_beam_size",
    "Silence threshold": "desktop.settings_dialog.schema_silence_threshold",
    "Chunk frames": "desktop.settings_dialog.schema_chunk_frames",
    "Realtime partial text": "desktop.settings_dialog.schema_realtime_partial_text",
    "Realtime pause seconds": "desktop.settings_dialog.schema_realtime_pause_seconds",
    "Service URL": "desktop.settings_dialog.schema_service_url",
    "Work path": "desktop.settings_dialog.schema_work_path",
    "Voice": "desktop.settings_dialog.schema_voice",
    "Rate": "desktop.settings_dialog.schema_rate",
    "Volume": "desktop.settings_dialog.schema_volume",
    "Pitch": "desktop.settings_dialog.schema_pitch",
    "OpenAI API key": "desktop.settings_dialog.schema_openai_api_key",
    "fal/xAI API Key": "desktop.settings_dialog.schema_xai_api_key",
    "fal/xAI/OpenRouter API Key": "desktop.settings_dialog.schema_xai_openrouter_api_key",
    "ElevenLabs API key": "desktop.settings_dialog.schema_elevenlabs_api_key",
    "MiniMax API key": "desktop.settings_dialog.schema_minimax_api_key",
    "Fish Audio API key": "desktop.settings_dialog.schema_fish_api_key",
    "DashScope API key": "desktop.settings_dialog.schema_dashscope_api_key",
    "Model": "desktop.settings_dialog.schema_model",
    "Format": "desktop.settings_dialog.schema_format",
    "Base URL": "desktop.settings_dialog.schema_base_url",
    "Timeout seconds": "desktop.settings_dialog.schema_timeout_seconds",
    "Quality": "desktop.settings_dialog.schema_quality",
    "Background": "desktop.settings_dialog.schema_background",
    "Voice ID": "desktop.settings_dialog.schema_voice_id",
    "Output format": "desktop.settings_dialog.schema_output_format",
    "Output compression": "desktop.settings_dialog.schema_output_compression",
    "Moderation": "desktop.settings_dialog.schema_moderation",
    "Stream images": "desktop.settings_dialog.schema_stream_images",
    "Stream partial images": "desktop.settings_dialog.schema_stream_partial_images",
    "API style": "desktop.settings_dialog.schema_api_style",
    "Aspect ratio": "desktop.settings_dialog.schema_aspect_ratio",
    "Image size": "desktop.settings_dialog.schema_image_size",
    "Stability": "desktop.settings_dialog.schema_stability",
    "Similarity boost": "desktop.settings_dialog.schema_similarity_boost",
    "MiniMax Group ID": "desktop.settings_dialog.schema_minimax_group_id",
    "Bitrate": "desktop.settings_dialog.schema_bitrate",
    "Reference ID": "desktop.settings_dialog.schema_reference_id",
    "MP3 bitrate": "desktop.settings_dialog.schema_mp3_bitrate",
    "Latency": "desktop.settings_dialog.schema_latency",
}

ASR_PROVIDER_LABELS = {
    "vosk": "Vosk",
    "faster_whisper": "faster-whisper",
    "realtime_stt": "RealtimeSTT",
}

ASR_PROVIDER_INSTALL_PACKAGES = {
    "vosk": ("pyaudio", "vosk"),
    "faster_whisper": ("pyaudio", "faster-whisper"),
    "realtime_stt": ("RealtimeSTT",),
}

ASR_WHISPER_MODEL_PRESETS = (
    "tiny",
    "base",
    "small",
    "medium",
    "large-v3",
)

ASR_WHISPER_MODEL_SIZE_LABELS = {
    "tiny": "75 MB",
    "base": "150 MB",
    "small": "500 MB",
    "medium": "1.5 GB",
    "large-v3": "3.1 GB",
}

VOSK_SMALL_CN_URL = f"https://alphacephei.com/vosk/models/{VOSK_SMALL_CN_MODEL_DIRNAME}.zip"
WHISPER_CACHE_DIR = Path.home() / ".cache" / "whisper"


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _installed_whisper_models() -> list[str]:
    if not WHISPER_CACHE_DIR.is_dir():
        return []
    models: list[str] = []
    for path in sorted(WHISPER_CACHE_DIR.glob("*.pt")):
        if path.is_file():
            models.append(path.stem)
    return models


def _make_status_label(parent: QWidget | None = None) -> QLabel:
    label = QLabel("", parent)
    label.setWordWrap(True)
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    label.setContentsMargins(0, 2, 0, 2)
    label.setMinimumHeight(label.fontMetrics().lineSpacing() * 2 + 8)
    label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
    label.setStyleSheet("color: rgba(255,255,255,175);")
    return label


def _set_status_label_text(label: QLabel, text: str) -> None:
    label.setText(text)
    label.updateGeometry()
    parent = label.parentWidget()
    if parent is not None and parent.layout() is not None:
        parent.layout().invalidate()
        parent.updateGeometry()


def _build_schema_widgets(
    schema: dict[str, dict],
    values: dict[str, Any],
    parent: QWidget | None,
) -> tuple[QWidget, dict[str, QWidget]]:
    wrap = QWidget(parent)
    wrap.setObjectName("ASRSettingsSchemaPanel")
    wrap.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    form = QFormLayout(wrap)
    form.setContentsMargins(0, 0, 0, 0)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
    form.setSpacing(8)
    editors: dict[str, QWidget] = {}
    for key, meta in schema.items():
        raw_label = str(meta.get("label", key))
        label_key = str(meta.get("label_key") or SCHEMA_LABEL_TRANSLATION_KEYS.get(raw_label, ""))
        label_text = tr(label_key) if label_key else raw_label
        label = QLabel(label_text, wrap)
        label.setWordWrap(True)
        typ = str(meta.get("type", "str")).lower()
        default = meta.get("default", "")
        cur = values.get(key, default)
        choices = meta.get("choices")
        if isinstance(choices, (list, tuple)) and choices:
            widget = QComboBox(wrap)
            style_combo_popup(widget)
            widget.setEditable(bool(meta.get("editable", False)))
            for choice in choices:
                widget.addItem(str(choice), str(choice))
            idx = widget.findData(str(cur if cur is not None else default))
            if idx >= 0:
                widget.setCurrentIndex(idx)
            elif widget.isEditable():
                widget.setEditText(str(cur if cur is not None else default))
            else:
                widget.setCurrentIndex(0)
        elif typ == "bool":
            widget = QCheckBox(wrap)
            widget.setChecked(_truthy(cur))
        elif typ == "int":
            widget = QSpinBox(wrap)
            widget.setRange(int(meta.get("min", -2147483648)), int(meta.get("max", 2147483647)))
            widget.setSingleStep(int(meta.get("step", 1) or 1))
            try:
                widget.setValue(int(cur))
            except (TypeError, ValueError):
                widget.setValue(int(default) if default != "" else 0)
        elif typ == "float":
            widget = QDoubleSpinBox(wrap)
            step = float(meta.get("step", 0.01) or 0.01)
            widget.setDecimals(2)
            widget.setSingleStep(step)
            widget.setRange(float(meta.get("min", -1e9)), float(meta.get("max", 1e9)))
            try:
                widget.setValue(float(cur))
            except (TypeError, ValueError):
                widget.setValue(float(default) if default != "" else 0.0)
        else:
            widget = QLineEdit("" if cur is None else str(cur), wrap)
            if typ == "password":
                widget.setEchoMode(QLineEdit.EchoMode.Password)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        form.addRow(label, widget)
        editors[key] = widget
    install_readable_edit_menus(wrap)
    return wrap, editors


def _read_schema_values(schema: dict[str, dict], editors: dict[str, QWidget]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, meta in schema.items():
        widget = editors.get(key)
        if widget is None:
            continue
        typ = str(meta.get("type", "str")).lower()
        default = meta.get("default", "")
        if isinstance(widget, QCheckBox):
            out[key] = widget.isChecked()
        elif isinstance(widget, QSpinBox):
            out[key] = int(widget.value())
        elif isinstance(widget, QDoubleSpinBox):
            out[key] = float(widget.value())
        elif isinstance(widget, QComboBox):
            data = widget.currentData()
            out[key] = str(data if data is not None else widget.currentText())
        elif isinstance(widget, QLineEdit):
            raw = widget.text().strip()
            if typ == "int":
                try:
                    out[key] = int(raw) if raw else int(default)
                except (TypeError, ValueError):
                    out[key] = int(default) if default != "" else 0
            elif typ == "float":
                try:
                    out[key] = float(raw) if raw else float(default)
                except (TypeError, ValueError):
                    out[key] = float(default) if default != "" else 0.0
            else:
                out[key] = raw if raw else str(default)
    return out


class _AsrPreloadSignals(QObject):
    status = Signal(str)
    finished = Signal(bool, str)


class _AsrDependencyInstallSignals(QObject):
    status = Signal(str)
    finished = Signal(bool, str)


class ASRSettingsDialog(QDialog):
    def __init__(
        self,
        parent=None,
        *,
        config_manager: ConfigManager | None = None,
        reset_adapter_callback=None,
        notify_callback=None,
        auto_prepare: bool = False,
    ) -> None:
        super().__init__(parent)
        self._config_manager = config_manager or ConfigManager()
        self._reset_adapter_callback = reset_adapter_callback
        self._notify_callback = notify_callback
        self._auto_prepare = auto_prepare
        self._extra_editors: dict[str, QWidget] = {}
        self._extra_schema: dict[str, dict] = {}
        self._preload_running = False
        self._preload_signals = _AsrPreloadSignals(self)
        self._preload_signals.status.connect(self._set_status)
        self._preload_signals.finished.connect(self._on_preload_finished)
        self._install_running = False
        self._install_signals = _AsrDependencyInstallSignals(self)
        self._install_signals.status.connect(self._set_status)
        self._install_signals.finished.connect(self._on_dependency_install_finished)
        self.setWindowTitle(tr("desktop.settings_dialog.asr_title"))
        self.setModal(True)
        self.resize(560, 620)
        self._build_ui()
        self._load_from_config()
        self._on_provider_changed()
        if self._auto_prepare:
            QTimer.singleShot(0, self._auto_prepare_if_possible)

    def _build_ui(self) -> None:
        self.setStyleSheet(
            """
            QDialog {
                background-color: rgba(24, 26, 32, 238);
                color: white;
            }
            QScrollArea,
            QScrollArea QWidget#qt_scrollarea_viewport,
            QWidget#ASRSettingsBody,
            QWidget#ASRSettingsSchemaPanel,
            QWidget#ASRSettingsInlineRow {
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
                color: white;
                background-color: rgb(24, 26, 32);
                selection-background-color: rgba(76, 175, 80, 210);
                selection-color: white;
                border: 1px solid rgba(255, 255, 255, 35);
                outline: 0;
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

        title = QLabel(tr("desktop.settings_dialog.asr_heading"), self)
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        root.addWidget(title)

        hint = QLabel(
            tr("desktop.settings_dialog.asr_hint"),
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
        body.setObjectName("ASRSettingsBody")
        body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        form = QFormLayout(body)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(10)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.provider_combo = QComboBox(body)
        style_combo_popup(self.provider_combo)
        self.provider_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.provider_combo.addItem("Vosk", "vosk")
        for slug in sorted(k for k in ASRAdapterFactory._adapters if k != "vosk"):
            self.provider_combo.addItem(ASR_PROVIDER_LABELS.get(slug, slug), slug)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        form.addRow(tr("desktop.settings_dialog.backend"), self.provider_combo)

        self.language_combo = QComboBox(body)
        style_combo_popup(self.language_combo)
        self.language_combo.addItem(tr("desktop.settings_dialog.follow_ui"), "")
        self.language_combo.addItem(tr("desktop.settings_dialog.chinese"), "zh")
        self.language_combo.addItem(tr("desktop.settings_dialog.english"), "en")
        self.language_combo.addItem(tr("desktop.settings_dialog.japanese"), "ja")
        self.language_combo.addItem(tr("desktop.settings_dialog.cantonese_as_zh"), "yue")
        form.addRow(tr("desktop.settings_dialog.language"), self.language_combo)

        self.vosk_row = QWidget(body)
        self.vosk_row.setObjectName("ASRSettingsInlineRow")
        self.vosk_row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        vosk_layout = QHBoxLayout(self.vosk_row)
        vosk_layout.setContentsMargins(0, 0, 0, 0)
        vosk_layout.setSpacing(8)
        self.vosk_path_edit = QLineEdit(self.vosk_row)
        self.vosk_path_edit.setPlaceholderText(default_vosk_model_path())
        browse_btn = QPushButton(tr("desktop.settings_dialog.choose_directory"), self.vosk_row)
        browse_btn.clicked.connect(self._choose_vosk_model_dir)
        vosk_layout.addWidget(self.vosk_path_edit, 1)
        vosk_layout.addWidget(browse_btn)
        form.addRow(tr("desktop.settings_dialog.vosk_model_dir"), self.vosk_row)

        self.model_combo = QComboBox(body)
        style_combo_popup(self.model_combo)
        for mid in ASR_WHISPER_MODEL_PRESETS:
            size = ASR_WHISPER_MODEL_SIZE_LABELS.get(mid, "")
            label = f"{mid} ({tr('desktop.settings_dialog.size_about', size=size)})" if size else mid
            self.model_combo.addItem(label, mid)
        self.model_combo.addItem(tr("desktop.settings_dialog.custom_model"), "__custom__")
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        self.model_custom = QLineEdit(body)
        self.model_custom.setPlaceholderText(tr("desktop.settings_dialog.custom_model_placeholder"))
        self.model_custom.setVisible(False)
        self.model_row = QWidget(body)
        self.model_row.setObjectName("ASRSettingsInlineRow")
        self.model_row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        model_layout = QVBoxLayout(self.model_row)
        model_layout.setContentsMargins(0, 0, 0, 0)
        model_layout.setSpacing(5)
        model_layout.addWidget(self.model_combo)
        model_layout.addWidget(self.model_custom)
        form.addRow(tr("desktop.settings_dialog.whisper_model"), self.model_row)

        self.device_combo = QComboBox(body)
        style_combo_popup(self.device_combo)
        self.device_combo.addItem(tr("desktop.settings_dialog.auto"), "auto")
        self.device_combo.addItem("CPU", "cpu")
        self.device_combo.addItem("CUDA", "cuda")
        form.addRow(tr("desktop.settings_dialog.device"), self.device_combo)

        self.compute_combo = QComboBox(body)
        style_combo_popup(self.compute_combo)
        for label, value in (
            (tr("desktop.settings_dialog.auto"), ""),
            ("int8", "int8"),
            ("float16", "float16"),
            ("int8_float16", "int8_float16"),
            ("int16", "int16"),
            ("float32", "float32"),
        ):
            self.compute_combo.addItem(label, value)
        form.addRow(tr("desktop.settings_dialog.compute_type"), self.compute_combo)

        self.extra_holder = QWidget(body)
        self.extra_holder.setObjectName("ASRSettingsInlineRow")
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
        self.install_deps_btn = QPushButton(tr("desktop.settings_dialog.install_asr_deps"), self)
        self.install_deps_btn.clicked.connect(self._install_current_dependencies)
        self.preload_btn = QPushButton(tr("desktop.settings_dialog.preload_model"), self)
        self.preload_btn.clicked.connect(self._preload_current_model)
        cancel_btn = QPushButton(tr("desktop.settings_dialog.cancel"), self)
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton(tr("desktop.settings_dialog.save_reset_mic"), self)
        save_btn.clicked.connect(self._save_and_accept)
        buttons.addWidget(self.install_deps_btn)
        buttons.addWidget(self.preload_btn)
        buttons.addStretch(1)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(save_btn)
        root.addLayout(buttons)
        install_readable_edit_menus(self)

    def _load_from_config(self) -> None:
        sys_cfg = self._config_manager.config.system_config
        provider = normalize_asr_provider_storage_key(
            str(getattr(sys_cfg, "asr_provider", "") or "vosk")
        )
        self._set_combo_data(self.provider_combo, provider)
        self._set_combo_data(
            self.language_combo,
            str(getattr(sys_cfg, "asr_language", "") or ""),
        )
        raw_model = str(getattr(sys_cfg, "asr_whisper_model_size", "") or "small")
        if raw_model in ASR_WHISPER_MODEL_PRESETS:
            self._set_combo_data(self.model_combo, raw_model)
        else:
            self._set_combo_data(self.model_combo, "__custom__")
            self.model_custom.setText(raw_model)
            self.model_custom.setVisible(True)
        self._set_combo_data(
            self.device_combo,
            str(getattr(sys_cfg, "asr_whisper_device", "") or "auto"),
        )
        self._set_combo_data(
            self.compute_combo,
            str(getattr(sys_cfg, "asr_whisper_compute_type", "") or ""),
        )

    def _set_combo_data(self, combo: QComboBox, value: str) -> None:
        for i in range(combo.count()):
            if str(combo.itemData(i) or "") == str(value):
                combo.setCurrentIndex(i)
                return

    def _current_provider(self) -> str:
        return normalize_asr_provider_storage_key(
            str(self.provider_combo.currentData() or "vosk")
        )

    def _missing_requirements(self, provider: str) -> list[str]:
        return missing_asr_requirements(provider)

    def _install_command_label(self, provider: str) -> str:
        return self._pip_install_command(provider)

    def _pip_install_command(self, provider: str) -> str:
        packages = ASR_PROVIDER_INSTALL_PACKAGES.get(provider, ())
        if not packages:
            packages = ("pyaudio", "vosk")
        return f"{Path(sys.executable).name} -m pip install " + " ".join(packages)

    def _current_model(self) -> str:
        data = self.model_combo.currentData()
        if data is not None and str(data) == "__custom__":
            return self.model_custom.text().strip() or "small"
        return str(data or "small")

    def _on_model_changed(self) -> None:
        self.model_custom.setVisible(str(self.model_combo.currentData() or "") == "__custom__")

    def _on_provider_changed(self) -> None:
        provider = self._current_provider()
        is_vosk = provider == "vosk"
        missing = self._missing_requirements(provider)
        self.vosk_row.setVisible(is_vosk)
        self.model_row.setVisible(not is_vosk)
        self.device_combo.setVisible(not is_vosk)
        self.compute_combo.setVisible(not is_vosk)
        self.install_deps_btn.setVisible(bool(missing))
        self.preload_btn.setEnabled(not bool(missing))
        self._rebuild_extra_panel(provider)
        self._set_status(self._status_for_provider(provider))

    def _status_for_provider(self, provider: str) -> str:
        missing = self._missing_requirements(provider)
        if missing:
            return tr(
                "desktop.settings_dialog.asr_deps_missing",
                modules=", ".join(missing),
                command=self._install_command_label(provider),
            )
        if provider == "vosk":
            path = self._vosk_model_path()
            ok = self._is_vosk_model_dir(path)
            if ok:
                return tr("desktop.settings_dialog.vosk_status_ok", path=path)
            whisper_models = _installed_whisper_models()
            suffix = ""
            if whisper_models:
                suffix = tr(
                    "desktop.settings_dialog.whisper_cache_suffix",
                    models=", ".join(whisper_models),
                )
            return tr("desktop.settings_dialog.vosk_status_missing", path=path, suffix=suffix)
        model = self._current_model()
        size = ASR_WHISPER_MODEL_SIZE_LABELS.get(model, tr("desktop.settings_dialog.custom_size"))
        cached = model in _installed_whisper_models()
        cache_text = (
            tr("desktop.settings_dialog.cache_found")
            if cached
            else tr("desktop.settings_dialog.cache_first")
        )
        return tr(
            "desktop.settings_dialog.asr_status_model",
            provider=ASR_PROVIDER_LABELS.get(provider, provider),
            model=model,
            size=size,
            cache_text=cache_text,
        )

    def _clear_extra_layout(self) -> None:
        while self.extra_layout.count():
            item = self.extra_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _rebuild_extra_panel(self, provider: str) -> None:
        self._clear_extra_layout()
        self._extra_editors = {}
        cls = ASRAdapterFactory._adapters.get(provider)
        self._extra_schema = cls.get_config_schema() if cls else {}
        values = self._config_manager.get_adapter_extra_config("asr", provider)
        if provider == "vosk":
            values = {**values, "model_path": self._vosk_model_path()}
        if not self._extra_schema:
            self.extra_holder.setVisible(False)
            return
        panel, editors = _build_schema_widgets(self._extra_schema, values, self.extra_holder)
        self.extra_layout.addWidget(panel)
        self._extra_editors = editors
        self.extra_holder.setVisible(True)
        if provider == "vosk":
            editor = editors.get("model_path")
            if isinstance(editor, QLineEdit):
                editor.textChanged.connect(self.vosk_path_edit.setText)
                if not self.vosk_path_edit.text().strip():
                    self.vosk_path_edit.setText(editor.text().strip() or default_vosk_model_path())

    def _choose_vosk_model_dir(self) -> None:
        start = self.vosk_path_edit.text().strip() or default_vosk_model_path()
        path = QFileDialog.getExistingDirectory(
            self,
            tr("desktop.settings_dialog.choose_vosk_dir_title"),
            start,
        )
        if not path:
            return
        self.vosk_path_edit.setText(path)
        editor = self._extra_editors.get("model_path")
        if isinstance(editor, QLineEdit):
            editor.setText(path)
        self._set_status(self._status_for_provider("vosk"))

    def _vosk_model_path(self) -> str:
        if self.vosk_path_edit.text().strip():
            return self.vosk_path_edit.text().strip()
        values = self._config_manager.get_adapter_extra_config("asr", "vosk")
        configured = str(values.get("model_path") or "").strip()
        if configured and Path(configured).expanduser().is_absolute():
            if self._is_vosk_model_dir(configured):
                return configured
            default_path = default_vosk_model_path()
            if default_path != configured and self._is_vosk_model_dir(default_path):
                return default_path
            return configured
        return default_vosk_model_path()

    def _is_vosk_model_dir(self, path: str) -> bool:
        return is_vosk_model_dir(path)

    def _schema_values(self, provider: str) -> dict[str, Any]:
        values = _read_schema_values(self._extra_schema, self._extra_editors)
        if provider == "vosk":
            values["model_path"] = self._vosk_model_path()
        return values

    def _set_vosk_model_path(self, path: str | Path) -> None:
        text = Path(path).expanduser().as_posix()
        self.vosk_path_edit.setText(text)
        editor = self._extra_editors.get("model_path")
        if isinstance(editor, QLineEdit):
            editor.setText(text)

    def _save_to_config(self, *, reset_adapter: bool) -> None:
        provider = self._current_provider()
        sys_cfg = self._config_manager.config.system_config.model_copy(deep=True)
        sys_cfg.asr_provider = provider
        sys_cfg.asr_language = str(self.language_combo.currentData() or "")
        sys_cfg.asr_whisper_model_size = self._current_model()
        sys_cfg.asr_whisper_device = str(self.device_combo.currentData() or "auto")
        sys_cfg.asr_whisper_compute_type = str(self.compute_combo.currentData() or "")
        self._config_manager.config.system_config = sys_cfg
        self._config_manager.set_adapter_extra_config(
            "asr",
            provider,
            self._schema_values(provider),
        )
        self._config_manager.save_system_config()
        self._config_manager.save_api_config()
        if reset_adapter and callable(self._reset_adapter_callback):
            self._reset_adapter_callback()

    def _project_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    def _uses_embedded_runtime(self) -> bool:
        py = Path(sys.executable).resolve()
        return py.parent.name in {"bin", "Scripts"} and py.parent.parent.name == "runtime"

    def _venv_python(self) -> Path:
        root = self._project_root()
        if sys.platform.startswith("win"):
            return root / ".venv" / "Scripts" / "python.exe"
        return root / ".venv" / "bin" / "python"

    def _can_install_dependencies(self) -> bool:
        if getattr(sys, "frozen", False):
            return False
        if self._uses_embedded_runtime():
            return False
        root = self._project_root()
        return (root / "pyproject.toml").is_file()

    def _install_current_dependencies(self) -> None:
        if self._install_running:
            return
        provider = self._current_provider()
        missing = self._missing_requirements(provider)
        if not missing:
            self._set_status(self._status_for_provider(provider))
            return
        self._save_to_config(reset_adapter=False)
        self._install_running = True
        self.install_deps_btn.setEnabled(False)
        self.preload_btn.setEnabled(False)
        self._set_status(tr("desktop.settings_dialog.asr_deps_install_start"))
        threading.Thread(
            target=self._dependency_install_worker,
            args=(provider,),
            daemon=True,
            name="here_asr_dependency_install",
        ).start()

    def _dependency_install_worker(self, provider: str) -> None:
        try:
            command, cwd, env = self._dependency_install_command(provider)
            self._install_signals.status.emit(
                tr("desktop.settings_dialog.asr_deps_install_running", command=" ".join(command))
            )
            proc = subprocess.run(
                command,
                cwd=str(cwd) if cwd else None,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=900,
                check=False,
            )
            if proc.returncode != 0:
                tail = (proc.stdout or "").strip().splitlines()[-12:]
                detail = "\n".join(tail).strip()
                raise RuntimeError(
                    tr("desktop.settings_dialog.asr_deps_install_failed_detail", detail=detail or proc.returncode)
            )
            importlib.invalidate_caches()
            install_user_python_packages_path()
            missing = self._missing_requirements(provider)
            if missing:
                raise RuntimeError(
                    tr(
                        "desktop.settings_dialog.asr_deps_still_missing",
                        modules=", ".join(missing),
                    )
                )
        except BaseException as exc:
            self._install_signals.finished.emit(False, str(exc))
            return
        self._install_signals.finished.emit(True, tr("desktop.settings_dialog.asr_deps_ready"))

    def _dependency_install_command(self, provider: str) -> tuple[list[str], Path | None, dict[str, str] | None]:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        root = self._project_root()
        if self._can_install_dependencies():
            uv = shutil.which("uv")
            if uv:
                return [uv, "sync", "--python", "3.11", "--extra", "asr"], root, env

        py = self._venv_python() if self._can_install_dependencies() else Path(sys.executable)
        if not py.is_file():
            py = Path(sys.executable)
        packages = list(ASR_PROVIDER_INSTALL_PACKAGES.get(provider, ()) or ("pyaudio", "vosk"))
        command = [str(py), "-m", "pip", "install", *packages]
        if not self._can_install_dependencies():
            target = install_user_python_packages_path()
            command.extend(["--target", str(target), "--upgrade"])
            env["PYTHONPATH"] = f"{target}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
        return command, None, env

    def _on_dependency_install_finished(self, ok: bool, message: str) -> None:
        self._install_running = False
        self.install_deps_btn.setEnabled(True)
        self.preload_btn.setEnabled(not bool(self._missing_requirements(self._current_provider())))
        self._set_status(message if not ok else self._status_for_provider(self._current_provider()))
        if not ok:
            QMessageBox.warning(self, tr("desktop.settings_dialog.asr_deps_install_failed"), message)
            return
        if callable(self._notify_callback):
            self._notify_callback(message)
        if self._auto_prepare:
            self._auto_prepare = False
            QTimer.singleShot(0, self._auto_prepare_if_possible)

    def _auto_prepare_if_possible(self) -> None:
        provider = self._current_provider()
        if self._missing_requirements(provider):
            self._install_current_dependencies()
            return
        if provider == "vosk" and not self._is_vosk_model_dir(self._vosk_model_path()):
            self._preload_current_model()

    def _save_and_accept(self) -> None:
        self._save_to_config(reset_adapter=True)
        if callable(self._notify_callback):
            label = ASR_PROVIDER_LABELS.get(self._current_provider(), self._current_provider())
            self._notify_callback(tr("desktop.settings_dialog.asr_saved", label=label))
        self.accept()

    def _preload_current_model(self) -> None:
        if self._preload_running:
            return
        if self._missing_requirements(self._current_provider()):
            self._set_status(self._status_for_provider(self._current_provider()))
            return
        self._save_to_config(reset_adapter=False)
        provider = self._current_provider()
        args = {
            "provider": provider,
            "model": self._current_model(),
            "device": str(self.device_combo.currentData() or "auto"),
            "compute": str(self.compute_combo.currentData() or ""),
            "vosk_path": self._vosk_model_path(),
        }
        self._preload_running = True
        self.preload_btn.setEnabled(False)
        self.install_deps_btn.setEnabled(False)
        self._set_status(tr("desktop.settings_dialog.model_prepare_start"))
        threading.Thread(
            target=self._preload_worker,
            kwargs=args,
            daemon=True,
            name="here_asr_preload",
        ).start()

    def _preload_worker(
        self,
        *,
        provider: str,
        model: str,
        device: str,
        compute: str,
        vosk_path: str,
    ) -> None:
        try:
            missing = self._missing_requirements(provider)
            if missing:
                raise RuntimeError(
                    tr(
                        "desktop.settings_dialog.asr_deps_missing",
                        modules=", ".join(missing),
                        command=self._install_command_label(provider),
                    )
                )
            if provider == "vosk":
                self._download_vosk_model(vosk_path)
            else:
                self._preload_whisper_model(model, device, compute)
        except BaseException as exc:
            self._preload_signals.finished.emit(False, str(exc))
            return
        self._preload_signals.finished.emit(True, tr("desktop.settings_dialog.model_ready"))

    def _download_vosk_model(self, model_path: str) -> None:
        target = Path(model_path).expanduser()
        if self._is_vosk_model_dir(str(target)):
            self._preload_signals.status.emit(tr("desktop.settings_dialog.vosk_exists", path=target))
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        zip_path = target.parent / f"{VOSK_SMALL_CN_MODEL_DIRNAME}.zip"
        self._preload_signals.status.emit(tr("desktop.settings_dialog.download_vosk"))
        urllib.request.urlretrieve(VOSK_SMALL_CN_URL, zip_path)
        self._preload_signals.status.emit(tr("desktop.settings_dialog.extract_vosk"))
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(target.parent)
        extracted_default = target.parent / VOSK_SMALL_CN_MODEL_DIRNAME
        if not self._is_vosk_model_dir(str(target)) and self._is_vosk_model_dir(str(extracted_default)):
            if target.exists():
                shutil.rmtree(target)
            shutil.move(str(extracted_default), str(target))
        if not self._is_vosk_model_dir(str(target)):
            raise RuntimeError(tr("desktop.settings_dialog.vosk_extract_missing", path=target))
        try:
            zip_path.unlink()
        except OSError:
            pass
        self._preload_signals.status.emit(tr("desktop.settings_dialog.vosk_ready", path=target))

    def _preload_whisper_model(self, model: str, device: str, compute: str) -> None:
        self._preload_signals.status.emit(tr("desktop.settings_dialog.preload_whisper", model=model))
        from faster_whisper import WhisperModel

        dev = device or "auto"
        compute_type = compute or ("int8" if dev in ("auto", "cpu") else "float16")
        _model = WhisperModel(model, device=dev, compute_type=compute_type)
        del _model
        self._preload_signals.status.emit(tr("desktop.settings_dialog.whisper_cached", model=model))

    def _set_status(self, text: str) -> None:
        _set_status_label_text(self.status_label, text)

    def _on_preload_finished(self, ok: bool, message: str) -> None:
        self._preload_running = False
        self.preload_btn.setEnabled(True)
        self.install_deps_btn.setEnabled(not bool(self._missing_requirements(self._current_provider())))
        self._set_status(message)
        if ok:
            if self._current_provider() == "vosk":
                self._set_vosk_model_path(self._vosk_model_path())
            self._save_to_config(reset_adapter=True)
            if callable(self._notify_callback):
                self._notify_callback(message)
            self._set_status(self._status_for_provider(self._current_provider()))
        else:
            QMessageBox.warning(self, tr("desktop.settings_dialog.model_prepare_failed"), message)
