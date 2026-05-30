"""主窗口设置菜单（历史、字体、语言、音量、主题等）。"""

from __future__ import annotations

import pygame
import shutil
from openai import OpenAI
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QComboBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)
from pathlib import Path

from infrastructure.paths import get_app_paths
from services.config.config_manager import ConfigManager, SYSTEM_CHARACTER_NAME
from core.agent import create_agent_backend
from internal_agent.context import AgentMemoryStore
from core.delivery import (
    DeliveryAdapterRegistry,
    DeliveryCapabilityProbe,
    DeliveryRouter,
    DesktopDeliveryAdapter,
    MessagingDeliveryAdapter,
)
from core.delivery.chat_platform_bridge import start_chat_platform_bridge, stop_chat_platform_bridge
from core.delivery.models import DELIVERY_CHANNELS
from core.delivery.messaging import MessageSender, MessagingConfig, create_default_registry
from core.importers.codex_pet_importer import (
    default_codex_pet_search_dirs,
    find_codex_pet_dirs,
    import_codex_pet_as_character,
)
from core.life import LifeEngine
from core.runtime.app_runtime import try_get_app_runtime
from services.i18n import init_i18n, tr
from core.messaging.messages import UserInputMessage
from ui.desktop.asr_settings_dialog import ASRSettingsDialog
from ui.desktop.create_character_dialog import CreateCharacterDialog
from ui.desktop.external_delivery_settings_dialog import ExternalDeliverySettingsDialog
from ui.desktop.proactive_photo_settings_dialog import ProactivePhotoSettingsDialog
from ui.desktop.storage_settings_dialog import StorageSettingsDialog
from ui.desktop.tts_settings_dialog import TTSSettingsDialog
from services.tts.tts_manager import TTSAdapterFactory, TTSManager
from services.selfie.factory import build_selfie_runtime
from ui.desktop.components import (
    FontSizeDialog,
    LanguageDialog,
    MessageDialog,
    VolumeDialog,
)
from ui.desktop import styles
from ui.desktop.combo_style import style_combo_popup

config_manager = ConfigManager()

TTS_PROVIDER_LABELS = {
    "none": "desktop.menu.tts_none",
    "edge-tts": "desktop.settings_dialog.tts_provider_edge",
    "openai-tts": "desktop.settings_dialog.tts_provider_openai",
    "elevenlabs": "desktop.settings_dialog.tts_provider_elevenlabs",
    "minimax-tts": "desktop.settings_dialog.tts_provider_minimax",
    "fish-audio": "desktop.settings_dialog.tts_provider_fish",
}

ONLINE_TTS_PROVIDERS = (
    "edge-tts",
    "openai-tts",
    "elevenlabs",
    "minimax-tts",
    "fish-audio",
)

class DesktopMenuMixin:
    def _sync_i18n_from_config(self) -> None:
        init_i18n(str(config_manager.config.system_config.ui_language or "zh_CN"))

    def _tts_provider_label(self, provider: str) -> str:
        label = TTS_PROVIDER_LABELS.get(provider, provider)
        if label.startswith("desktop."):
            return tr(label)
        return label

    def show_sprite_scale_settings(self) -> None:
        """设置当前角色立绘缩放倍率。"""
        active_name = config_manager.resolve_active_character_name()
        character = config_manager.get_character_by_name(active_name)
        if character is None:
            self.setNotification(tr("desktop.menu.err_current_character_missing", name=active_name))
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(tr("desktop.menu.sprite_scale"))
        dialog.setModal(True)
        dialog.setStyleSheet(
            """
            QDialog {
                background-color: rgba(0, 0, 0, 220);
                color: white;
            }
            QLabel, QLineEdit {
                color: white;
                font-size: 14px;
            }
            QLineEdit {
                background-color: rgba(45, 45, 45, 230);
                border: 1px solid rgba(255, 255, 255, 80);
                border-radius: 6px;
                padding: 6px;
            }
            QPushButton {
                background-color: rgba(76, 175, 80, 210);
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 18px;
            }
            QPushButton:hover {
                background-color: rgba(76, 175, 80, 255);
            }
            """
        )
        layout = QFormLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        scale_input = QLineEdit(dialog)
        scale_input.setPlaceholderText("0.15 - 3.00")
        scale_input.setText(f"{float(getattr(character, 'sprite_scale', 1.0) or 1.0):.2f}")
        scale_input.selectAll()
        layout.addRow(f"{active_name}：", scale_input)

        button_row = QHBoxLayout()
        cancel_btn = QPushButton(tr("desktop.menu.cancel"), dialog)
        ok_btn = QPushButton(tr("desktop.menu.save"), dialog)
        cancel_btn.clicked.connect(dialog.reject)
        ok_btn.clicked.connect(dialog.accept)
        button_row.addStretch(1)
        button_row.addWidget(cancel_btn)
        button_row.addWidget(ok_btn)
        layout.addRow(button_row)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        raw_scale = scale_input.text().strip().replace("x", "").replace("X", "").replace("，", ".").replace(",", ".")
        try:
            scale = float(raw_scale)
        except ValueError:
            self.setNotification(tr("desktop.menu.err_sprite_scale_invalid"))
            return
        scale = max(0.15, min(3.0, scale))
        character.sprite_scale = round(scale, 3)
        config_manager.save_characters_config()
        self.setNotification(
            tr(
                "desktop.menu.notify_sprite_scale_saved",
                name=active_name,
                scale=f"{character.sprite_scale:.2f}",
            )
        )
        rt = try_get_app_runtime()
        if rt is not None:
            try:
                rt.ui_update_manager.update_sprite(active_name, 0)
            except Exception:
                pass

    def show_font_size_settings(self) -> None:
        """显示字体大小设置对话框"""
        dialog = FontSizeDialog(self.base_font_size_px, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_size = dialog.get_new_font_size()
            if new_size != self.base_font_size_px:
                self.base_font_size_px = new_size
                config_manager.config.system_config.base_font_size_px = new_size
                config_manager.save_system_config()
                self.apply_font_styles()
                self.setNotification(tr("desktop.menu.notify_font_size", size=new_size))

    def show_settings_menu(self, global_pos: QPoint | None = None) -> None:
        """显示设置下拉菜单"""
        try:
            config_manager.reload()
        except Exception:
            pass
        menu = QMenu(self)

        active_name = config_manager.resolve_active_character_name()
        character_menu = menu.addMenu(tr("desktop.menu.switch_character"))
        for character in config_manager.config.characters:
            name = str(character.name or "").strip()
            if not name:
                continue
            action = QAction(name, self)
            action.setCheckable(True)
            action.setChecked(name == active_name)
            action.triggered.connect(lambda _checked=False, n=name: self.switch_active_character(n))
            character_menu.addAction(action)
        create_character_action = QAction(tr("desktop.menu.create_character"), self)
        create_character_action.triggered.connect(self.show_create_character_dialog)
        edit_character_action = QAction(tr("desktop.menu.edit_character"), self)
        edit_character_action.triggered.connect(self.show_edit_character_dialog)
        delete_character_action = QAction(tr("desktop.menu.delete_character"), self)
        delete_character_action.triggered.connect(self.show_delete_character_dialog)
        delete_character_action.setEnabled(active_name != SYSTEM_CHARACTER_NAME)
        life_plan_action = QAction(tr("desktop.menu.life_plan"), self)
        life_plan_action.triggered.connect(self.show_life_plan_dialog)
        proactive_action = QAction(tr("desktop.menu.proactive_contact"), self)
        proactive_action.setCheckable(True)
        proactive_enabled = bool(
            getattr(config_manager.config.system_config, "proactive_contact_enabled", False)
        )
        proactive_action.setChecked(proactive_enabled)
        proactive_action.triggered.connect(self.toggle_proactive_contact)
        proactive_menu = QMenu(tr("desktop.menu.proactive_contact"), self)
        proactive_menu.addAction(proactive_action)
        proactive_photo_action = QAction(tr("desktop.menu.proactive_photo"), self)
        proactive_photo_action.setCheckable(True)
        proactive_photo_action.setChecked(
            bool(getattr(config_manager.config.system_config, "proactive_photo_enabled", False))
        )
        proactive_photo_action.triggered.connect(self.toggle_proactive_photo)
        proactive_menu.addAction(proactive_photo_action)
        proactive_photo_settings_action = QAction(tr("desktop.menu.proactive_photo_settings"), self)
        proactive_photo_settings_action.triggered.connect(self.show_proactive_photo_settings)
        proactive_menu.addAction(proactive_photo_settings_action)
        proactive_delivery_menu = proactive_menu.addMenu(tr("desktop.menu.proactive_delivery_channel"))
        self._populate_external_delivery_menu(proactive_delivery_menu)
        chat_platform_menu = QMenu(tr("desktop.menu.chat_platform"), self)
        self._populate_chat_platform_menu(chat_platform_menu)
        delivery_settings_action = QAction(tr("desktop.menu.configure_chat_platforms"), self)
        delivery_settings_action.triggered.connect(self.show_external_delivery_settings)

        records_menu = QMenu(tr("desktop.menu.conversation_records"), self)
        history_action = QAction(tr("desktop.menu.history"), self)
        clear_history_action = QAction(tr("desktop.menu.clear_history"), self)
        copy_history_action = QAction(tr("desktop.menu.copy_history"), self)
        language_action = QAction(tr("desktop.menu.ui_language"), self)
        storage_settings_action = QAction(tr("desktop.menu.storage_locations"), self)
        api_settings_action = QAction(tr("desktop.menu.api_settings"), self)
        asr_action = QAction(tr("desktop.menu.asr_settings"), self)
        display_state_menu = QMenu(tr("desktop.menu.display_state"), self)
        dialog_box_menu = display_state_menu.addMenu(tr("desktop.menu.dialog_box"))
        show_dialog_action = QAction(tr("desktop.menu.show"), self)
        show_dialog_action.setCheckable(True)
        show_dialog_action.setChecked(not self.is_dialog_box_collapsed())
        show_dialog_action.triggered.connect(
            lambda _checked=False: self.set_dialog_box_collapsed(False)
        )
        collapse_dialog_action = QAction(tr("desktop.menu.collapse"), self)
        collapse_dialog_action.setCheckable(True)
        collapse_dialog_action.setChecked(self.is_dialog_box_collapsed())
        collapse_dialog_action.triggered.connect(
            lambda _checked=False: self.set_dialog_box_collapsed(True)
        )
        dialog_box_menu.addAction(show_dialog_action)
        dialog_box_menu.addAction(collapse_dialog_action)
        input_bar_menu = display_state_menu.addMenu(tr("desktop.menu.input_bar"))
        show_input_bar_action = QAction(tr("desktop.menu.show"), self)
        show_input_bar_action.setCheckable(True)
        show_input_bar_action.setChecked(not self.is_input_bar_collapsed())
        show_input_bar_action.triggered.connect(
            lambda _checked=False: self.set_input_bar_collapsed(False)
        )
        collapse_input_bar_action = QAction(tr("desktop.menu.collapse"), self)
        collapse_input_bar_action.setCheckable(True)
        collapse_input_bar_action.setChecked(self.is_input_bar_collapsed())
        collapse_input_bar_action.triggered.connect(
            lambda _checked=False: self.set_input_bar_collapsed(True)
        )
        input_bar_menu.addAction(show_input_bar_action)
        input_bar_menu.addAction(collapse_input_bar_action)
        process_hint_menu = display_state_menu.addMenu(tr("desktop.menu.process_hint"))
        show_process_hint_action = QAction(tr("desktop.menu.show"), self)
        show_process_hint_action.setCheckable(True)
        show_process_hint_action.setChecked(not self.is_process_hint_collapsed())
        show_process_hint_action.triggered.connect(
            lambda _checked=False: self.set_process_hint_collapsed(False)
        )
        collapse_process_hint_action = QAction(tr("desktop.menu.collapse"), self)
        collapse_process_hint_action.setCheckable(True)
        collapse_process_hint_action.setChecked(self.is_process_hint_collapsed())
        collapse_process_hint_action.triggered.connect(
            lambda _checked=False: self.set_process_hint_collapsed(True)
        )
        process_hint_menu.addAction(show_process_hint_action)
        process_hint_menu.addAction(collapse_process_hint_action)
        sprite_scale_action = QAction(tr("desktop.menu.sprite_scale"), self)
        font_size_action = QAction(tr("desktop.menu.font_size"), self)
        volumn_action = QAction(tr("desktop.menu.volume"), self)
        pin_top_action = QAction(tr("desktop.menu.pin_top"), self)
        pin_top_action.setCheckable(True)
        pin_top_action.setChecked(bool(self.windowFlags() & Qt.WindowStaysOnTopHint))
        minimize_action = QAction(tr("desktop.menu.minimize"), self)
        close_action = QAction(tr("desktop.menu.close"), self)

        history_action.triggered.connect(lambda: self.open_chat_history_dialog.emit())
        language_action.triggered.connect(self.show_language_settings)
        storage_settings_action.triggered.connect(self.show_storage_settings)
        api_settings_action.triggered.connect(self.show_api_settings)
        asr_action.triggered.connect(self.show_asr_settings)
        clear_history_action.triggered.connect(self.clear_history)
        sprite_scale_action.triggered.connect(self.show_sprite_scale_settings)
        font_size_action.triggered.connect(self.show_font_size_settings)
        volumn_action.triggered.connect(self.show_volumn_settings)
        copy_history_action.triggered.connect(self.copy_chat_history_to_clipboard)
        pin_top_action.triggered.connect(self._toggle_pin_top)
        minimize_action.triggered.connect(self.minimize_window)
        close_action.triggered.connect(self.close)

        menu.addMenu(character_menu)
        menu.addAction(create_character_action)
        self._add_codex_pet_import_menu(menu)
        menu.addAction(edit_character_action)
        menu.addAction(delete_character_action)
        menu.addAction(sprite_scale_action)
        menu.addSeparator()
        menu.addMenu(chat_platform_menu)
        menu.addMenu(proactive_menu)
        menu.addAction(delivery_settings_action)
        menu.addSeparator()
        records_menu.addAction(history_action)
        records_menu.addAction(copy_history_action)
        records_menu.addAction(clear_history_action)
        records_menu.addSeparator()
        records_menu.addAction(life_plan_action)
        menu.addMenu(records_menu)
        menu.addAction(language_action)
        menu.addAction(storage_settings_action)
        menu.addAction(api_settings_action)
        menu.addAction(asr_action)
        self._add_tts_settings_menu(menu)
        menu.addMenu(display_state_menu)
        menu.addAction(font_size_action)
        menu.addAction(volumn_action)
        menu.addSeparator()
        menu.addAction(pin_top_action)
        menu.addAction(minimize_action)
        menu.addAction(close_action)

        if global_pos is None:
            btn = getattr(self, "settings_btn", None)
            if btn is not None:
                global_pos = btn.mapToGlobal(btn.rect().bottomLeft())
            else:
                global_pos = self.mapToGlobal(self.rect().center())
        menu.setStyleSheet(styles.menu_popup())
        menu.exec(global_pos)

    def toggle_proactive_contact(self, checked: bool) -> None:
        config_manager.set_proactive_contact_enabled(bool(checked))
        rt = try_get_app_runtime()
        scheduler = getattr(rt, "proactive_contact_scheduler", None) if rt is not None else None
        if scheduler is not None and checked:
            try:
                scheduler.request_generate_today()
            except Exception as exc:
                print(f"主动联系计划生成失败: {exc}")
        key = (
            "desktop.menu.notify_proactive_contact_enabled"
            if checked
            else "desktop.menu.notify_proactive_contact_disabled"
        )
        self.setNotification(tr(key))

    def toggle_proactive_photo(self, checked: bool) -> None:
        config_manager.set_proactive_photo_enabled(bool(checked))
        ok, message = self._reload_proactive_photo_service()
        key = (
            "desktop.menu.notify_proactive_photo_enabled"
            if checked
            else "desktop.menu.notify_proactive_photo_disabled"
        )
        if ok:
            self.setNotification(tr(key))
        else:
            self.setNotification(f"{tr(key)}；附图运行时刷新失败：{message}")

    def _reload_proactive_photo_service(self) -> tuple[bool, str]:
        rt = try_get_app_runtime()
        if rt is None:
            return True, ""
        try:
            service, manager = build_selfie_runtime(
                config_manager,
                existing_manager=getattr(rt, "selfie_t2i_manager", None),
                enabled_only=True,
            )
            rt.selfie_service = service
            rt.selfie_t2i_manager = manager
            scheduler = getattr(rt, "proactive_contact_scheduler", None)
            if scheduler is not None:
                if service is None:
                    scheduler.photo_generator = None
                else:
                    scheduler.photo_generator = lambda request, svc=service: (
                        (result.path if (result := svc.generate(request)) is not None else "")
                    )
            return True, ""
        except Exception as exc:
            return False, str(exc)

    def show_proactive_photo_settings(self) -> None:
        self._sync_i18n_from_config()
        try:
            config_manager.reload()
        except Exception:
            pass
        dialog = ProactivePhotoSettingsDialog(
            self,
            config_manager=config_manager,
            apply_callback=self._reload_proactive_photo_service,
            notify_callback=self.setNotification,
        )
        dialog.exec()

    def _populate_external_delivery_menu(self, menu: QMenu) -> None:
        try:
            capabilities = DeliveryCapabilityProbe(config_manager).probe()
        except Exception:
            capabilities = {}
        sc = config_manager.config.system_config
        selected = str(getattr(sc, "external_delivery_channel", "desktop_chat") or "desktop_chat")
        external_enabled = bool(getattr(sc, "external_delivery_enabled", False))
        for channel in DELIVERY_CHANNELS:
            cap = capabilities.get(channel)
            label = cap.label if cap is not None else channel
            unavailable = channel != "desktop_chat" and cap is not None and not cap.available
            if unavailable:
                label = f"{label} ({tr('desktop.menu.external_delivery_unavailable', reason=cap.reason)})"
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(
                (channel == "desktop_chat" and not external_enabled)
                or (external_enabled and selected == channel)
            )
            action.setEnabled(True)
            if unavailable:
                action.triggered.connect(lambda _checked=False, c=channel: self.show_external_delivery_settings(c))
            else:
                action.triggered.connect(lambda _checked=False, c=channel: self.select_external_delivery_channel(c))
            menu.addAction(action)

    def _populate_chat_platform_menu(self, menu: QMenu) -> None:
        try:
            capabilities = DeliveryCapabilityProbe(config_manager).probe()
        except Exception:
            capabilities = {}
        sc = config_manager.config.system_config
        selected = str(getattr(sc, "chat_delivery_channel", "desktop_chat") or "desktop_chat")
        for channel in DELIVERY_CHANNELS:
            cap = capabilities.get(channel)
            label = cap.label if cap is not None else channel
            unavailable = channel != "desktop_chat" and cap is not None and not cap.available
            if unavailable:
                label = f"{label} ({tr('desktop.menu.external_delivery_unavailable', reason=cap.reason)})"
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(selected == channel)
            action.setEnabled(True)
            if unavailable:
                action.triggered.connect(lambda _checked=False, c=channel: self.show_external_delivery_settings(c))
            else:
                action.triggered.connect(lambda _checked=False, c=channel: self.select_chat_delivery_channel(c))
            menu.addAction(action)

    def select_external_delivery_channel(self, channel: str) -> None:
        normalized = str(channel or "desktop_chat").strip().lower()
        enabled = normalized != "desktop_chat"
        config_manager.set_external_delivery_channel(normalized, enabled=enabled)
        self._refresh_delivery_runtime()
        key = (
            "desktop.menu.notify_external_delivery_desktop"
            if normalized == "desktop_chat"
            else "desktop.menu.notify_external_delivery_channel"
        )
        self.setNotification(tr(key, channel=normalized))

    def select_chat_delivery_channel(self, channel: str) -> None:
        normalized = str(channel or "desktop_chat").strip().lower()
        if normalized not in DELIVERY_CHANNELS:
            normalized = "desktop_chat"
        config_manager.set_chat_delivery_channel(normalized)
        self._refresh_delivery_runtime()
        if hasattr(self, "apply_chat_delivery_visibility"):
            self.apply_chat_delivery_visibility()
        self.setNotification(tr("desktop.menu.notify_chat_platform_channel", channel=normalized))

    def show_external_delivery_settings(self, channel: str = "") -> None:
        dialog = ExternalDeliverySettingsDialog(self, initial_channel=channel)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._refresh_delivery_runtime()
            self.setNotification("外部发送渠道配置已保存。")

    def _refresh_delivery_runtime(self) -> None:
        rt = try_get_app_runtime()
        if rt is None:
            return
        try:
            rt.delivery_router = DeliveryRouter(config_manager, DeliveryCapabilityProbe(config_manager))
            sender = MessageSender(
                config=MessagingConfig.auto_load(),
                registry=create_default_registry(rt.tts_queue.put),
            )
            rt.delivery_adapters = DeliveryAdapterRegistry(
                DesktopDeliveryAdapter(rt.tts_queue.put),
                MessagingDeliveryAdapter(sender),
            )
            scheduler = getattr(rt, "proactive_contact_scheduler", None)
            if scheduler is not None:
                scheduler.delivery_router = rt.delivery_router
                scheduler.delivery_adapters = rt.delivery_adapters
            stop_chat_platform_bridge(getattr(rt, "chat_platform_bridge", None))
            rt.chat_platform_bridge = start_chat_platform_bridge(
                channel=getattr(config_manager.config.system_config, "chat_delivery_channel", "desktop_chat"),
                emit_user_text=lambda text: rt.user_input_queue.put(UserInputMessage(text=text)),
                notify=rt.ui_update_manager.post_notification,
            )
            if hasattr(self, "apply_chat_delivery_visibility"):
                self.apply_chat_delivery_visibility()
        except Exception as exc:
            print(f"刷新外部发送运行时失败: {exc}")

    def show_volumn_settings(self) -> None:
        dialog = VolumeDialog(
            config_manager.config.system_config.music_volumn, self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_volumn = dialog.get_new_volume()
            config_manager.config.system_config.music_volumn = selected_volumn
            config_manager.save_system_config()
            pygame.mixer.music.set_volume(selected_volumn / 100)

    def _toggle_pin_top(self, checked: bool) -> None:
        """切换窗口置顶状态。"""
        if checked:
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowStaysOnTopHint)
        self.show()  # 改 flags 后必须 show 才能生效

    def clear_history(self) -> None:
        reply = QMessageBox.question(
            self,
            tr("desktop.menu.confirm_clear_title"),
            tr("desktop.menu.confirm_clear_body"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.clear_chat_history.emit()

    def open_history_dialog(self, messages) -> None:
        dialog = MessageDialog(messages, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_revert_user_index is not None:
            self.revert_chat_history.emit(dialog.selected_revert_user_index)

    def show_language_settings(self) -> None:
        """显示界面语言设置。"""
        current = str(config_manager.config.system_config.ui_language or "zh_CN")
        dialog = LanguageDialog(self, mode="ui", current_language=current)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_language = dialog.get_selected_language()
            print(f"选择的界面语言: {selected_language}")
            ui_labels = {
                "en": "template.voice_lang_en",
                "zh_CN": "template.voice_lang_zh",
                "ja": "template.voice_lang_ja",
                "ko": "template.voice_lang_ko",
            }
            language_str = tr(ui_labels.get(selected_language, "template.voice_lang_zh"))

            config_manager.set_ui_language(selected_language)
            init_i18n(selected_language)
            self.setNotification(
                tr("desktop.menu.notify_ui_language", lang=language_str)
            )

    def _reset_mic_adapter_after_asr_change(self) -> None:
        mic_button = getattr(self, "mic_button", None)
        if mic_button is None:
            return
        reset = getattr(mic_button, "reset_adapter", None)
        if callable(reset):
            reset()

    def show_asr_settings(self, *, auto_prepare: bool = False) -> None:
        self._sync_i18n_from_config()
        dialog = ASRSettingsDialog(
            self,
            config_manager=config_manager,
            reset_adapter_callback=self._reset_mic_adapter_after_asr_change,
            notify_callback=self.setNotification,
            auto_prepare=auto_prepare,
        )
        dialog.exec()

    def show_storage_settings(self) -> None:
        self._sync_i18n_from_config()
        try:
            config_manager.reload()
        except Exception:
            pass
        dialog = StorageSettingsDialog(
            self,
            config_manager=config_manager,
            notify_callback=self.setNotification,
        )
        dialog.exec()

    def show_api_settings(self) -> None:
        """Show the lightweight Agent backend settings dialog."""
        self._sync_i18n_from_config()
        try:
            config_manager.reload()
        except Exception:
            pass
        api = config_manager.config.api_config
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("desktop.menu.api_settings"))
        dialog.setModal(True)
        dialog.setMinimumWidth(520)
        dialog.setStyleSheet(
            """
            QDialog {
                background-color: rgba(24, 26, 32, 238);
                color: white;
            }
            QLabel {
                color: rgba(255, 255, 255, 220);
                font-size: 13px;
            }
            QLineEdit, QComboBox {
                background-color: rgba(45, 45, 45, 230);
                color: white;
                border: 1px solid rgba(255, 255, 255, 80);
                border-radius: 6px;
                padding: 6px;
            }
            QPushButton {
                background-color: rgba(76, 175, 80, 210);
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 18px;
            }
            QPushButton:hover {
                background-color: rgba(76, 175, 80, 255);
            }
            """
        )
        root = QVBoxLayout(dialog)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)
        form = QFormLayout()
        form.setSpacing(10)

        backend_combo = QComboBox(dialog)
        style_combo_popup(backend_combo)
        backend_combo.addItem("Hermes Agent", "hermes-agent")
        backend_combo.addItem("Internal Agent", "internal-agent")
        backend_combo.addItem("Auto", "auto")
        current_backend = str(getattr(api, "agent_backend", "auto") or "auto")
        idx = backend_combo.findData(current_backend)
        backend_combo.setCurrentIndex(idx if idx >= 0 else 0)

        provider_edit = QLineEdit(str(getattr(api, "internal_agent_provider", "") or "openai"), dialog)
        model_edit = QLineEdit(str(getattr(api, "internal_agent_model", "") or "gpt-4o-mini"), dialog)
        base_url_edit = QLineEdit(str(getattr(api, "internal_agent_base_url", "") or "https://api.openai.com/v1"), dialog)
        api_key_edit = QLineEdit(str(getattr(api, "internal_agent_api_key", "") or ""), dialog)
        api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        model_combo = QComboBox(dialog)
        style_combo_popup(model_combo)
        model_combo.setEditable(False)
        model_combo.setVisible(False)
        fetch_models_btn = QPushButton(tr("desktop.settings_dialog.fetch_models"), dialog)

        core_rows: list[QWidget] = []
        model_combo_row: list[QWidget] = []

        def add_core_row(label_key: str, widget: QWidget, *, row_group: list[QWidget] | None = None) -> None:
            label = QLabel(tr(label_key), dialog)
            form.addRow(label, widget)
            core_rows.extend([label, widget])
            if row_group is not None:
                row_group.extend([label, widget])

        form.addRow(QLabel(tr("desktop.settings_dialog.agent_backend"), dialog), backend_combo)
        add_core_row("desktop.settings_dialog.core_provider", provider_edit)
        add_core_row("desktop.settings_dialog.core_model", model_edit)
        add_core_row("desktop.settings_dialog.available_models", model_combo, row_group=model_combo_row)
        add_core_row("desktop.settings_dialog.core_base_url", base_url_edit)
        add_core_row("desktop.settings_dialog.core_api_key", api_key_edit)
        add_core_row("desktop.settings_dialog.fetch_models", fetch_models_btn)

        hint = QLabel(tr("desktop.settings_dialog.agent_backend_hint"), dialog)
        hint.setWordWrap(True)
        root.addWidget(hint)
        root.addLayout(form)

        def update_core_visibility() -> None:
            show_core = str(backend_combo.currentData() or "") in {"internal-agent", "auto"}
            for row_widget in core_rows:
                row_widget.setVisible(show_core)
            show_model_combo = show_core and model_combo.count() > 0
            for row_widget in model_combo_row:
                row_widget.setVisible(show_model_combo)

        backend_combo.currentIndexChanged.connect(lambda *_: update_core_visibility())
        update_core_visibility()

        def fetch_available_models() -> None:
            base_url = base_url_edit.text().strip()
            api_key = api_key_edit.text().strip() or "unused"
            try:
                client = OpenAI(api_key=api_key, base_url=base_url.rstrip("/") or None)
                ids = sorted(str(model.id) for model in client.models.list().data if str(model.id or "").strip())
            except Exception as exc:
                QMessageBox.warning(
                    dialog,
                    tr("desktop.settings_dialog.fetch_models_failed_title"),
                    tr("desktop.settings_dialog.fetch_models_failed", error=str(exc)),
                )
                return
            if not ids:
                QMessageBox.information(
                    dialog,
                    tr("desktop.settings_dialog.fetch_models_title"),
                    tr("desktop.settings_dialog.fetch_models_empty"),
                )
                return
            model_combo.blockSignals(True)
            model_combo.clear()
            for model_id in ids:
                model_combo.addItem(model_id, model_id)
            model_combo.blockSignals(False)
            current_model = model_edit.text().strip()
            idx = model_combo.findText(current_model)
            if idx < 0:
                preferred = next(
                    (
                        model_id
                        for model_id in ids
                        if model_id.startswith("step-3.7")
                        or model_id.startswith("step-3.5")
                        or model_id == "gpt-4o-mini"
                    ),
                    ids[0],
                )
                idx = model_combo.findText(preferred)
                model_edit.setText(preferred)
                self.setNotification(
                    tr(
                        "desktop.menu.notify_model_unavailable_replaced",
                        old=current_model or "-",
                        new=preferred,
                    )
                )
            model_combo.setCurrentIndex(idx if idx >= 0 else 0)
            model_combo.setVisible(True)
            update_core_visibility()

        def apply_model_combo(index: int) -> None:
            model_id = str(model_combo.itemData(index) or model_combo.currentText() or "").strip()
            if model_id:
                model_edit.setText(model_id)

        model_combo.currentIndexChanged.connect(apply_model_combo)
        fetch_models_btn.clicked.connect(fetch_available_models)

        buttons = QHBoxLayout()
        cancel_btn = QPushButton(tr("desktop.menu.cancel"), dialog)
        save_btn = QPushButton(tr("desktop.menu.save"), dialog)
        cancel_btn.clicked.connect(dialog.reject)
        save_btn.clicked.connect(dialog.accept)
        buttons.addStretch(1)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(save_btn)
        root.addLayout(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        api_new = api.model_copy(
            update={
                "agent_backend": str(backend_combo.currentData() or "hermes-agent"),
                "internal_agent_provider": provider_edit.text().strip(),
                "internal_agent_model": model_edit.text().strip(),
                "internal_agent_base_url": base_url_edit.text().strip(),
                "internal_agent_api_key": api_key_edit.text().strip(),
            }
        )
        config_manager.config.api_config = api_new
        config_manager.save_api_config()
        rt = try_get_app_runtime()
        selected_backend = str(backend_combo.currentText())
        runtime_backend = ""
        if rt is not None:
            try:
                old_backend = getattr(rt, "agent_backend", None)
                system_prompt = str(getattr(old_backend, "system_prompt", "") or "")
                new_backend = create_agent_backend(
                    config_manager,
                    system_prompt=system_prompt,
                    status_callback=rt.ui_update_manager.post_notification,
                    tool_status_callback=lambda text: rt.ui_update_manager.post_busy_bar(str(text), 0.0),
                )
                rt.agent_backend = new_backend
                if hasattr(self, "agent_backend"):
                    self.agent_backend = new_backend
                if getattr(rt, "life_scheduler", None) is not None:
                    rt.life_scheduler.agent_backend = new_backend
                if getattr(rt, "proactive_contact_scheduler", None) is not None:
                    rt.proactive_contact_scheduler.agent_backend = new_backend
                if old_backend is not None and hasattr(old_backend, "reset_session"):
                    old_backend.reset_session()
                runtime_backend = str(
                    getattr(new_backend, "selected_backend_id", type(new_backend).__name__)
                    or ""
                )
            except Exception as exc:
                self.setNotification(f"Agent 后端配置已保存，但即时切换失败：{exc}")
                return
        if runtime_backend and runtime_backend != str(backend_combo.currentData() or ""):
            selected_backend = f"{selected_backend}（当前实际运行：{runtime_backend}）"
        elif runtime_backend:
            selected_backend = f"{selected_backend}（已生效）"
        self.setNotification(tr("desktop.menu.notify_agent_backend_saved", backend=selected_backend))

    def show_create_character_dialog(self) -> None:
        self._sync_i18n_from_config()
        dialog = CreateCharacterDialog(self, config_manager=config_manager)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        config_manager.reload()
        self.switch_active_character(dialog.character_name)
        self.setNotification(
            tr("desktop.menu.notify_character_created", name=dialog.character_name)
        )

    def show_edit_character_dialog(self) -> None:
        self._sync_i18n_from_config()
        try:
            config_manager.reload()
        except Exception:
            pass
        active_name = config_manager.resolve_active_character_name()
        if config_manager.get_character_by_name(active_name) is None:
            self.setNotification(tr("desktop.menu.err_current_character_missing", name=active_name))
            return
        dialog = CreateCharacterDialog(
            self,
            config_manager=config_manager,
            edit_character_name=active_name,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        old_name = dialog.original_character_name or active_name
        new_name = dialog.character_name or old_name
        if old_name != new_name:
            try:
                memory_store = None
                rt = try_get_app_runtime()
                if rt is not None:
                    memory_store = getattr(rt, "agent_memory_store", None)
                (memory_store or AgentMemoryStore()).rename_character(old_name, new_name)
            except Exception as exc:
                QMessageBox.warning(
                    self,
                    tr("desktop.menu.edit_character_failed_title"),
                    tr(
                        "desktop.menu.err_character_memory_rename_failed",
                        old=old_name,
                        new=new_name,
                        error=str(exc),
                    ),
                )
                return
        config_manager.reload()
        if old_name != new_name:
            config_manager.set_active_character_name(new_name)
        rt = try_get_app_runtime()
        if rt is not None and hasattr(rt.agent_backend, "reset_session"):
            rt.agent_backend.reset_session()
            if rt.active_character is not None:
                rt.active_character.set_name(new_name, persist=False)
            try:
                rt.ui_update_manager.update_sprite(new_name, 0)
            except Exception:
                pass
        self.setNotification(
            tr("desktop.menu.notify_character_edited", name=new_name)
        )

    def show_delete_character_dialog(self) -> None:
        self._sync_i18n_from_config()
        try:
            config_manager.reload()
        except Exception:
            pass
        active_name = config_manager.resolve_active_character_name()
        if active_name == SYSTEM_CHARACTER_NAME:
            QMessageBox.information(
                self,
                tr("desktop.menu.delete_character_failed_title"),
                tr("desktop.menu.err_system_character_protected"),
            )
            return
        character = config_manager.get_character_by_name(active_name)
        if character is None:
            self.setNotification(tr("desktop.menu.err_current_character_missing", name=active_name))
            return
        valid_names = [
            str(c.name or "").strip()
            for c in config_manager.config.characters
            if str(c.name or "").strip()
        ]
        if len(valid_names) <= 1:
            QMessageBox.warning(
                self,
                tr("desktop.menu.delete_character_failed_title"),
                tr("desktop.menu.err_delete_last_character"),
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(tr("desktop.menu.delete_character"))
        dialog.setModal(True)
        dialog.setStyleSheet(
            """
            QDialog {
                background-color: rgba(24, 26, 32, 238);
                color: white;
            }
            QLabel, QCheckBox {
                color: rgba(255, 255, 255, 220);
                font-size: 13px;
            }
            QCheckBox {
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
            QPushButton#DeleteCharacterDangerButton {
                background-color: rgba(220, 70, 70, 215);
            }
            QPushButton#DeleteCharacterDangerButton:hover {
                background-color: rgba(235, 78, 78, 245);
            }
            """
        )
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        message = QLabel(tr("desktop.menu.delete_character_body", name=active_name), dialog)
        message.setWordWrap(True)
        layout.addWidget(message)
        delete_memory_check = QCheckBox(
            tr("desktop.menu.delete_character_memory_checkbox"),
            dialog,
        )
        delete_memory_check.setChecked(False)
        delete_memory_check.setToolTip(tr("desktop.menu.delete_character_memory_tooltip"))
        layout.addWidget(delete_memory_check)
        hint = QLabel(tr("desktop.menu.delete_character_memory_hint"), dialog)
        hint.setWordWrap(True)
        hint.setStyleSheet("color: rgba(255, 214, 102, 230);")
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        cancel_btn = QPushButton(tr("desktop.menu.cancel"), dialog)
        delete_btn = QPushButton(tr("desktop.menu.delete_character_confirm"), dialog)
        delete_btn.setObjectName("DeleteCharacterDangerButton")
        cancel_btn.clicked.connect(dialog.reject)
        delete_btn.clicked.connect(dialog.accept)
        buttons.addStretch(1)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(delete_btn)
        layout.addLayout(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        delete_memory = delete_memory_check.isChecked()
        sprite_prefix = str(getattr(character, "sprite_prefix", "") or "").strip()
        try:
            config_manager.delete_character(active_name)
            if sprite_prefix:
                paths = get_app_paths()
                for base_dir in (
                    paths.characters_dir,
                    paths.generated_dir / "voices",
                    paths.models_dir,
                ):
                    char_dir = Path(base_dir) / sprite_prefix
                    if char_dir.exists():
                        shutil.rmtree(char_dir, ignore_errors=True)
            if delete_memory:
                memory_store = None
                rt = try_get_app_runtime()
                if rt is not None:
                    memory_store = getattr(rt, "agent_memory_store", None)
                (memory_store or AgentMemoryStore()).delete_character(active_name)
        except Exception as exc:
            QMessageBox.warning(
                self,
                tr("desktop.menu.delete_character_failed_title"),
                str(exc),
            )
            return

        config_manager.reload()
        if config_manager.get_character_by_name(SYSTEM_CHARACTER_NAME) is not None:
            next_name = config_manager.set_active_character_name(SYSTEM_CHARACTER_NAME)
        else:
            next_name = config_manager.resolve_active_character_name()
        rt = try_get_app_runtime()
        if rt is not None:
            if rt.active_character is not None:
                next_name = rt.active_character.set_name(next_name)
            if hasattr(rt.agent_backend, "reset_session"):
                rt.agent_backend.reset_session()
            try:
                rt.ui_update_manager.update_sprite(next_name, 0)
            except Exception:
                pass
        else:
            config_manager.set_active_character_name(next_name)
        self.setNotification(
            tr(
                "desktop.menu.notify_character_deleted",
                name=active_name,
                next=next_name,
            )
        )

    def show_life_plan_dialog(self) -> None:
        self._sync_i18n_from_config()
        try:
            config_manager.reload()
        except Exception:
            pass
        active_name = config_manager.resolve_active_character_name()
        character = config_manager.get_character_by_name(active_name)
        if character is None:
            self.setNotification(tr("desktop.menu.err_current_character_missing", name=active_name))
            return
        rt = try_get_app_runtime()
        memory_store = getattr(rt, "agent_memory_store", None) if rt is not None else None
        engine = getattr(rt, "life_engine", None) if rt is not None else None
        if engine is None:
            engine = LifeEngine(memory_store or AgentMemoryStore())
        try:
            plan = engine.ensure_daily_plan(
                character,
                agent_backend=getattr(rt, "agent_backend", None) if rt is not None else None,
            )
            body = engine.render_daily_plan(plan)
        except Exception as exc:
            QMessageBox.warning(
                self,
                tr("desktop.menu.life_plan"),
                tr("desktop.menu.life_plan_failed", error=str(exc)),
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(tr("desktop.menu.life_plan_dialog_title", name=active_name))
        dialog.setModal(True)
        dialog.resize(760, 560)
        dialog.setStyleSheet(
            """
            QDialog {
                background-color: rgba(24, 26, 32, 238);
                color: white;
            }
            QPlainTextEdit {
                background-color: rgba(18, 20, 25, 235);
                color: rgba(255, 255, 255, 230);
                border: 1px solid rgba(255, 255, 255, 55);
                border-radius: 6px;
                padding: 10px;
                font-size: 13px;
            }
            QPushButton {
                background-color: rgba(76, 175, 80, 205);
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: rgba(76, 175, 80, 245);
            }
            """
        )
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        text = QPlainTextEdit(dialog)
        text.setReadOnly(True)
        text.setPlainText(body)
        layout.addWidget(text, stretch=1)
        close_btn = QPushButton(tr("desktop.menu.close_life_plan"), dialog)
        close_btn.clicked.connect(dialog.accept)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)
        dialog.exec()

    def _add_codex_pet_import_menu(self, menu: QMenu) -> None:
        pet_menu = menu.addMenu(tr("desktop.menu.codex_pet_import"))
        discovered = find_codex_pet_dirs()
        for pet_dir in discovered[:12]:
            name = pet_dir.name
            action = QAction(name, self)
            action.setToolTip(str(pet_dir))
            action.triggered.connect(
                lambda _checked=False, p=pet_dir: self.import_codex_pet_directory(p)
            )
            pet_menu.addAction(action)
        if discovered:
            pet_menu.addSeparator()
        choose_action = QAction(tr("desktop.menu.choose_pet_folder"), self)
        choose_action.triggered.connect(self.choose_codex_pet_directory)
        pet_menu.addAction(choose_action)

    def choose_codex_pet_directory(self) -> None:
        search_dirs = default_codex_pet_search_dirs()
        start_dir = str(search_dirs[0]) if search_dirs else str(Path.home())
        path = QFileDialog.getExistingDirectory(
            self,
            tr("desktop.menu.choose_pet_folder_title"),
            start_dir,
        )
        if path:
            self.import_codex_pet_directory(path)

    def import_codex_pet_directory(self, pet_dir) -> None:
        try:
            result = import_codex_pet_as_character(
                pet_dir,
                config_manager=config_manager,
                make_active=True,
            )
            config_manager.reload()
            self.switch_active_character(result.character_name)
            self.setNotification(
                tr(
                    "desktop.menu.notify_codex_pet_imported",
                    name=result.character_name,
                    count=result.state_count,
                )
            )
        except Exception as exc:
            QMessageBox.warning(self, tr("desktop.menu.err_codex_pet_import_title"), str(exc))

    def _add_tts_settings_menu(self, menu: QMenu) -> None:
        """把当前桌面版可用的 TTS 设置挂到齿轮菜单。"""
        current_provider = self._normalize_tts_provider(
            str(getattr(config_manager.config.api_config, "tts_provider", "") or "none")
        )
        tts_menu = menu.addMenu(tr("desktop.menu.tts_settings"))
        settings_action = QAction(tr("desktop.menu.tts_settings_action"), self)
        settings_action.triggered.connect(self.show_tts_settings)
        tts_menu.addAction(settings_action)
        tts_menu.addSeparator()
        self._add_tts_provider_action(tts_menu, "none", current_provider)

    def _add_tts_provider_action(
        self, menu: QMenu, provider: str, current_provider: str
    ) -> None:
        label = self._tts_provider_label(provider)
        action = QAction(label, self)
        action.setCheckable(True)
        action.setChecked(provider == current_provider)
        action.triggered.connect(
            lambda _checked=False, p=provider: self.set_tts_provider(p)
        )
        menu.addAction(action)

    def _available_tts_providers(self) -> list[str]:
        providers = ["none"]
        for preferred in ONLINE_TTS_PROVIDERS:
            if preferred in TTSAdapterFactory._adapters:
                providers.append(preferred)
        for provider in TTSAdapterFactory._adapters:
            if provider not in providers:
                providers.append(provider)
        return providers

    def _normalize_tts_provider(self, provider: str) -> str:
        value = str(provider or "").strip().lower()
        aliases = {
            "off": "none",
            "disable": "none",
            "disabled": "none",
            "edge": "edge-tts",
            "edge_tts": "edge-tts",
            "openai": "openai-tts",
            "openai_tts": "openai-tts",
            "eleven": "elevenlabs",
            "eleven_labs": "elevenlabs",
            "minimax": "minimax-tts",
            "minimax_tts": "minimax-tts",
            "fish": "fish-audio",
            "fish_audio": "fish-audio",
        }
        value = aliases.get(value, value)
        if value == "none" or value in TTSAdapterFactory._adapters:
            return value
        return "edge-tts" if "edge-tts" in TTSAdapterFactory._adapters else "none"

    def set_tts_provider(self, provider: str) -> None:
        """保存并尽量即时切换 TTS 后端。"""
        provider_key = self._normalize_tts_provider(provider)
        api_cfg = config_manager.config.api_config.model_copy(deep=True)
        api_cfg.tts_provider = provider_key
        config_manager.config.api_config = api_cfg
        config_manager.save_api_config()
        ok, message = self._apply_tts_provider_runtime(provider_key)
        label = self._tts_provider_label(provider_key)
        if ok:
            self.setNotification(tr("desktop.menu.notify_tts_switched", label=label))
        else:
            self.setNotification(
                tr("desktop.menu.notify_tts_saved_apply_failed", label=label, message=message)
            )

    def show_tts_settings(self) -> None:
        self._sync_i18n_from_config()
        dialog = TTSSettingsDialog(
            self,
            config_manager=config_manager,
            apply_callback=self._apply_tts_provider_runtime,
            notify_callback=self.setNotification,
        )
        dialog.exec()

    def _apply_tts_provider_runtime(self, provider_key: str) -> tuple[bool, str]:
        rt = try_get_app_runtime()
        if rt is None:
            return True, ""
        old_manager = getattr(rt, "tts_manager", None)
        if provider_key == "none":
            try:
                if old_manager is not None:
                    old_manager.shutdown()
            except Exception as exc:
                return False, str(exc)
            rt.tts_manager = None
            return True, ""

        try:
            adapter = TTSAdapterFactory.create_adapter(
                provider_key,
                **config_manager.merged_tts_factory_kwargs(
                    provider_key,
                    {},
                ),
            )
            if old_manager is None:
                manager = TTSManager()
            else:
                manager = old_manager
            manager.set_tts_adapter(adapter)
            voice_lang = str(config_manager.config.system_config.voice_language or "ja").strip() or "ja"
            manager.set_language(voice_lang)
            rt.tts_manager = manager
            return True, ""
        except Exception as exc:
            return False, str(exc)
