from __future__ import annotations

from typing import Any

from bridge import hooks
from bridge.deps import (
    Path,
    default_character_assets_dir,
    default_character_memory_dir,
    is_strict_child,
    load_storage_paths,
    resolve_storage_path,
    save_storage_paths,
    shutil,
)


def save_storage(self, payload: dict[str, Any]) -> dict[str, Any]:
    old_memory = self.paths.memory_dir
    old_assets = self.paths.characters_dir
    old_config = load_storage_paths(self.paths.root)
    memory_raw = str(payload.get("character_memory_dir") or "").strip()
    assets_raw = str(payload.get("character_assets_dir") or "").strip()
    new_memory = resolve_storage_path(
        memory_raw, root=self.paths.root, fallback=default_character_memory_dir(self.paths.root)
    )
    new_assets = resolve_storage_path(
        assets_raw, root=self.paths.root, fallback=default_character_assets_dir(self.paths.root)
    )
    copy_memory = bool(payload.get("copy_memory", True))
    copy_assets = bool(payload.get("copy_assets", True))
    if copy_memory and is_strict_child(new_memory, old_memory):
        raise ValueError("新的角色记忆目录不能位于旧目录内部。")
    if copy_assets and is_strict_child(new_assets, old_assets):
        raise ValueError("新的角色资产目录不能位于旧目录内部。")
    saved = False
    try:
        new_memory.mkdir(parents=True, exist_ok=True)
        new_assets.mkdir(parents=True, exist_ok=True)
        value = save_storage_paths(
            character_memory_dir=memory_raw,
            character_assets_dir=assets_raw,
            root=self.paths.root,
        )
        saved = True
        hooks.migrate_storage_locations(
            old_memory_dir=old_memory,
            old_assets_dir=old_assets,
            new_memory_dir=new_memory,
            new_assets_dir=new_assets,
            config_manager=self.config,
            copy_memory=copy_memory,
            copy_assets=copy_assets,
        )
        self.reload_runtime()
        return hooks.model_json(value.__dict__)
    except Exception:
        if saved:
            save_storage_paths(
                character_memory_dir=old_config.character_memory_dir,
                character_assets_dir=old_config.character_assets_dir,
                root=self.paths.root,
            )
            self.config.reload()
        raise


def import_legacy(self, payload: dict[str, Any]) -> dict[str, Any]:
    selected = Path(str(payload.get("source_path") or "")).expanduser().resolve()
    candidates = [selected / ".local" / "here", selected]
    source = next(
        (path for path in candidates if (path / "config" / "system_config.yaml").is_file()),
        None,
    )
    if source is None:
        raise ValueError("没有找到旧版 config/system_config.yaml。")
    if source == self.paths.root.resolve():
        raise ValueError("所选目录已经是 Electron 数据目录。")
    copied: list[str] = []
    for name in ("config", "memory", "characters", "backgrounds", "state", "character_templates"):
        origin = source / name
        if not origin.exists():
            continue
        destination = self.paths.root / name
        if origin.is_dir():
            shutil.copytree(origin, destination, dirs_exist_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, destination)
        copied.append(name)
    self.reload_runtime()
    return {
        "sourcePath": str(source),
        "charactersImported": len(self.config.config.characters),
        "settingsImported": "config" in copied,
        "warnings": [
            "旧数据已复制到 Electron 目录；原目录未被修改。",
            "Hermes 自身的全局配置仍由本机 Hermes 安装管理。",
        ],
        "copied": copied,
    }
