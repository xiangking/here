"""Storage migration helpers shared by desktop frontends."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


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
    config_manager: Any,
    copy_memory: bool = True,
    copy_assets: bool = True,
) -> bool:
    """Copy selected data and rewrite paths rooted in the old asset folder."""
    if copy_memory:
        copy_directory_contents(Path(old_memory_dir), Path(new_memory_dir))
    if not copy_assets:
        return False
    copy_directory_contents(Path(old_assets_dir), Path(new_assets_dir))
    return rewrite_character_asset_paths(
        old_assets_dir,
        new_assets_dir,
        config_manager=config_manager,
    )


def copy_directory_contents(source: Path, target: Path) -> None:
    if source == target or not source.exists():
        target.mkdir(parents=True, exist_ok=True)
        return
    target.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        destination = target / item.name
        if item.is_dir():
            shutil.copytree(item, destination, dirs_exist_ok=True)
        elif item.is_file():
            shutil.copy2(item, destination)


def rewrite_character_asset_paths(
    old_assets_dir: str | Path,
    new_assets_dir: str | Path,
    *,
    config_manager: Any,
) -> bool:
    old_root = Path(old_assets_dir).expanduser()
    new_root = Path(new_assets_dir).expanduser()
    if old_root == new_root:
        return False
    changed = False
    for character in list(config_manager.config.characters or []):
        replacement = replace_prefixed_path(
            getattr(character, "visual_reference_image", ""), old_root, new_root
        )
        if replacement is not None:
            character.visual_reference_image = replacement
            changed = True
        for sprite in list(getattr(character, "sprites", []) or []):
            if rewrite_sprite_paths(sprite, old_root, new_root):
                changed = True
    if changed:
        config_manager.save_characters_config()
    return changed


def rewrite_sprite_paths(sprite: Any, old_root: Path, new_root: Path) -> bool:
    changed = False
    for field in PATH_FIELDS:
        replacement = replace_prefixed_path(sprite_get(sprite, field), old_root, new_root)
        if replacement is not None:
            sprite_set(sprite, field, replacement)
            changed = True
    frames = sprite_get(sprite, "frames")
    if isinstance(frames, list):
        rewritten = [replace_prefixed_path(frame, old_root, new_root) or frame for frame in frames]
        if rewritten != frames:
            sprite_set(sprite, "frames", rewritten)
            changed = True
    return changed


def sprite_get(sprite: Any, field: str) -> Any:
    return sprite.get(field) if isinstance(sprite, dict) else getattr(sprite, field, None)


def sprite_set(sprite: Any, field: str, value: Any) -> None:
    if isinstance(sprite, dict):
        sprite[field] = value
    elif hasattr(sprite, field):
        setattr(sprite, field, value)


def replace_prefixed_path(value: Any, old_root: Path, new_root: Path) -> str | None:
    text = str(value or "").strip()
    if not text or text.lower().startswith(("http://", "https://", "data:")):
        return None
    try:
        relative = Path(text).expanduser().relative_to(old_root)
    except ValueError:
        return None
    return (new_root / relative).as_posix()


def is_strict_child(path: Path, parent: Path) -> bool:
    resolved = path.expanduser().resolve(strict=False)
    resolved_parent = parent.expanduser().resolve(strict=False)
    if resolved == resolved_parent:
        return False
    try:
        resolved.relative_to(resolved_parent)
    except ValueError:
        return False
    return True
