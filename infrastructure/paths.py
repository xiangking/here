"""Centralized filesystem layout for here."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

APP_NAME = "here"
APP_ID = "here"
ENV_APP_HOME = "HERE_APP_HOME"
STORAGE_PATHS_CONFIG_FILE = "storage_paths.yaml"
DEFAULT_CHARACTER_ASSET_PREFIXES = (
    "defaults/characters/",
    "./defaults/characters/",
)
PROJECT_RELATIVE_PREFIXES = (
    "assets/",
    "./assets/",
    "defaults/",
    "./defaults/",
)


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def defaults_dir() -> Path:
    return project_root() / "defaults"


def _platform_app_home() -> Path:
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / APP_NAME
        if os.name == "nt":
            return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
        return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_ID
    return project_root() / ".local" / APP_ID


def app_home() -> Path:
    override = os.environ.get(ENV_APP_HOME, "").strip()
    return Path(override).expanduser() if override else _platform_app_home()


@dataclass(frozen=True)
class StoragePathConfig:
    character_memory_dir: str = ""
    character_assets_dir: str = ""


def default_character_memory_dir(root: str | Path | None = None) -> Path:
    base = Path(root).expanduser() if root is not None else app_home()
    return base / "memory"


def default_character_assets_dir(root: str | Path | None = None) -> Path:
    base = Path(root).expanduser() if root is not None else app_home()
    return base / "characters"


def storage_paths_config_path(root: str | Path | None = None) -> Path:
    base = Path(root).expanduser() if root is not None else app_home()
    return base / "config" / STORAGE_PATHS_CONFIG_FILE


def load_storage_paths(root: str | Path | None = None) -> StoragePathConfig:
    path = storage_paths_config_path(root)
    if not path.is_file():
        return StoragePathConfig()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    return StoragePathConfig(
        character_memory_dir=str(data.get("character_memory_dir") or "").strip(),
        character_assets_dir=str(data.get("character_assets_dir") or "").strip(),
    )


def resolve_storage_path(
    value: str | Path | None,
    *,
    root: str | Path | None = None,
    fallback: str | Path,
) -> Path:
    raw = str(value or "").strip()
    if not raw:
        return Path(fallback).expanduser()
    path = Path(raw).expanduser()
    if not path.is_absolute():
        base = Path(root).expanduser() if root is not None else app_home()
        path = base / path
    return path


def save_storage_paths(
    *,
    character_memory_dir: str = "",
    character_assets_dir: str = "",
    root: str | Path | None = None,
) -> StoragePathConfig:
    path = storage_paths_config_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    config = StoragePathConfig(
        character_memory_dir=str(character_memory_dir or "").strip(),
        character_assets_dir=str(character_assets_dir or "").strip(),
    )
    data = {
        "character_memory_dir": config.character_memory_dir,
        "character_assets_dir": config.character_assets_dir,
    }
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return config


@dataclass(frozen=True)
class AppPaths:
    root: Path

    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    @property
    def state_dir(self) -> Path:
        return self.root / "state"

    @property
    def memory_dir(self) -> Path:
        config = load_storage_paths(self.root)
        return resolve_storage_path(
            config.character_memory_dir,
            root=self.root,
            fallback=default_character_memory_dir(self.root),
        )

    @property
    def characters_dir(self) -> Path:
        config = load_storage_paths(self.root)
        return resolve_storage_path(
            config.character_assets_dir,
            root=self.root,
            fallback=default_character_assets_dir(self.root),
        )

    @property
    def backgrounds_dir(self) -> Path:
        return self.root / "backgrounds"

    @property
    def generated_dir(self) -> Path:
        return self.root / "generated"

    @property
    def cache_dir(self) -> Path:
        return self.root / "cache"

    @property
    def models_dir(self) -> Path:
        return self.root / "models"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def exports_dir(self) -> Path:
        return self.root / "exports"

    @property
    def templates_dir(self) -> Path:
        return self.root / "character_templates"

    @property
    def chat_history_dir(self) -> Path:
        return self.state_dir / "chat_history"

    @property
    def input_images_dir(self) -> Path:
        return self.generated_dir / "input_images"

    @property
    def selfies_dir(self) -> Path:
        return self.generated_dir / "selfies"

    @property
    def sprite_cache_dir(self) -> Path:
        return self.cache_dir / "sprite_cache"

    @property
    def messaging_state_dir(self) -> Path:
        return self.state_dir / "messaging"

    @property
    def tts_audio_dir(self) -> Path:
        return self.generated_dir / "tts_audio"

    def ensure(self) -> "AppPaths":
        for path in (
            self.config_dir,
            self.state_dir,
            self.memory_dir,
            self.characters_dir,
            self.backgrounds_dir,
            self.generated_dir,
            self.cache_dir,
            self.models_dir,
            self.logs_dir,
            self.exports_dir,
            self.templates_dir,
            self.chat_history_dir,
            self.input_images_dir,
            self.selfies_dir,
            self.sprite_cache_dir,
            self.messaging_state_dir,
            self.tts_audio_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        return self


def get_app_paths() -> AppPaths:
    return AppPaths(app_home()).ensure()


def _rewrite_default_character_asset_value(value, paths: AppPaths) -> tuple[object, bool]:
    if isinstance(value, str):
        normalized = value.strip().replace("\\", "/")
        for prefix in DEFAULT_CHARACTER_ASSET_PREFIXES:
            if normalized.startswith(prefix):
                rel = normalized[len(prefix):]
                return (paths.characters_dir / rel).as_posix(), True
        return value, False

    if isinstance(value, list):
        changed = False
        rewritten_items = []
        for item in value:
            rewritten, item_changed = _rewrite_default_character_asset_value(item, paths)
            rewritten_items.append(rewritten)
            changed = changed or item_changed
        return rewritten_items, changed

    if isinstance(value, dict):
        changed = False
        rewritten_dict = {}
        for key, item in value.items():
            rewritten, item_changed = _rewrite_default_character_asset_value(item, paths)
            rewritten_dict[key] = rewritten
            changed = changed or item_changed
        return rewritten_dict, changed

    return value, False


def resolve_character_asset_path(value: str | Path | None, paths: AppPaths | None = None) -> Path:
    """Resolve character asset paths against app storage or the project root."""
    paths = paths or get_app_paths()
    raw = str(value or "").strip()
    normalized = raw.replace("\\", "/")
    for prefix in DEFAULT_CHARACTER_ASSET_PREFIXES:
        if normalized.startswith(prefix):
            return paths.characters_dir / normalized[len(prefix):]
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    if normalized.startswith("characters/"):
        return paths.root / path
    for prefix in PROJECT_RELATIVE_PREFIXES:
        if normalized.startswith(prefix):
            return project_root() / normalized[2:] if prefix.startswith("./") else project_root() / path
    return path


def rewrite_seeded_character_asset_paths(paths: AppPaths | None = None) -> bool:
    """Point seeded default character assets at the configured character folder."""
    paths = paths or get_app_paths()
    config_path = paths.config_dir / "characters.yaml"
    if not config_path.is_file():
        return False
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except Exception:
        return False

    rewritten, changed = _rewrite_default_character_asset_value(data, paths)
    if not changed:
        return False
    config_path.write_text(
        yaml.safe_dump(rewritten, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return True


def seed_defaults(paths: AppPaths | None = None, *, source_root: str | Path | None = None) -> None:
    paths = paths or get_app_paths()
    src_root = Path(source_root).expanduser() if source_root is not None else defaults_dir()
    if not src_root.exists():
        return
    for subdir, target in (
        ("config", paths.config_dir),
        ("character_templates", paths.templates_dir),
        ("characters", paths.characters_dir),
    ):
        source = src_root / subdir
        if not source.exists():
            continue
        target.mkdir(parents=True, exist_ok=True)
        for item in source.iterdir():
            dest = target / item.name
            if dest.exists():
                continue
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)
    rewrite_seeded_character_asset_paths(paths)
