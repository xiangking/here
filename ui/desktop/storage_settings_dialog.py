"""Storage location settings for character memory and character assets."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from infrastructure.paths import (
    default_character_assets_dir,
    default_character_memory_dir,
    get_app_paths,
    load_storage_paths,
    resolve_storage_path,
    save_storage_paths,
)
from services.config.config_manager import ConfigManager
from services.i18n import tr
from ui.desktop.edit_context_menu import install_readable_edit_menus


PATH_FIELDS = (
    "path",
    "voice_path",
    "spritesheet_path",
    "visual_reference_image",
)


def migrate_storage_locations(
    *,
    old_memory_dir: str | Path,
    old_assets_dir: str | Path,
    new_memory_dir: str | Path,
    new_assets_dir: str | Path,
    config_manager: ConfigManager,
    copy_memory: bool = True,
    copy_assets: bool = True,
) -> bool:
    """Copy existing storage data and rewrite character asset paths if needed."""
    rewritten = False
    if copy_memory:
        _copy_directory_contents(Path(old_memory_dir), Path(new_memory_dir))
    if copy_assets:
        _copy_directory_contents(Path(old_assets_dir), Path(new_assets_dir))
        rewritten = rewrite_character_asset_paths(
            old_assets_dir,
            new_assets_dir,
            config_manager=config_manager,
        )
    return rewritten


def rewrite_character_asset_paths(
    old_assets_dir: str | Path,
    new_assets_dir: str | Path,
    *,
    config_manager: ConfigManager,
) -> bool:
    old_root = Path(old_assets_dir).expanduser()
    new_root = Path(new_assets_dir).expanduser()
    if old_root == new_root:
        return False
    changed = False
    for character in list(config_manager.config.characters or []):
        value = _replace_prefixed_path(
            getattr(character, "visual_reference_image", ""),
            old_root,
            new_root,
        )
        if value is not None:
            character.visual_reference_image = value
            changed = True
        for sprite in list(getattr(character, "sprites", []) or []):
            if _rewrite_sprite_paths(sprite, old_root, new_root):
                changed = True
    if changed:
        config_manager.save_characters_config()
    return changed


def _copy_directory_contents(source: Path, target: Path) -> None:
    if source == target or not source.exists():
        target.mkdir(parents=True, exist_ok=True)
        return
    target.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        dest = target / item.name
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True)
        elif item.is_file():
            shutil.copy2(item, dest)


def _rewrite_sprite_paths(sprite: Any, old_root: Path, new_root: Path) -> bool:
    changed = False
    for field in PATH_FIELDS:
        current = _sprite_get(sprite, field)
        replacement = _replace_prefixed_path(current, old_root, new_root)
        if replacement is not None:
            _sprite_set(sprite, field, replacement)
            changed = True
    frames = _sprite_get(sprite, "frames")
    if isinstance(frames, list):
        new_frames: list[Any] = []
        frame_changed = False
        for frame in frames:
            replacement = _replace_prefixed_path(frame, old_root, new_root)
            if replacement is not None:
                new_frames.append(replacement)
                frame_changed = True
            else:
                new_frames.append(frame)
        if frame_changed:
            _sprite_set(sprite, "frames", new_frames)
            changed = True
    return changed


def _sprite_get(sprite: Any, field: str) -> Any:
    if isinstance(sprite, dict):
        return sprite.get(field)
    return getattr(sprite, field, None)


def _sprite_set(sprite: Any, field: str, value: Any) -> None:
    if isinstance(sprite, dict):
        sprite[field] = value
    elif hasattr(sprite, field):
        setattr(sprite, field, value)


def _replace_prefixed_path(value: Any, old_root: Path, new_root: Path) -> str | None:
    text = str(value or "").strip()
    if not text or _looks_like_url(text):
        return None
    path = Path(text).expanduser()
    try:
        rel = path.relative_to(old_root)
    except ValueError:
        return None
    return (new_root / rel).as_posix()


def _looks_like_url(value: str) -> bool:
    lower = value.lower()
    return lower.startswith(("http://", "https://", "data:"))


def _is_strict_child(path: Path, parent: Path) -> bool:
    path_resolved = path.expanduser().resolve(strict=False)
    parent_resolved = parent.expanduser().resolve(strict=False)
    if path_resolved == parent_resolved:
        return False
    try:
        path_resolved.relative_to(parent_resolved)
    except ValueError:
        return False
    return True


class StorageSettingsDialog(QDialog):
    def __init__(
        self,
        parent=None,
        *,
        config_manager: ConfigManager | None = None,
        notify_callback: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._config_manager = config_manager or ConfigManager()
        self._notify_callback = notify_callback
        self.setWindowTitle(tr("desktop.settings_dialog.storage_title"))
        self.setModal(True)
        self.resize(660, 360)
        self._build_ui()
        self._load_from_config()

    def _build_ui(self) -> None:
        self.setStyleSheet(
            """
            QDialog {
                background-color: rgba(24, 26, 32, 238);
                color: white;
            }
            QLabel {
                color: rgba(255, 255, 255, 220);
                font-size: 13px;
            }
            QLabel#StorageHintLabel,
            QLabel#StorageDefaultLabel {
                color: rgba(255, 255, 255, 168);
            }
            QLineEdit {
                color: white;
                background-color: rgba(44, 47, 57, 235);
                border: 1px solid rgba(255, 255, 255, 72);
                border-radius: 6px;
                padding: 7px;
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
            QPushButton#StorageSecondaryButton {
                background-color: rgba(255, 255, 255, 32);
                color: rgba(255, 255, 255, 220);
                border: 1px solid rgba(255, 255, 255, 52);
            }
            QPushButton#StorageSecondaryButton:hover {
                background-color: rgba(255, 255, 255, 50);
            }
            """
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        title = QLabel(tr("desktop.settings_dialog.storage_heading"), self)
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        root.addWidget(title)

        hint = QLabel(tr("desktop.settings_dialog.storage_hint"), self)
        hint.setObjectName("StorageHintLabel")
        hint.setWordWrap(True)
        root.addWidget(hint)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        root.addLayout(form)

        self.memory_edit = QLineEdit(self)
        self.assets_edit = QLineEdit(self)
        form.addRow(
            tr("desktop.settings_dialog.character_memory_dir"),
            self._path_row(
                self.memory_edit,
                lambda: self._choose_dir(
                    self.memory_edit,
                    tr("desktop.settings_dialog.choose_memory_dir_title"),
                ),
                lambda: self.memory_edit.clear(),
            ),
        )
        form.addRow(
            tr("desktop.settings_dialog.character_assets_dir"),
            self._path_row(
                self.assets_edit,
                lambda: self._choose_dir(
                    self.assets_edit,
                    tr("desktop.settings_dialog.choose_assets_dir_title"),
                ),
                lambda: self.assets_edit.clear(),
            ),
        )

        default_paths = QLabel(
            tr(
                "desktop.settings_dialog.storage_default_path",
                memory=str(default_character_memory_dir()),
                assets=str(default_character_assets_dir()),
            ),
            self,
        )
        default_paths.setObjectName("StorageDefaultLabel")
        default_paths.setWordWrap(True)
        root.addWidget(default_paths)

        self.copy_memory_check = QCheckBox(
            tr("desktop.settings_dialog.copy_existing_memory"),
            self,
        )
        self.copy_memory_check.setChecked(True)
        self.copy_assets_check = QCheckBox(
            tr("desktop.settings_dialog.copy_existing_assets"),
            self,
        )
        self.copy_assets_check.setChecked(True)
        root.addWidget(self.copy_memory_check)
        root.addWidget(self.copy_assets_check)

        buttons = QHBoxLayout()
        cancel_btn = QPushButton(tr("desktop.settings_dialog.cancel"), self)
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton(tr("desktop.settings_dialog.save_storage_locations"), self)
        save_btn.clicked.connect(self._save_and_accept)
        buttons.addStretch(1)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(save_btn)
        root.addLayout(buttons)
        install_readable_edit_menus(self)

    def _path_row(
        self,
        edit: QLineEdit,
        choose_callback: Callable[[], None],
        reset_callback: Callable[[], None],
    ) -> QWidget:
        row = QWidget(self)
        row.setObjectName("StoragePathRow")
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        choose_btn = QPushButton(tr("desktop.settings_dialog.browse"), row)
        choose_btn.setObjectName("StorageSecondaryButton")
        reset_btn = QPushButton(tr("desktop.settings_dialog.reset_default"), row)
        reset_btn.setObjectName("StorageSecondaryButton")
        choose_btn.clicked.connect(choose_callback)
        reset_btn.clicked.connect(reset_callback)
        layout.addWidget(edit, 1)
        layout.addWidget(choose_btn)
        layout.addWidget(reset_btn)
        return row

    def _load_from_config(self) -> None:
        config = load_storage_paths()
        self.memory_edit.setText(config.character_memory_dir)
        self.assets_edit.setText(config.character_assets_dir)

    def _choose_dir(self, edit: QLineEdit, title: str) -> None:
        current = edit.text().strip()
        if current:
            start_dir = str(resolve_storage_path(current, fallback=Path.home()))
        else:
            start_dir = str(Path.home())
        path = QFileDialog.getExistingDirectory(self, title, start_dir)
        if path:
            edit.setText(path)

    def _save_and_accept(self) -> None:
        old_paths = get_app_paths()
        old_memory_dir = old_paths.memory_dir
        old_assets_dir = old_paths.characters_dir
        old_storage_config = load_storage_paths(old_paths.root)
        memory_raw = self.memory_edit.text().strip()
        assets_raw = self.assets_edit.text().strip()
        saved_new_config = False
        try:
            new_memory = resolve_storage_path(
                memory_raw,
                fallback=default_character_memory_dir(old_paths.root),
            )
            new_assets = resolve_storage_path(
                assets_raw,
                fallback=default_character_assets_dir(old_paths.root),
            )
            if self.copy_memory_check.isChecked() and _is_strict_child(new_memory, old_memory_dir):
                raise ValueError(
                    tr(
                        "desktop.settings_dialog.storage_target_inside_source",
                        source=str(old_memory_dir),
                        target=str(new_memory),
                    )
                )
            if self.copy_assets_check.isChecked() and _is_strict_child(new_assets, old_assets_dir):
                raise ValueError(
                    tr(
                        "desktop.settings_dialog.storage_target_inside_source",
                        source=str(old_assets_dir),
                        target=str(new_assets),
                    )
                )
            new_memory.mkdir(parents=True, exist_ok=True)
            new_assets.mkdir(parents=True, exist_ok=True)
            save_storage_paths(
                character_memory_dir=memory_raw,
                character_assets_dir=assets_raw,
                root=old_paths.root,
            )
            saved_new_config = True
            new_paths = get_app_paths()
            migrate_storage_locations(
                old_memory_dir=old_memory_dir,
                old_assets_dir=old_assets_dir,
                new_memory_dir=new_paths.memory_dir,
                new_assets_dir=new_paths.characters_dir,
                config_manager=self._config_manager,
                copy_memory=bool(self.copy_memory_check.isChecked()),
                copy_assets=bool(self.copy_assets_check.isChecked()),
            )
            self._config_manager.reload()
        except Exception as exc:
            if saved_new_config:
                save_storage_paths(
                    character_memory_dir=old_storage_config.character_memory_dir,
                    character_assets_dir=old_storage_config.character_assets_dir,
                    root=old_paths.root,
                )
                try:
                    self._config_manager.reload()
                except Exception:
                    pass
            QMessageBox.warning(
                self,
                tr("desktop.settings_dialog.storage_migration_failed_title"),
                tr("desktop.settings_dialog.storage_saved_migration_failed", error=str(exc)),
            )
            return
        if callable(self._notify_callback):
            self._notify_callback(tr("desktop.settings_dialog.storage_saved_restart"))
        self.accept()
