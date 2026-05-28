"""Small desktop dialog for creating a runnable character."""

from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path

from infrastructure.paths import get_app_paths

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QImage, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from services.config.config_manager import ConfigManager
from services.config.config_manager import SYSTEM_CHARACTER_NAME
from services.config.schema import Character, Sprite
from core.sprite.character_profile import (
    MBTI_DESCRIPTIONS,
    MBTI_TYPES,
    build_character_setting_from_profile,
    normalize_character_profile,
)
from core.sprite.emotion_resolver import CORE_EMOTIONS
from services.i18n import tr
from ui.desktop.edit_context_menu import install_readable_edit_menus


STATE_GROUP_CORE_EMOTION = "core_emotion"

STATE_LABELS = {
    "neutral": "Neutral",
    "happy": "Happy",
    "thinking": "Thinking",
    "surprised": "Surprised",
    "sad": "Sad",
    "angry": "Angry",
}

STATE_TAGS = {
    "neutral": "默认、平静、普通、neutral",
    "happy": "开心、赞同、欢迎、happy",
    "thinking": "思考、等待、犹豫、thinking",
    "surprised": "惊讶、意外、注意力被拉起、surprised",
    "sad": "难过、失落、失败、sad",
    "angry": "生气、不满、抗议、angry",
}

IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.webp *.bmp)"
ANIMATION_FILTER = "Animation frames or video (*.png *.jpg *.jpeg *.webp *.bmp *.mp4 *.mov *.webm *.m4v *.avi)"
VIDEO_SUFFIXES = {".mp4", ".mov", ".webm", ".m4v", ".avi"}
MAX_VIDEO_FRAMES = 240

class CreateCharacterDialog(QDialog):
    def __init__(
        self,
        parent=None,
        *,
        config_manager: ConfigManager | None = None,
        edit_character_name: str = "",
    ) -> None:
        super().__init__(parent)
        self._config_manager = config_manager or ConfigManager()
        self._edit_character = self._config_manager.get_character_by_name(edit_character_name)
        self._state_files: dict[str, list[Path]] = {}
        self._state_path_edits: dict[str, QLineEdit] = {}
        self._state_preview_labels: dict[str, QLabel] = {}
        self._state_open_buttons: dict[str, QPushButton] = {}
        self._state_interval_inputs: dict[str, QSpinBox] = {}
        self._cleared_states: set[str] = set()
        self._existing_state_sprites: dict[str, dict[str, object]] = {}
        self._existing_extra_sprites: list[dict[str, object]] = []
        self._original_character_name = str(getattr(self._edit_character, "name", "") or "").strip()
        self._editing_system_character = self._original_character_name == SYSTEM_CHARACTER_NAME
        self._last_generated_setting = ""
        self._updating_setting_text = False

        title_key = "desktop.menu.edit_character" if self.is_editing else "desktop.menu.create_character"
        self.setWindowTitle(tr(title_key))
        self.setModal(True)
        self.resize(680, 720)
        self._build_ui()
        self._load_character_for_edit()

    @property
    def is_editing(self) -> bool:
        return self._edit_character is not None

    @property
    def character_name(self) -> str:
        return self.name_edit.text().strip()

    @property
    def original_character_name(self) -> str:
        return self._original_character_name

    @property
    def renamed_character(self) -> bool:
        return self.is_editing and self.character_name != self._original_character_name

    def _build_ui(self) -> None:
        self.setStyleSheet(
            """
            QDialog {
                background-color: rgba(24, 26, 32, 238);
                color: white;
            }
            QScrollArea,
            QScrollArea QWidget#qt_scrollarea_viewport,
            QWidget#CreateCharacterBody,
            QWidget#CreateCharacterStatePanel {
                background-color: rgba(24, 26, 32, 238);
                border: none;
            }
            QLabel {
                color: rgba(255, 255, 255, 220);
                font-size: 13px;
            }
            QLineEdit, QPlainTextEdit, QSpinBox {
                color: white;
                background-color: rgba(44, 47, 57, 235);
                border: 1px solid rgba(255, 255, 255, 72);
                border-radius: 6px;
                padding: 6px;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: rgba(68, 72, 84, 235);
                border: none;
                width: 16px;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background-color: rgba(86, 92, 108, 245);
            }
            QPlainTextEdit {
                min-height: 96px;
            }
            QLabel#CharacterAssetPreview {
                background-color: rgba(44, 47, 57, 235);
                border: 1px solid rgba(255, 255, 255, 45);
                border-radius: 6px;
                min-width: 48px;
                max-width: 48px;
                min-height: 48px;
                max-height: 48px;
            }
            QTabWidget::pane {
                border: 1px solid rgba(255, 255, 255, 45);
                border-radius: 6px;
                top: -1px;
            }
            QTabBar::tab {
                background-color: rgba(44, 47, 57, 220);
                color: rgba(255, 255, 255, 190);
                border: 1px solid rgba(255, 255, 255, 45);
                border-bottom: none;
                padding: 7px 10px;
                margin-right: 2px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }
            QTabBar::tab:selected {
                background-color: rgba(76, 175, 80, 115);
                color: white;
            }
            QComboBox {
                color: white;
                background-color: rgba(44, 47, 57, 235);
                border: 1px solid rgba(255, 255, 255, 72);
                border-radius: 6px;
                padding: 6px;
            }
            QPushButton#MbtiButton {
                background-color: rgba(44, 47, 57, 235);
                border: 1px solid rgba(255, 255, 255, 60);
            }
            QPushButton#MbtiButton:checked {
                background-color: rgba(76, 175, 80, 215);
                border: 1px solid rgba(180, 255, 185, 180);
            }
            QPushButton {
                background-color: rgba(76, 175, 80, 205);
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 12px;
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

        title_key = "desktop.menu.edit_character" if self.is_editing else "desktop.menu.create_character"
        hint_key = (
            "desktop.menu.edit_character_hint"
            if self.is_editing
            else "desktop.menu.create_character_hint"
        )
        title = QLabel(tr(title_key), self)
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        root.addWidget(title)

        hint = QLabel(tr(hint_key), self)
        hint.setWordWrap(True)
        hint.setStyleSheet("color: rgba(255,255,255,170);")
        root.addWidget(hint)

        if self.is_editing and not self._editing_system_character:
            warning = QLabel(tr("desktop.menu.edit_character_rename_warning"), self)
            warning.setWordWrap(True)
            warning.setStyleSheet(
                "color: rgba(255, 214, 102, 230);"
                "background-color: rgba(255, 193, 7, 28);"
                "border: 1px solid rgba(255, 193, 7, 90);"
                "border-radius: 6px;"
                "padding: 8px;"
            )
            root.addWidget(warning)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        scroll.viewport().setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        scroll.viewport().setStyleSheet("background-color: rgba(24, 26, 32, 238);")

        body = QWidget(scroll)
        body.setObjectName("CreateCharacterBody")
        body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        form = QFormLayout(body)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.name_edit = QLineEdit(body)
        self.name_edit.setPlaceholderText(tr("desktop.menu.create_character_name_placeholder"))
        self.name_edit.setReadOnly(self._editing_system_character)
        self.name_edit.textChanged.connect(lambda _text: self._sync_profile_preview())
        form.addRow(tr("desktop.menu.create_character_name"), self.name_edit)

        self.profile_tabs = QTabWidget(body)
        self._build_profile_tabs(self.profile_tabs)
        form.addRow("角色设定", self.profile_tabs)

        state_panel = QWidget(body)
        state_panel.setObjectName("CreateCharacterStatePanel")
        state_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        grid = QGridLayout(state_panel)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        grid.addWidget(QLabel(tr("desktop.menu.create_character_state"), state_panel), 0, 0)
        grid.addWidget(QLabel(tr("desktop.menu.create_character_preview"), state_panel), 0, 1)
        grid.addWidget(QLabel(tr("desktop.menu.create_character_asset"), state_panel), 0, 2)
        grid.addWidget(QLabel(tr("desktop.menu.create_character_frame_interval"), state_panel), 0, 3)

        for row, state in enumerate(CORE_EMOTIONS, start=1):
            label = QLabel(f"{STATE_LABELS.get(state, state)} ({state})", state_panel)
            label.setMinimumWidth(110)
            preview = QLabel(state_panel)
            preview.setObjectName("CharacterAssetPreview")
            preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            path_edit = QLineEdit(state_panel)
            path_edit.setReadOnly(True)
            path_edit.setPlaceholderText(tr("desktop.menu.create_character_no_asset"))
            path_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            interval_input = QSpinBox(state_panel)
            interval_input.setRange(16, 3000)
            interval_input.setSingleStep(10)
            interval_input.setSuffix(" ms")
            interval_input.setValue(120)
            interval_input.setToolTip(tr("desktop.menu.create_character_frame_interval_tip"))
            open_btn = QPushButton(tr("desktop.menu.open_asset"), state_panel)
            image_btn = QPushButton(tr("desktop.menu.import_image"), state_panel)
            anim_btn = QPushButton(tr("desktop.menu.import_animation"), state_panel)
            clear_btn = QPushButton(tr("desktop.menu.clear_asset"), state_panel)
            open_btn.clicked.connect(lambda _checked=False, s=state: self._open_state_asset(s))
            image_btn.clicked.connect(lambda _checked=False, s=state: self._choose_image(s))
            anim_btn.clicked.connect(lambda _checked=False, s=state: self._choose_animation(s))
            clear_btn.clicked.connect(lambda _checked=False, s=state: self._clear_state(s))
            grid.addWidget(label, row, 0)
            grid.addWidget(preview, row, 1)
            grid.addWidget(path_edit, row, 2)
            grid.addWidget(interval_input, row, 3)
            grid.addWidget(open_btn, row, 4)
            grid.addWidget(image_btn, row, 5)
            grid.addWidget(anim_btn, row, 6)
            grid.addWidget(clear_btn, row, 7)
            self._state_path_edits[state] = path_edit
            self._state_preview_labels[state] = preview
            self._state_open_buttons[state] = open_btn
            self._state_interval_inputs[state] = interval_input
            self._set_open_button_enabled(state, False)

        form.addRow(tr("desktop.menu.create_character_sprites"), state_panel)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        cancel_btn = QPushButton(tr("desktop.menu.cancel"), self)
        save_key = (
            "desktop.menu.edit_character_save"
            if self.is_editing
            else "desktop.menu.create_character_save"
        )
        save_btn = QPushButton(tr(save_key), self)
        cancel_btn.clicked.connect(self.reject)
        save_btn.clicked.connect(self._save)
        buttons.addStretch(1)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(save_btn)
        root.addLayout(buttons)

        install_readable_edit_menus(self)

    def _editable_combo(self, parent: QWidget, values: list[str], current: str = "") -> QComboBox:
        combo = QComboBox(parent)
        combo.setEditable(True)
        combo.addItems(values)
        combo.setCurrentText(current)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        combo.lineEdit().editingFinished.connect(self._sync_profile_preview)
        combo.currentTextChanged.connect(lambda _text: self._sync_profile_preview())
        return combo

    def _profile_line(self, parent: QWidget, placeholder: str = "") -> QLineEdit:
        edit = QLineEdit(parent)
        edit.setPlaceholderText(placeholder)
        edit.textChanged.connect(lambda _text: self._sync_profile_preview())
        return edit

    def _profile_text(self, parent: QWidget, placeholder: str = "") -> QPlainTextEdit:
        edit = QPlainTextEdit(parent)
        edit.setPlaceholderText(placeholder)
        edit.setMaximumHeight(76)
        edit.textChanged.connect(self._sync_profile_preview)
        return edit

    def _build_profile_tabs(self, tabs: QTabWidget) -> None:
        basic = QWidget(tabs)
        basic_form = QFormLayout(basic)
        basic_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.age_spin = QSpinBox(basic)
        self.age_spin.setRange(18, 120)
        self.age_spin.setValue(22)
        self.age_spin.valueChanged.connect(lambda _value: self._sync_profile_preview())
        basic_form.addRow("实际年龄", self.age_spin)
        self.birthday_edit = self._profile_line(basic, "12-18，可留空")
        basic_form.addRow("生日", self.birthday_edit)
        self.gender_combo = self._editable_combo(basic, ["女性", "男性", "非二元", "虚拟角色", "自定义"], "女性")
        basic_form.addRow("性别/身份", self.gender_combo)
        self.occupation_combo = self._editable_combo(
            basic,
            ["自学中的程序员", "学生", "程序员", "设计师", "咖啡店店员", "自由职业", "桌面助手", "自定义"],
            "自学中的程序员",
        )
        basic_form.addRow("职业", self.occupation_combo)
        self.life_status_combo = self._editable_combo(
            basic,
            ["独居", "合租", "学校宿舍", "在家办公", "旅行中", "自定义"],
            "独居",
        )
        basic_form.addRow("生活状态", self.life_status_combo)
        self.relationship_combo = self._editable_combo(
            basic,
            ["朋友", "暧昧陪伴者", "恋人", "青梅竹马", "工作伙伴", "家人感", "自定义"],
            "暧昧陪伴者",
        )
        basic_form.addRow("与用户关系", self.relationship_combo)
        self.first_person_combo = self._editable_combo(basic, ["我", "人家", "本小姐", "自定义"], "我")
        basic_form.addRow("第一人称", self.first_person_combo)
        self.user_address_combo = self._editable_combo(basic, ["你", "前辈", "主人", "老板", "自定义"], "你")
        basic_form.addRow("称呼用户", self.user_address_combo)
        tabs.addTab(basic, "基础")

        personality = QWidget(tabs)
        personality_layout = QVBoxLayout(personality)
        personality_layout.setContentsMargins(0, 0, 0, 0)
        personality_layout.setSpacing(8)
        self.mbti_buttons = QButtonGroup(personality)
        self.mbti_buttons.setExclusive(True)
        mbti_grid = QGridLayout()
        mbti_grid.setHorizontalSpacing(8)
        mbti_grid.setVerticalSpacing(8)
        for row, mbti_row in enumerate(MBTI_TYPES):
            for col, mbti in enumerate(mbti_row):
                button = QPushButton(mbti, personality)
                button.setObjectName("MbtiButton")
                button.setCheckable(True)
                button.setToolTip(MBTI_DESCRIPTIONS.get(mbti, ""))
                self.mbti_buttons.addButton(button)
                mbti_grid.addWidget(button, row, col)
                if mbti == "INFP":
                    button.setChecked(True)
        self.mbti_buttons.buttonClicked.connect(lambda _button: self._sync_profile_preview())
        personality_layout.addLayout(mbti_grid)
        self.mbti_desc = QLabel(personality)
        self.mbti_desc.setWordWrap(True)
        self.mbti_desc.setStyleSheet("color: rgba(255,255,255,170);")
        personality_layout.addWidget(self.mbti_desc)
        personality_form = QFormLayout()
        self.mbti_style_combo = self._editable_combo(
            personality,
            ["典型表现", "轻微倾向", "反差型", "自定义"],
            "典型表现",
        )
        personality_form.addRow("表现方式", self.mbti_style_combo)
        self.custom_traits_edit = self._profile_line(personality, "温柔但有点嘴硬, 对亲近的人很黏")
        personality_form.addRow("性格补充", self.custom_traits_edit)
        self.flaws_edit = self._profile_line(personality, "容易想太多, 怕被忽略")
        personality_form.addRow("缺点补充", self.flaws_edit)
        self.contrast_edit = self._profile_line(personality, "平时安静，熟悉后会变得很会撒娇")
        personality_form.addRow("反差点", self.contrast_edit)
        personality_layout.addLayout(personality_form)
        tabs.addTab(personality, "MBTI")

        speech = QWidget(tabs)
        speech_form = QFormLayout(speech)
        speech_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.tone_edit = self._profile_line(speech, "自然, 亲近, 轻柔")
        speech_form.addRow("语气", self.tone_edit)
        self.reply_length_combo = self._editable_combo(speech, ["简短", "适中", "详细", "自定义"], "适中")
        speech_form.addRow("回复长度", self.reply_length_combo)
        self.catchphrases_edit = self._profile_line(speech, "我在呢, 这个我陪你一起弄明白")
        speech_form.addRow("口头禅", self.catchphrases_edit)
        self.relationship_stage_combo = self._editable_combo(
            speech,
            ["初识", "朋友", "暧昧", "恋人", "长期陪伴", "自定义"],
            "暧昧",
        )
        speech_form.addRow("关系阶段", self.relationship_stage_combo)
        self.trust_triggers_edit = self._profile_line(speech, "用户认真听她说话, 用户记得她的小习惯")
        speech_form.addRow("信任触发", self.trust_triggers_edit)
        self.sadness_triggers_edit = self._profile_line(speech, "被忽略, 用户情绪低落")
        speech_form.addRow("失落触发", self.sadness_triggers_edit)
        tabs.addTab(speech, "说话/关系")

        preferences = QWidget(tabs)
        pref_form = QFormLayout(preferences)
        pref_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.likes_edit = self._profile_line(preferences, "雪天, 热可可, 写代码, 夜聊")
        pref_form.addRow("喜欢", self.likes_edit)
        self.dislikes_edit = self._profile_line(preferences, "被敷衍, 太吵, 被催促")
        pref_form.addRow("讨厌", self.dislikes_edit)
        self.hobbies_edit = self._profile_line(preferences, "学 Python, 整理桌面, 看雪景照片")
        pref_form.addRow("爱好", self.hobbies_edit)
        self.boundary_combo = self._editable_combo(
            preferences,
            ["普通陪伴", "轻度亲密", "恋人感但不露骨", "自定义"],
            "轻度亲密",
        )
        pref_form.addRow("亲密边界", self.boundary_combo)
        self.boundary_notes_edit = self._profile_text(
            preferences,
            "角色必须为成年人；温柔亲密但不露骨；不鼓励用户脱离现实生活。",
        )
        pref_form.addRow("边界补充", self.boundary_notes_edit)
        tabs.addTab(preferences, "喜好/边界")

        manual = QWidget(tabs)
        manual_layout = QVBoxLayout(manual)
        manual_layout.setContentsMargins(0, 0, 0, 0)
        self.setting_edit = QPlainTextEdit(manual)
        self.setting_edit.setPlaceholderText(tr("desktop.menu.create_character_setting_placeholder"))
        self.setting_edit.setReadOnly(self._editing_system_character)
        self.setting_edit.textChanged.connect(self._on_setting_text_changed)
        manual_layout.addWidget(QLabel("AI 看到的角色设定文本", manual))
        manual_layout.addWidget(self.setting_edit, stretch=2)
        regen = QPushButton("根据表单重新生成设定文本", manual)
        regen.clicked.connect(self._apply_profile_setting)
        manual_layout.addWidget(regen)
        self.visual_edit = QPlainTextEdit(manual)
        self.visual_edit.setPlaceholderText(tr("desktop.menu.create_character_visual_placeholder"))
        self.visual_edit.setReadOnly(self._editing_system_character)
        manual_layout.addWidget(QLabel(tr("desktop.menu.create_character_visual"), manual))
        manual_layout.addWidget(self.visual_edit, stretch=1)
        tabs.addTab(manual, "预览/手动")

        self._sync_profile_preview()

    def _on_setting_text_changed(self) -> None:
        if self._updating_setting_text:
            return

    def _choose_image(self, state: str) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("desktop.menu.choose_character_image_title", state=state),
            str(Path.home()),
            IMAGE_FILTER,
        )
        if path:
            self._set_state_files(state, [Path(path)])

    def _csv_values(self, text: str) -> list[str]:
        return [part.strip() for part in re.split(r"[,，、\n]+", text or "") if part.strip()]

    def _csv_text(self, values: object) -> str:
        if isinstance(values, list):
            return ", ".join(str(v).strip() for v in values if str(v).strip())
        return str(values or "").strip()

    def _selected_mbti(self) -> str:
        button = self.mbti_buttons.checkedButton()
        return button.text().strip() if button else "INFP"

    def _set_selected_mbti(self, value: str) -> None:
        target = str(value or "INFP").upper()
        for button in self.mbti_buttons.buttons():
            if button.text().strip().upper() == target:
                button.setChecked(True)
                break

    def _character_profile(self) -> dict[str, object]:
        return {
            "identity": {
                "age": int(self.age_spin.value()),
                "birthday": self.birthday_edit.text().strip(),
                "gender": self.gender_combo.currentText().strip(),
                "occupation": self.occupation_combo.currentText().strip(),
                "life_status": self.life_status_combo.currentText().strip(),
                "relationship_to_user": self.relationship_combo.currentText().strip(),
                "first_person": self.first_person_combo.currentText().strip(),
                "user_address": self.user_address_combo.currentText().strip(),
            },
            "personality": {
                "mbti": self._selected_mbti(),
                "mbti_style": self.mbti_style_combo.currentText().strip(),
                "custom_traits": self._csv_values(self.custom_traits_edit.text()),
                "flaws": self._csv_values(self.flaws_edit.text()),
                "contrast": self.contrast_edit.text().strip(),
            },
            "speech": {
                "tone": self._csv_values(self.tone_edit.text()),
                "reply_length": self.reply_length_combo.currentText().strip(),
                "catchphrases": self._csv_values(self.catchphrases_edit.text()),
            },
            "relationship": {
                "stage": self.relationship_stage_combo.currentText().strip(),
                "trust_triggers": self._csv_values(self.trust_triggers_edit.text()),
                "sadness_triggers": self._csv_values(self.sadness_triggers_edit.text()),
            },
            "preferences": {
                "likes": self._csv_values(self.likes_edit.text()),
                "dislikes": self._csv_values(self.dislikes_edit.text()),
                "hobbies": self._csv_values(self.hobbies_edit.text()),
            },
            "boundaries": {
                "adult": True,
                "intimacy_level": self.boundary_combo.currentText().strip(),
                "notes": self.boundary_notes_edit.toPlainText().strip(),
            },
        }

    def _fill_profile(self, profile: dict[str, object]) -> None:
        identity = profile.get("identity") if isinstance(profile.get("identity"), dict) else {}
        personality = profile.get("personality") if isinstance(profile.get("personality"), dict) else {}
        speech = profile.get("speech") if isinstance(profile.get("speech"), dict) else {}
        relationship = profile.get("relationship") if isinstance(profile.get("relationship"), dict) else {}
        preferences = profile.get("preferences") if isinstance(profile.get("preferences"), dict) else {}
        boundaries = profile.get("boundaries") if isinstance(profile.get("boundaries"), dict) else {}
        try:
            self.age_spin.setValue(max(18, int(identity.get("age") or 22)))
        except (TypeError, ValueError):
            self.age_spin.setValue(22)
        self.birthday_edit.setText(str(identity.get("birthday") or ""))
        self.gender_combo.setCurrentText(str(identity.get("gender") or "女性"))
        self.occupation_combo.setCurrentText(str(identity.get("occupation") or "自学中的程序员"))
        self.life_status_combo.setCurrentText(str(identity.get("life_status") or "独居"))
        self.relationship_combo.setCurrentText(str(identity.get("relationship_to_user") or "暧昧陪伴者"))
        self.first_person_combo.setCurrentText(str(identity.get("first_person") or "我"))
        self.user_address_combo.setCurrentText(str(identity.get("user_address") or "你"))
        self._set_selected_mbti(str(personality.get("mbti") or "INFP"))
        self.mbti_style_combo.setCurrentText(str(personality.get("mbti_style") or "典型表现"))
        self.custom_traits_edit.setText(self._csv_text(personality.get("custom_traits") or []))
        self.flaws_edit.setText(self._csv_text(personality.get("flaws") or []))
        self.contrast_edit.setText(str(personality.get("contrast") or ""))
        self.tone_edit.setText(self._csv_text(speech.get("tone") or []))
        self.reply_length_combo.setCurrentText(str(speech.get("reply_length") or "适中"))
        self.catchphrases_edit.setText(self._csv_text(speech.get("catchphrases") or []))
        self.relationship_stage_combo.setCurrentText(str(relationship.get("stage") or "暧昧"))
        self.trust_triggers_edit.setText(self._csv_text(relationship.get("trust_triggers") or []))
        self.sadness_triggers_edit.setText(self._csv_text(relationship.get("sadness_triggers") or []))
        self.likes_edit.setText(self._csv_text(preferences.get("likes") or []))
        self.dislikes_edit.setText(self._csv_text(preferences.get("dislikes") or []))
        self.hobbies_edit.setText(self._csv_text(preferences.get("hobbies") or []))
        self.boundary_combo.setCurrentText(str(boundaries.get("intimacy_level") or "轻度亲密"))
        self.boundary_notes_edit.setPlainText(str(boundaries.get("notes") or ""))
        self._sync_profile_preview()

    def _generated_setting_text(self) -> str:
        return build_character_setting_from_profile(
            self.character_name or "这个角色",
            self._character_profile(),
        )

    def _sync_profile_preview(self) -> None:
        if not hasattr(self, "setting_edit"):
            return
        mbti = self._selected_mbti()
        self.mbti_desc.setText(MBTI_DESCRIPTIONS.get(mbti, ""))
        current = self.setting_edit.toPlainText().strip()
        generated = self._generated_setting_text()
        if not current or current == self._last_generated_setting:
            self._updating_setting_text = True
            try:
                self.setting_edit.setPlainText(generated)
            finally:
                self._updating_setting_text = False
            self._last_generated_setting = generated

    def _apply_profile_setting(self) -> None:
        generated = self._generated_setting_text()
        self._updating_setting_text = True
        try:
            self.setting_edit.setPlainText(generated)
        finally:
            self._updating_setting_text = False
        self._last_generated_setting = generated

    def _choose_animation(self, state: str) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            tr("desktop.menu.choose_character_animation_title", state=state),
            str(Path.home()),
            ANIMATION_FILTER,
        )
        if paths:
            self._set_state_files(state, [Path(p) for p in sorted(paths)])

    def _clear_state(self, state: str) -> None:
        self._state_files.pop(state, None)
        self._cleared_states.add(state)
        self._state_path_edits[state].clear()
        self._state_path_edits[state].setPlaceholderText(tr("desktop.menu.create_character_no_asset"))
        self._state_preview_labels[state].clear()
        self._set_open_button_enabled(state, False)

    def _set_state_files(self, state: str, paths: list[Path]) -> None:
        clean = [p.expanduser() for p in paths if p.expanduser().is_file()]
        if not clean:
            return
        video_paths = [p for p in clean if self._is_video_file(p)]
        if video_paths:
            if len(clean) != 1:
                QMessageBox.warning(
                    self,
                    tr("desktop.menu.create_character_failed_title"),
                    tr("desktop.menu.err_character_video_mixed_assets"),
                )
                return
            interval = self._video_frame_interval_ms(video_paths[0])
            if interval:
                self._state_interval_inputs[state].setValue(interval)
        self._state_files[state] = clean
        self._cleared_states.discard(state)
        if len(video_paths) == 1:
            label = tr(
                "desktop.menu.create_character_video_asset",
                name=video_paths[0].name,
            )
        elif len(clean) == 1:
            label = clean[0].name
        else:
            label = tr("desktop.menu.create_character_frame_count", count=len(clean))
        self._state_path_edits[state].setText(
            tr("desktop.menu.create_character_imported_asset", detail=label)
        )
        if len(video_paths) == 1:
            self._set_preview_from_video(state, video_paths[0])
        else:
            self._set_preview_from_path(state, clean[0])
        self._set_open_button_enabled(state, True)

    def _save(self) -> None:
        try:
            name = self.character_name
            if not name:
                raise ValueError(tr("desktop.menu.err_character_name_required"))
            existing = self._config_manager.get_character_by_name(name)
            if existing is not None and (
                not self.is_editing or name != self._original_character_name
            ):
                raise ValueError(tr("desktop.menu.err_character_name_exists", name=name))
            setting = self.setting_edit.toPlainText().strip()
            if not setting:
                raise ValueError(tr("desktop.menu.err_character_setting_required"))
            if self._editing_system_character and name != SYSTEM_CHARACTER_NAME:
                raise ValueError(tr("desktop.menu.err_system_character_protected"))
            if not self.is_editing and not self._state_files:
                raise ValueError(tr("desktop.menu.err_character_asset_required"))

            if self.is_editing:
                self._update_character(name, setting)
            else:
                character = self._create_character(name, setting)
                self._config_manager.config.characters.append(character)
                self._ensure_memory_file(name)
            self._config_manager.save_characters_config()
        except Exception as exc:
            title_key = (
                "desktop.menu.edit_character_failed_title"
                if self.is_editing
                else "desktop.menu.create_character_failed_title"
            )
            QMessageBox.warning(self, tr(title_key), str(exc))
            return
        self.accept()

    def _load_character_for_edit(self) -> None:
        character = self._edit_character
        if character is None:
            return
        self.name_edit.setText(str(character.name or ""))
        self.setting_edit.setPlainText(str(character.character_setting or ""))
        self._last_generated_setting = ""
        self.visual_edit.setPlainText(str(character.visual_identity or ""))
        profile = getattr(character, "character_profile", None)
        self._fill_profile(normalize_character_profile(character.name, profile))
        for sprite in list(character.sprites or []):
            data = self._sprite_to_dict(sprite)
            state = str(data.get("state_name") or "").strip()
            if state in CORE_EMOTIONS and state not in self._existing_state_sprites:
                self._existing_state_sprites[state] = data
                self._state_interval_inputs[state].setValue(
                    self._frame_interval_from_sprite(data)
                )
                self._state_path_edits[state].setText(self._asset_label(data))
                preview_path = self._preview_path_from_sprite(data)
                if preview_path:
                    self._set_preview_from_path(state, preview_path)
                    self._set_open_button_enabled(state, True)
            else:
                self._existing_extra_sprites.append(data)

    def _update_character(self, name: str, setting: str) -> None:
        character = self._edit_character
        if character is None:
            raise ValueError(tr("desktop.menu.err_current_character_missing", name=self.character_name))
        prefix = str(character.sprite_prefix or "").strip() or self._unique_sprite_prefix(character.name)
        character.sprite_prefix = prefix
        asset_root = get_app_paths().characters_dir / prefix
        asset_root.mkdir(parents=True, exist_ok=True)

        sprites: list[dict[str, object]] = []
        first_path = ""
        for state in CORE_EMOTIONS:
            if state in self._cleared_states:
                continue
            imported = self._state_files.get(state)
            if imported:
                copied = self._copy_state_files(asset_root, prefix, state, imported)
                if not copied:
                    continue
                sprite = self._sprite_dict_for_state(state, copied)
            else:
                sprite = self._existing_state_sprites.get(state)
            if not sprite:
                continue
            sprite = dict(sprite)
            sprite["frame_interval_ms"] = self._state_interval_value(state)
            sprite["fps"] = 0.0
            if not first_path:
                first_path = str(sprite.get("path") or "")
            sprites.append(sprite)

        for sprite in self._existing_extra_sprites:
            if not first_path:
                first_path = str(sprite.get("path") or "")
            sprites.append(dict(sprite))

        if not sprites:
            raise ValueError(tr("desktop.menu.err_character_asset_required"))

        if not self._editing_system_character:
            character.name = name
            character.character_setting = setting
            character.visual_identity = self.visual_edit.toPlainText().strip()
            character.character_profile = self._character_profile()
        character.visual_reference_image = first_path
        character.sprites = sprites
        character.emotion_tags = self._emotion_tags(sprites)

    def _create_character(self, name: str, setting: str) -> Character:
        prefix = self._unique_sprite_prefix(name)
        asset_root = get_app_paths().characters_dir / prefix
        asset_root.mkdir(parents=True, exist_ok=True)

        sprites: list[dict[str, object]] = []
        first_path = ""
        for state in CORE_EMOTIONS:
            paths = self._state_files.get(state)
            if not paths:
                continue
            copied = self._copy_state_files(asset_root, prefix, state, paths)
            if not copied:
                continue
            if not first_path:
                first_path = copied[0]
            sprites.append(self._sprite_dict_for_state(state, copied))

        if not sprites:
            raise ValueError(tr("desktop.menu.err_character_asset_required"))

        visual_identity = self.visual_edit.toPlainText().strip()
        scale = float(getattr(self._config_manager.config.system_config, "default_sprite_scale", 0.72) or 0.72)
        return Character(
            name=name,
            color="#84C2D5",
            sprite_prefix=prefix,
            sprites=sprites,
            character_profile=self._character_profile(),
            character_setting=setting,
            visual_reference_image=first_path,
            visual_identity=visual_identity,
            sprite_scale=scale,
            emotion_tags=self._emotion_tags(sprites),
            speech_speed=1.0,
            speech_volume=1.0,
            pronunciation_map={},
        )

    def _copy_state_files(
        self,
        asset_root: Path,
        prefix: str,
        state: str,
        paths: list[Path],
    ) -> list[str]:
        copied: list[str] = []
        if len(paths) == 1 and self._is_video_file(paths[0]):
            return self._extract_video_frames(asset_root, prefix, state, paths[0])
        if len(paths) == 1:
            src = paths[0]
            ext = src.suffix.lower() or ".png"
            dst = asset_root / f"{prefix}_{state}{ext}"
            self._copy2_if_needed(src, dst)
            return [dst.as_posix()]

        state_dir = asset_root / "animations" / state
        state_dir.mkdir(parents=True, exist_ok=True)
        for idx, src in enumerate(paths, start=1):
            ext = src.suffix.lower() or ".png"
            dst = state_dir / f"frame_{idx:02d}{ext}"
            self._copy2_if_needed(src, dst)
            copied.append(dst.as_posix())
        return copied

    def _copy2_if_needed(self, src: Path, dst: Path) -> None:
        src_resolved = src.expanduser().resolve()
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() and dst.resolve() == src_resolved:
            return
        shutil.copy2(src_resolved, dst)

    def _extract_video_frames(
        self,
        asset_root: Path,
        prefix: str,
        state: str,
        video_path: Path,
    ) -> list[str]:
        try:
            import cv2
        except ImportError as exc:
            raise ValueError(tr("desktop.menu.err_character_video_requires_opencv")) from exc

        src = video_path.expanduser()
        cap = cv2.VideoCapture(str(src))
        if not cap.isOpened():
            raise ValueError(tr("desktop.menu.err_character_video_open_failed", path=str(src)))

        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        step = max(1, (total + MAX_VIDEO_FRAMES - 1) // MAX_VIDEO_FRAMES) if total else 1
        state_dir = asset_root / "animations" / state
        if state_dir.exists():
            shutil.rmtree(state_dir, ignore_errors=True)
        state_dir.mkdir(parents=True, exist_ok=True)

        copied: list[str] = []
        frame_index = 0
        saved_index = 1
        try:
            while len(copied) < MAX_VIDEO_FRAMES:
                ok, frame = cap.read()
                if not ok:
                    break
                if frame_index % step != 0:
                    frame_index += 1
                    continue
                dst = state_dir / f"frame_{saved_index:03d}.png"
                if not cv2.imwrite(str(dst), frame):
                    raise ValueError(tr("desktop.menu.err_character_video_frame_write_failed"))
                copied.append(dst.as_posix())
                saved_index += 1
                frame_index += 1
        finally:
            cap.release()

        if len(copied) < 2:
            raise ValueError(tr("desktop.menu.err_character_video_no_frames", path=str(src)))
        return copied

    def _sprite_dict_for_state(self, state: str, paths: list[str]) -> dict[str, object]:
        sprite: dict[str, object] = {
            "path": paths[0],
            "state_name": state,
            "state_group": STATE_GROUP_CORE_EMOTION,
            "source_state": state,
            "frame_interval_ms": self._state_interval_value(state),
        }
        if len(paths) > 1:
            sprite["frames"] = paths
            sprite["frame_count"] = len(paths)
        return sprite

    def _emotion_tags(self, sprites: list[dict[str, object]]) -> str:
        lines = [
            "状态分组：核心情绪 core_emotion、系统可选情绪 system_optional_emotion、用户自定义 custom、鼠标事件 mouse_event。",
            "核心情绪标准名：neutral/happy/thinking/surprised/sad/angry；这些状态允许缺少。",
            "",
        ]
        for idx, sprite in enumerate(sprites, start=1):
            state = str(sprite.get("state_name") or "")
            tags = STATE_TAGS.get(state, state)
            lines.append(f"立绘 {idx}：{state}；分组：{STATE_GROUP_CORE_EMOTION}；{tags}")
        return "\n".join(lines).strip()

    def _sprite_to_dict(self, sprite: Sprite | dict) -> dict[str, object]:
        if isinstance(sprite, Sprite):
            return sprite.model_dump(mode="json")
        return dict(sprite or {})

    def _state_interval_value(self, state: str) -> int:
        widget = self._state_interval_inputs.get(state)
        if widget is None:
            return 120
        return max(16, min(3000, int(widget.value())))

    def _frame_interval_from_sprite(self, sprite: dict[str, object]) -> int:
        try:
            fps = float(sprite.get("fps") or 0)
            if fps > 0:
                return max(16, min(3000, round(1000 / fps)))
        except (TypeError, ValueError, ZeroDivisionError):
            pass
        try:
            value = int(sprite.get("frame_interval_ms") or 120)
        except (TypeError, ValueError):
            value = 120
        return max(16, min(3000, value))

    def _asset_label(self, sprite: dict[str, object]) -> str:
        frames = sprite.get("frames") or []
        if isinstance(frames, list) and len(frames) > 1:
            detail = tr("desktop.menu.create_character_frame_count", count=len(frames))
            return tr("desktop.menu.create_character_imported_asset", detail=detail)
        path = str(sprite.get("path") or "")
        if path:
            return tr("desktop.menu.create_character_imported_asset", detail=Path(path).name)
        return tr("desktop.menu.create_character_no_asset")

    def _preview_path_from_sprite(self, sprite: dict[str, object]) -> Path | None:
        frames = sprite.get("frames") or []
        if isinstance(frames, list) and frames:
            first = Path(str(frames[0] or ""))
            if first.is_file():
                return first
        path = Path(str(sprite.get("path") or ""))
        return path if path.is_file() else None

    def _is_video_file(self, path: Path) -> bool:
        return path.suffix.lower() in VIDEO_SUFFIXES

    def _video_frame_interval_ms(self, path: Path) -> int:
        try:
            import cv2
        except ImportError:
            return 120
        cap = cv2.VideoCapture(str(path.expanduser()))
        if not cap.isOpened():
            return 120
        try:
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        finally:
            cap.release()
        if fps <= 0:
            return 120
        step = max(1, (total + MAX_VIDEO_FRAMES - 1) // MAX_VIDEO_FRAMES) if total else 1
        return max(16, min(3000, round(1000 / fps * step)))

    def _set_preview_from_video(self, state: str, path: Path) -> None:
        label = self._state_preview_labels.get(state)
        if label is None:
            return
        try:
            import cv2
        except ImportError:
            label.clear()
            return
        cap = cv2.VideoCapture(str(path.expanduser()))
        if not cap.isOpened():
            label.clear()
            return
        try:
            ok, frame = cap.read()
        finally:
            cap.release()
        if not ok or frame is None:
            label.clear()
            return
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width, channels = rgb.shape
        image = QImage(
            rgb.data,
            width,
            height,
            channels * width,
            QImage.Format.Format_RGB888,
        ).copy()
        label.setPixmap(
            QPixmap.fromImage(image).scaled(
                44,
                44,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _open_state_asset(self, state: str) -> None:
        paths = self._state_files.get(state)
        if paths:
            target = paths[0].parent if len(paths) > 1 else paths[0]
            self._open_path(target)
            return
        sprite = self._existing_state_sprites.get(state)
        if not sprite:
            return
        frames = sprite.get("frames") or []
        if isinstance(frames, list) and frames:
            target = Path(str(frames[0] or "")).parent
        else:
            target = Path(str(sprite.get("path") or ""))
        self._open_path(target)

    def _open_path(self, path: Path) -> None:
        if not path:
            return
        target = path.expanduser()
        if not target.exists():
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.resolve())))

    def _set_preview_from_path(self, state: str, path: Path) -> None:
        label = self._state_preview_labels.get(state)
        if label is None:
            return
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            label.clear()
            return
        label.setPixmap(
            pixmap.scaled(
                44,
                44,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _set_open_button_enabled(self, state: str, enabled: bool) -> None:
        button = self._state_open_buttons.get(state)
        if button is not None:
            button.setEnabled(enabled)

    def _unique_sprite_prefix(self, name: str) -> str:
        slug = re.sub(r"[^0-9A-Za-z._-]+", "_", name.strip()).strip("._-").lower()
        if not slug:
            slug = f"character_{uuid.uuid4().hex[:8]}"
        existing_prefixes = {
            str(getattr(c, "sprite_prefix", "") or "").strip()
            for c in self._config_manager.config.characters
        }
        candidate = slug
        index = 2
        while candidate in existing_prefixes or (get_app_paths().characters_dir / candidate).exists():
            candidate = f"{slug}_{index}"
            index += 1
        return candidate

    def _ensure_memory_file(self, name: str) -> None:
        path = get_app_paths().memory_dir / "characters" / f"{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(f"# {name} 长期记忆\n\n", encoding="utf-8")
