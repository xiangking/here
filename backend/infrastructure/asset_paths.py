"""Confine character asset paths to a single owned directory under a root.

``sprite_prefix`` is a public, user-editable folder name. Joining it with a
storage root is only safe when the value is a single path segment that cannot
replace the root, walk upward, or resolve through a symlink to another tree.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
from collections.abc import Callable
from pathlib import Path

SPRITE_PREFIX_PATTERN = re.compile(r"^[0-9A-Za-z_\-\u4e00-\u9fff]+$")


class UnsafeSpritePrefixError(ValueError):
    """Raised when a sprite prefix cannot be used as an asset folder name."""


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


def validate_sprite_prefix(value: str | os.PathLike[str] | None) -> str:
    """Return a single-segment folder name or raise ``UnsafeSpritePrefixError``."""
    text = str(value or "").strip()
    if not text:
        raise UnsafeSpritePrefixError("资源前缀不能为空。")
    if text in {".", ".."}:
        raise UnsafeSpritePrefixError("资源前缀不能是当前目录或上级目录。")
    if text.startswith("~") or os.path.isabs(text) or Path(text).is_absolute():
        raise UnsafeSpritePrefixError("资源前缀不能是绝对路径。")
    if any(separator in text for separator in ("/", "\\")):
        raise UnsafeSpritePrefixError("资源前缀不能包含路径分隔符。")
    if not SPRITE_PREFIX_PATTERN.fullmatch(text):
        raise UnsafeSpritePrefixError("资源前缀只能包含字母、数字、下划线、连字符或中文。")
    return text


def sprite_prefix_in_use(
    characters: list[object],
    prefix: str,
    *,
    exclude_name: str | None = None,
) -> bool:
    wanted = str(prefix or "").strip()
    if not wanted:
        return False
    for character in characters:
        name = str(getattr(character, "name", "") or "").strip()
        if exclude_name and name == exclude_name:
            continue
        if str(getattr(character, "sprite_prefix", "") or "").strip() == wanted:
            return True
    return False


def _root(base: str | Path) -> Path:
    return Path(base).expanduser().resolve(strict=False)


def owned_character_dir(base: str | Path, prefix: str) -> Path:
    """Return ``base / prefix`` after proving it is a strict child of ``base``."""
    name = validate_sprite_prefix(prefix)
    root = _root(base)
    candidate = root / name
    if candidate.is_symlink():
        raise UnsafeSpritePrefixError("资源目录不能是指向其他位置的符号链接。")
    if not candidate.exists():
        return candidate
    resolved = candidate.resolve(strict=False)
    if not is_strict_child(resolved, root):
        raise UnsafeSpritePrefixError("资源路径超出允许的目录。")
    if resolved.relative_to(root).parts != (name,):
        raise UnsafeSpritePrefixError("资源路径超出允许的目录。")
    return resolved


def prepare_owned_character_dir(base: str | Path, prefix: str) -> Path:
    """Create ``base / prefix`` and re-check ownership after mkdir."""
    name = validate_sprite_prefix(prefix)
    root = _root(base)
    candidate = root / name
    if candidate.is_symlink():
        raise UnsafeSpritePrefixError("资源目录不能是指向其他位置的符号链接。")
    candidate.mkdir(parents=True, exist_ok=True)
    if candidate.is_symlink():
        raise UnsafeSpritePrefixError("资源目录不能是指向其他位置的符号链接。")
    resolved = candidate.resolve(strict=False)
    if not is_strict_child(resolved, root) or resolved.relative_to(root).parts != (name,):
        raise UnsafeSpritePrefixError("资源路径超出允许的目录。")
    return resolved


def remove_owned_character_dir(base: str | Path, prefix: str) -> bool:
    """Recursively delete an owned character folder. Returns True if removed."""
    try:
        name = validate_sprite_prefix(prefix)
    except UnsafeSpritePrefixError:
        return False
    root = _root(base)
    candidate = root / name
    try:
        info = candidate.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        return False
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        return False
    resolved = candidate.resolve(strict=False)
    if not is_strict_child(resolved, root):
        return False
    if resolved.relative_to(root).parts != (name,):
        return False
    shutil.rmtree(resolved)
    return True


def is_inside_owned_dir(path: str | Path, owned_dir: str | Path, *, allow_root: bool = False) -> bool:
    """True when ``path`` resolves strictly inside ``owned_dir``."""
    try:
        resolved = Path(path).expanduser().resolve(strict=False)
        root = Path(owned_dir).expanduser().resolve(strict=False)
    except OSError:
        return False
    if resolved == root:
        return allow_root
    return is_strict_child(resolved, root)


# Sprite fields that can hold a filesystem asset reference.
SPRITE_REFERENCE_FIELDS = ("path", "frames", "spritesheet_path", "voice_path")


def _sprite_reference_value(sprite: object, field: str) -> object:
    if isinstance(sprite, dict):
        return sprite.get(field)
    return getattr(sprite, field, "")


def _is_external_reference(text: str) -> bool:
    return text.lower().startswith(("http://", "https://", "data:"))


def _add_resolved_reference(target: set[Path], value: object, resolve: Callable[[str], str | Path]) -> None:
    values = value if isinstance(value, (list, tuple, set)) else (value,)
    for item in values:
        text = str(item or "").strip()
        if not text or _is_external_reference(text):
            continue
        try:
            target.add(Path(resolve(text)).expanduser().resolve(strict=False))
        except (OSError, RuntimeError, ValueError):
            continue


def collect_referenced_asset_paths(
    characters: list[object],
    resolve: Callable[[str], str | Path],
    *,
    skip: tuple[str, int] | None = None,
    skip_sprites_of: str | None = None,
    skip_visual_reference_of: str | None = None,
) -> set[Path]:
    """Resolve every sprite- and character-level asset reference.

    ``resolve`` maps a stored reference (absolute or a supported relative form)
    to a concrete path. ``skip=(name, index)`` omits one sprite, while
    ``skip_sprites_of=name`` omits every sprite of a character that survives
    (e.g. when only its sprites are cleared). ``skip_visual_reference_of=name``
    omits one character's ``visual_reference_image``; the character-level
    reference is otherwise always included, because it keeps the file alive
    even when every sprite of that character is removed.
    """
    referenced: set[Path] = set()
    for character in characters or []:
        name = str(getattr(character, "name", "") or "").strip()
        if skip_sprites_of is None or name != skip_sprites_of:
            sprites = list(getattr(character, "sprites", []) or [])
            for index, sprite in enumerate(sprites):
                if skip is not None and (name, index) == skip:
                    continue
                for field in SPRITE_REFERENCE_FIELDS:
                    _add_resolved_reference(referenced, _sprite_reference_value(sprite, field), resolve)
        if skip_visual_reference_of is not None and name == skip_visual_reference_of:
            continue
        _add_resolved_reference(referenced, getattr(character, "visual_reference_image", ""), resolve)
    return referenced


def is_referenced_target(path: str | Path, referenced: set[Path]) -> bool:
    """True when ``path`` itself, or a directory containing it, is referenced."""
    try:
        resolved = Path(path).expanduser().resolve(strict=False)
    except OSError:
        return False
    return any(item == resolved or is_strict_child(item, resolved) for item in referenced)


def referenced_inside_directory(directory: str | Path, referenced: set[Path]) -> bool:
    """True when any referenced path lives strictly inside ``directory``."""
    try:
        resolved = Path(directory).expanduser().resolve(strict=False)
    except OSError:
        return False
    return any(is_strict_child(item, resolved) for item in referenced)
