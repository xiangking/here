"""Centralized filesystem layout for Here."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "Here"
APP_ID = "here"
ENV_APP_HOME = "HERE_APP_HOME"


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
        return self.root / "memory"

    @property
    def characters_dir(self) -> Path:
        return self.root / "characters"

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


def seed_defaults(paths: AppPaths | None = None) -> None:
    paths = paths or get_app_paths()
    src_root = defaults_dir()
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
